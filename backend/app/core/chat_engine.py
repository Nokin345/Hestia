import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.defaults_config import load_defaults_config
from app.core.memory import (
    create_memory,
    extract_memories_with_model,
    find_duplicate,
    format_memory_context,
    has_content_words,
    load_memory_config,
    select_memories_for_query,
)
from app.core.search import fetch_url, search_and_fetch
from app.core.search_config import load_search_config
from app.db import SessionLocal
from app.models import Conversation, Message
from app.providers.base import ProviderCallParams
from app.providers.registry import get_provider
from app.schemas.common import ChatMessage, MessagePart, ToolCall
from app.schemas.memory import MemoryCreate

logger = logging.getLogger(__name__)

_title_tasks: set[asyncio.Task] = set()
_memory_tasks: set[asyncio.Task] = set()

_SEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current or factual information. Returns a list of results "
            "with titles, URLs and snippets, and fetches readable text from the top pages. "
            "Use this when the answer requires up-to-date or external information."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_url",
        "description": (
            "Fetch a single URL and return its readable text content. "
            "Use this to read the full content of a specific page. "
            "Default max_chars: {default_chars}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to read."},
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters to return (default {default_chars}). "
                                   "Set higher (up to 50000) for long articles, "
                                   "or lower to save tokens.",
                },
            },
            "required": ["url"],
        },
    },
]

_READ_URL_MAX = 50000

_CODE_TOOL: dict[str, Any] = {
    "name": "run_code",
    "description": (
        "Execute code and return its printed output. The code runs in a "
        "network-isolated sandbox with pre-installed Python, Node.js, Go, and "
        "Java runtimes. Each run is a fresh, stateless environment: nothing "
        "persists between calls, so put everything you need in a single "
        "program.\n\n"
        "USE THIS TOOL for any calculation or numeric work: complex arithmetic, "
        "multiplication/division of large numbers, probability and statistics, "
        "data processing, string/date manipulation, or any computation where a "
        "precise programmatic answer matters. You MUST prefer running code over "
        "answering from memory whenever exactness is important — a wrong number "
        "in a calculation is a serious error, so always verify computations by "
        "executing them. For exact arithmetic use Python ints or the fractions "
        "module, not floats. The script's stdout and stderr are returned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": ["python", "java", "node", "go"],
                "description": "Which runtime to execute the code with. "
                "python: saved as main.py, run with python3. "
                "java: expects a public class Main, saved as Main.java, "
                "compiled with javac and run. "
                "node: saved as main.js, run with node (JavaScript). "
                "go: saved as main.go, run with go run. "
                "Default: python.",
            },
            "code": {
                "type": "string",
                "description": "The full program to execute in the chosen "
                "language. Print/println the result so it is returned to you.",
            },
        },
        "required": ["code"],
    },
}


def parts_to_json(parts: list[MessagePart]) -> str:
    return json.dumps(
        [p.model_dump(exclude_none=True) for p in parts], ensure_ascii=False
    )


def parts_from_json(raw: str | None) -> list[MessagePart]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [MessagePart(**p) for p in data if isinstance(p, dict)]


def _tool_results_dict(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return tool_results


def _utf16_len(s: str) -> int:
    # JS string length counts UTF-16 code units (astral chars = 2 units),
    # while Python's len() counts code points. The frontend parser measures
    # payloads with JS .length, so the length prefix must match that.
    return len(s.encode("utf-16-le")) // 2


def _format_tool_message(
    tc: ToolCall, ok: bool, content: str, args: dict[str, Any] | None = None
) -> str:
    args = args if args is not None else (tc.arguments or {})
    args_json = json.dumps(args, ensure_ascii=False)
    body = json.dumps(content, ensure_ascii=False)
    return (
        f"{tc.name} | {'ok' if ok else 'failed'}"
        f"\nA{_utf16_len(args_json)}\n{args_json}"
        f"\nC{_utf16_len(body)}\n{body}"
    )


class ChatEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def _title_conversation(
        self,
        conversation_id: str,
        provider_id: str,
        model: str,
        first_user: str,
    ) -> None:
        try:
            async with SessionLocal() as db:
                provider = await get_provider(db, provider_id)
                if provider is None:
                    return
                title = ""
                async for event in provider.stream(
                    ProviderCallParams(
                        model=model,
                        system=(
                            "You are a title generator. Reply with a short conversation "
                            "title, max 60 characters, no quotes or punctuation."
                        ),
                        messages=[
                            ChatMessage(
                                role="user",
                                parts=[
                                    MessagePart(
                                        type="text",
                                        text=f"Title this conversation (first user message):\n{first_user[:400]}",
                                    )
                                ],
                            )
                        ],
                        tools=[],
                        # Headroom: a title needs ~30 tokens, but models that
                        # cannot disable thinking may spend more before it.
                        max_tokens=300,
                        temperature=0.5,
                        reasoning=False,
                    )
                ):
                    if event.kind == "text":
                        title += event.content
                title = title.strip().split("\n")[0].strip(' "\'\t')[:60]
                if not title:
                    return
                conv = await db.get(Conversation, conversation_id)
                if conv:
                    conv.title = title
                    await db.commit()
        except Exception:
            return

    @classmethod
    def _recent_text(
        cls, history: list[ChatMessage], user_parts: list[MessagePart]
    ) -> str:
        """Current user query text, for the recall query."""
        return "".join(p.text or "" for p in user_parts).strip()

    @classmethod
    def _recent_has_content(
        cls, history: list[ChatMessage], user_parts: list[MessagePart]
    ) -> bool:
        """True if the latest user message has meaningful words.

        Trivial-turn guard: "hi"/"ok"/"thanks" skip recall/extraction; a
        message with real content proceeds. Recall/extraction still use the
        last 6 messages as context via _recent_text.
        """
        cur = "".join(p.text or "" for p in user_parts).strip()
        return has_content_words(cur)

    async def _utility_model_for(
        self, fallback_provider_id: str, fallback_model: str
    ) -> tuple[str, str]:
        """Resolve the provider/model for background tasks (titles, memory extraction).

        Returns the configured utility model when set; otherwise the chat
        provider/model so behaviour matches "Same as chat model".
        """
        try:
            cfg = await load_defaults_config(self.db)
            util = (cfg.utility_model or "").strip()
            if util and "::" in util:
                provider_id, model = util.split("::", 1)
                provider_id, model = provider_id.strip(), model.strip()
                if provider_id and model and await get_provider(self.db, provider_id) is not None:
                    return provider_id, model
        except Exception:
            pass
        return fallback_provider_id, fallback_model

    async def _extract_memories(
        self,
        conversation_id: str,
        util_provider_id: str,
        util_model: str,
        main_provider_id: str,
        main_model: str,
        memory_enabled: bool = True,
    ) -> None:
        try:
            async with SessionLocal() as db:
                cfg = await load_memory_config(db)
                if not memory_enabled or not cfg["memory_auto_extract"]:
                    return

                is_separate = (
                    util_provider_id != main_provider_id or util_model != main_model
                )
                provider_id = util_provider_id if is_separate else main_provider_id
                model = util_model if is_separate else main_model

                provider = await get_provider(db, provider_id)
                if provider is None:
                    return

                history = await self._load_history(conversation_id)
                user_text = ""
                assistant_text = ""
                for m in reversed(history):
                    text = "".join(
                        p.text or "" for p in m.parts if p.type == "text"
                    ).strip()
                    if not text:
                        continue
                    if not user_text and m.role == "user":
                        user_text = text
                    elif not assistant_text and m.role == "assistant":
                        assistant_text = text
                    if user_text and assistant_text:
                        break

                if not user_text:
                    return

                extracted = await extract_memories_with_model(
                    provider, model, user_text, assistant_text
                )
                for item in extracted:
                    if await find_duplicate(db, item["text"]) is not None:
                        continue
                    mem = await create_memory(
                        db,
                        MemoryCreate(text=item["text"], category=item["category"]),
                        source="auto",
                        conversation_id=conversation_id,
                    )
        except Exception:
            return

    async def _load_history(self, conversation_id: str) -> list[ChatMessage]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        history: list[ChatMessage] = []
        for row in rows:
            parts = parts_from_json(row.content)
            tool_calls: list[ToolCall] = []
            if row.tool_calls:
                try:
                    tool_calls = [ToolCall(**tc) for tc in json.loads(row.tool_calls)]
                except (json.JSONDecodeError, TypeError):
                    tool_calls = []
            tool_results: list[dict[str, Any]] = []
            if row.tool_results:
                try:
                    tool_results = json.loads(row.tool_results)
                except json.JSONDecodeError:
                    tool_results = []
            history.append(
                ChatMessage(
                    role=row.role,
                    parts=parts,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                )
            )
        return history

    async def _save_message(
        self,
        msg: ChatMessage,
        conversation_id: str,
        usage: dict[str, Any] | None = None,
        model: str | None = None,
        memories_used: list[dict[str, Any]] | None = None,
    ) -> str:
        row = Message(
            conversation_id=conversation_id,
            role=msg.role,
            content=parts_to_json(msg.parts),
            model=model,
            usage=json.dumps(usage, ensure_ascii=False) if usage else None,
            memories_used=json.dumps(memories_used, ensure_ascii=False)
            if memories_used
            else None,
            tool_calls=json.dumps(
                [tc.model_dump() for tc in msg.tool_calls], ensure_ascii=False
            )
            if msg.tool_calls
            else None,
            tool_results=json.dumps(msg.tool_results, ensure_ascii=False)
            if msg.tool_results
            else None,
        )
        self.db.add(row)
        await self.db.flush()
        return row.id

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def _estimate_request_tokens(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
    ) -> int:
        body: dict[str, Any] = {
            "model": "",
            "messages": [
                {
                    "role": m.role,
                    "content": "".join(p.text or "" for p in m.parts),
                }
                | (
                    {
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ]
                    }
                    if m.tool_calls
                    else {}
                )
                | (
                    {
                        "tool_results": [
                            {
                                "id": tr.get("id", ""),
                                "name": tr.get("name", ""),
                                "content": tr.get("content", ""),
                            }
                            for tr in m.tool_results
                        ]
                    }
                    if m.tool_results
                    else {}
                )
                for m in messages
            ],
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 16384,
            "tools": tools,
        }
        if system:
            body["messages"] = [{"role": "system", "content": system}] + body["messages"]
        return self._estimate_tokens(json.dumps(body, ensure_ascii=False))

    async def _execute_tool(
        self, tc: ToolCall, conversation_id: str = ""
    ) -> tuple[bool, str]:
        name = tc.name
        args = tc.arguments or {}
        if name == "run_code":
            code = str(args.get("code") or "").strip()
            if not code:
                return False, "run_code: missing 'code' argument"
            language = str(args.get("language") or "python").strip().lower()
            if language == "node":
                language = "javascript"
            if language not in ("python", "java", "javascript", "go"):
                language = "python"
            filename = {
                "python": "main.py",
                "javascript": "main.js",
                "go": "main.go",
                "java": "Main.java",
            }[language]
            try:
                import httpx

                url = f"{self.settings.piston_url}/api/v2/execute"
                payload = {
                    "language": language,
                    "version": "*",
                    "files": [{"name": filename, "content": code.replace("\r\n", "\n")}],
                    "run_timeout": 60_000,
                    "compile_timeout": 60_000,
                    "run_memory_limit": 512 * 1024 * 1024,
                }
                res = await asyncio.wait_for(
                    httpx.AsyncClient(timeout=300).post(url, json=payload), timeout=300
                )
                if res.status_code != 200:
                    detail = ""
                    try:
                        detail = res.json().get("message", "")
                    except Exception:
                        pass
                    return False, (
                        f"run_code: piston error"
                        + (f": {detail}" if detail else f" (HTTP {res.status_code})")
                    )
                result = res.json()
                run = result.get("run") or {}
                compile_ = result.get("compile") or {}
                stdout = str(run.get("stdout") or "") + str(compile_.get("stdout") or "")
                stderr = str(run.get("stderr") or "")
                if compile_.get("stderr"):
                    stderr = f"{compile_.get('stderr')}\n{stderr}".strip()
                exit_code = int(run.get("code") or 0)
                status = run.get("status")
                timed_out = status in ("TO", "SG")
                combined = stdout + (f"\n{stderr}" if stderr else "")
                if not combined:
                    combined = "(no output)"
                if timed_out:
                    combined += "\n[Execution timed out]"
                combined += f"\n[exit code: {exit_code}]"
                return True, combined
            except asyncio.TimeoutError:
                return False, "run_code: sandbox timed out"
            except Exception as exc:
                return False, f"run_code: sandbox error: {exc}"
        cfg = await load_search_config(self.db)
        if name == "web_search":
            query = str(args.get("query") or "").strip()
            if not query:
                return False, "web_search: missing 'query' argument"
            result = await search_and_fetch(
                query,
                cfg.searxng_url,
                cfg.max_results,
                cfg.fallback,
                cfg.fetch_urls,
                cfg.fetch_limit,
                cfg.max_chars_per_url,
            )
            payload = {
                "engine": result.get("engine"),
                "results": result.get("results") or [],
                "fetched": result.get("fetched") or [],
            }
            return True, json.dumps(payload, ensure_ascii=False)
        if name == "read_url":
            url = str(args.get("url") or "").strip()
            if not url:
                return False, "read_url: missing 'url' argument"
            requested = int(args.get("max_chars", cfg.max_chars_per_url))
            limit = min(max(requested, 500), _READ_URL_MAX)
            text = await fetch_url(url, limit)
            if not text:
                return False, f"read_url: could not read {url}"
            return True, text
        if "." in name:
            prefix, tool_name = name.split(".", 1)
            from app.core.mcp import call_mcp_tool, get_mcp_server_by_prefix

            server = await get_mcp_server_by_prefix(self.db, prefix)
            if server is not None:
                return await call_mcp_tool(server, tool_name, args)
        return False, f"Unknown tool: {name}"

    async def stream_chat(
        self,
        conversation_id: str,
        provider_id: str,
        model: str,
        user_parts: list[MessagePart],
        save_user: bool = True,
        reasoning: bool | None = None,
        search: bool = False,
        code: bool = False,
        kb_enabled: bool = False,
        memory_enabled: bool | None = None,
        mcp_tools: list[str] | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        provider = await get_provider(self.db, provider_id)
        if provider is None:
            yield {
                "event": "error",
                "data": json.dumps({"message": f"Unknown provider: {provider_id}"}),
            }
            return
        if provider.requires_api_key() and not provider.configured:
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "message": (
                            f"Provider '{provider_id}' has no API key. "
                            "Add one in Settings."
                        )
                    }
                ),
            }
            return

        # Tell the client the real conversation id up front (the route already
        # created the row). Without this the frontend only learns the id from
        # `done`, so stopping mid-stream on a brand-new chat would leave it at
        # "/" unable to edit/refetch its own just-saved message.
        yield {
            "event": "conversation",
            "data": json.dumps({"conversation_id": conversation_id}),
        }

        if save_user:
            await self._save_message(
                ChatMessage(role="user", parts=user_parts),
                conversation_id,
                model=model,
            )
            await self.db.commit()

        user_text = "".join(p.text or "" for p in user_parts).strip()
        memory_cfg = await load_memory_config(self.db)
        global_memory_enabled = memory_cfg["enable_memory"]
        memory_enabled = global_memory_enabled and (
            memory_enabled if memory_enabled is not None else True
        )
        extract_task: asyncio.Task | None = None

        history = await self._load_history(conversation_id)

        system = system_prompt or "You are a helpful assistant."
        now = datetime.now().astimezone()
        tz = os.environ.get("TZ", "").strip() or "UTC"
        city = tz.split("/")[-1].replace("_", " ") or tz
        off = now.utcoffset()
        if off is None:
            off_label = "UTC"
        else:
            total = int(off.total_seconds())
            sign = "+" if total >= 0 else "-"
            total = abs(total)
            off_label = f"UTC{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"
        system += (
            f"\n\nCurrent date: {now.strftime('%Y-%m-%d')} ({now.strftime('%A')}).\n"
            f"Current location: {city} (timezone {tz}, {off_label})."
        )
        memories_snapshot: list[dict[str, Any]] | None = None
        memory_context = ""
        rag_content = ""
        recent_text = self._recent_text(history, user_parts)
        recent_has_content = self._recent_has_content(history, user_parts)
        if memory_enabled:
            # Empty query for trivial turns: skips retrieval, keeps pinned only.
            memories = await select_memories_for_query(
                self.db, recent_text if recent_has_content else ""
            )
            memory_context = format_memory_context(
                [m for m, _ in memories]
            )
            if memories:
                memories_snapshot = [
                    {
                        "id": m.id,
                        "text": m.text,
                        "category": m.category,
                        "type": typ,
                    }
                    for m, typ in memories
                ]
                yield {
                    "event": "memory_retrieved",
                    "data": json.dumps(
                        {
                            "count": len(memories),
                            "memories": memories_snapshot,
                        }
                    ),
                }
        if kb_enabled:
            try:
                from sqlalchemy import select

                from app.core.kb_vector import get_kb_store
                from app.models import KbDocument

                res = await self.db.execute(
                    select(KbDocument.id).where(KbDocument.enabled.is_(True))
                )
                enabled_ids = list(res.scalars().all())
                store = await get_kb_store(self.db)
                results = (
                    store.search(user_text, k=5, doc_ids=enabled_ids)
                    if enabled_ids
                    else []
                )
                if results:
                    match_count = sum(1 for r in results if r.get("role") == "match")
                    rag_sources = [
                        {
                            "filename": r["metadata"].get("filename", "unknown"),
                            "similarity": r.get("similarity", 0.0),
                            "role": r.get("role", "match"),
                        }
                        for r in results
                    ]

                    # Group by document, show chunks in order
                    doc_groups: dict[str, list[dict]] = {}
                    for r in results:
                        fn = r["metadata"].get("filename", "unknown")
                        doc_groups.setdefault(fn, []).append(r)

                    parts: list[str] = []
                    for fn, chunks in doc_groups.items():
                        block = f"[{fn}]"
                        for c in chunks:
                            role = c.get("role", "match")
                            chunk_i = c["metadata"].get("chunk", 0)
                            label = f"chunk {chunk_i}" if role == "match" else f"context {chunk_i}"
                            block += f"\n\n[{label}]\n{c['document']}"
                        parts.append(block)

                    rag_content = "Relevant documents:\n\n" + "\n\n---\n\n".join(parts)
                    if len(rag_content) > 10000:
                        rag_content = rag_content[:10000] + "\n[Truncated]"
                    yield {
                        "event": "kb_retrieved",
                        "data": json.dumps(
                            {
                                "count": match_count,
                                "sources": rag_sources,
                            }
                        ),
                    }
            except Exception as exc:
                logger.warning("KB retrieval failed: %s", exc)
        tools: list[dict[str, Any]] = []
        if search:
            try:
                _search_cfg = await load_search_config(self.db)
                default_chars = _search_cfg.max_chars_per_url
            except Exception:
                default_chars = 4000
            for t in _SEARCH_TOOLS:
                if t["name"] == "read_url":
                    td = {
                        "name": t["name"],
                        "description": t["description"].format(
                            default_chars=default_chars
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                k: {
                                    "type": v["type"],
                                    "description": v["description"].format(
                                        default_chars=default_chars
                                    ),
                                }
                                for k, v in t["parameters"]["properties"].items()
                            },
                            "required": list(t["parameters"]["required"]),
                        },
                    }
                else:
                    td = dict(t)
                tools.append(td)
        if code:
            tools.append(dict(_CODE_TOOL))
        if mcp_tools:
            from app.core.mcp import list_all_mcp_tools

            mcp_tools_list = await list_all_mcp_tools(self.db, None, mcp_tools)
            tools.extend(
                {
                    "name": t.name,
                    "description": t.description
                    or f"An MCP tool exposed by the '{t.server}' server.",
                    "parameters": t.input_schema,
                }
                for t in mcp_tools_list
            )
            if mcp_tools_list:
                tools_note = ", ".join(
                    f"{t.name}" for t in mcp_tools_list[:8]
                )
                suffix = " and more" if len(mcp_tools_list) > 8 else ""
                system += (
                    "\n\nYou have access to MCP tools (prefixed with their server "
                    f"name): {tools_note}{suffix}. Call them exactly as named; "
                    "the result comes back as text."
                )

        provider_messages: list[ChatMessage] = list(history)
        provider_usage: dict[str, Any] = {}
        generation_started: float | None = None
        any_tool_used = False

        # Dynamic retrieval (memories, RAG) goes at the END of the prompt, not in
        # the system block, so the prefix [static system + prior turns] stays
        # identical between requests and llama.cpp can reuse its KV cache. Only
        # the latest user turn + this tail changes per request.
        tail_blocks = [memory_context, rag_content]
        if any(tail_blocks):
            for msg in reversed(provider_messages):
                if msg.role == "user":
                    msg.parts.append(
                        MessagePart(
                            text="\n\n" + "\n\n".join(b for b in tail_blocks if b)
                        )
                    )
                    break

        while True:
            iter_parts: list[MessagePart] = []
            iter_tool_calls: list[ToolCall] = []
            params = ProviderCallParams(
                model=model,
                system=system,
                messages=provider_messages,
                tools=tools,
                reasoning=reasoning,
                temperature=temperature if temperature is not None else 0.7,
            )
            try:
                async for event in provider.stream(params):
                    if event.kind == "error":
                        yield {
                            "event": "error",
                            "data": json.dumps({"message": event.error}),
                        }
                        return
                    if event.kind == "done":
                        provider_usage = event.usage or {}
                        continue
                    if event.kind == "text":
                        if generation_started is None:
                            generation_started = time.monotonic()
                        if iter_parts and iter_parts[-1].type == "text":
                            iter_parts[-1].text += event.content
                        else:
                            iter_parts.append(
                                MessagePart(type="text", text=event.content)
                            )
                        yield {
                            "event": "delta",
                            "data": json.dumps({"content": event.content}),
                        }
                    elif event.kind == "reasoning":
                        if generation_started is None:
                            generation_started = time.monotonic()
                        if iter_parts and iter_parts[-1].type == "reasoning":
                            iter_parts[-1].text += event.content
                        else:
                            iter_parts.append(
                                MessagePart(type="reasoning", text=event.content)
                            )
                        yield {
                            "event": "reasoning",
                            "data": json.dumps({"content": event.content}),
                        }
                    elif event.kind == "tool_call" and event.tool_call is not None:
                        iter_tool_calls.append(event.tool_call)
                        yield {
                            "event": "tool_call",
                            "data": json.dumps(event.tool_call.model_dump()),
                        }
            except Exception as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": str(exc)}),
                }
                return

            if not iter_tool_calls:
                assistant_parts = iter_parts
                break

            any_tool_used = True
            # Persist the pre-tool assistant turn (its reasoning/text so far).
            await self._save_message(
                ChatMessage(
                    role="assistant", parts=iter_parts, tool_calls=iter_tool_calls
                ),
                conversation_id,
                model=model,
            )

            # Execute the tools and persist a tool message with the returned content.
            results: list[dict[str, Any]] = []
            tool_parts_text: list[str] = []
            for tc in iter_tool_calls:
                try:
                    ok, content = await self._execute_tool(tc, conversation_id)
                except Exception as exc:
                    ok, content = False, str(exc)
                results.append(
                    {"id": tc.id, "name": tc.name, "ok": ok, "content": content}
                )
                tool_parts_text.append(_format_tool_message(tc, ok, content))
                yield {
                    "event": "tool",
                    "data": json.dumps(
                        {
                            "name": tc.name,
                            "ok": ok,
                            "arguments": tc.arguments,
                            "content": content,
                        }
                    ),
                }

            await self._save_message(
                ChatMessage(
                    role="tool",
                    parts=[
                        MessagePart(type="text", text="\n\n".join(tool_parts_text))
                    ],
                    tool_results=results,
                ),
                conversation_id,
                model=model,
            )
            await self.db.commit()

            provider_messages.append(
                ChatMessage(
                    role="assistant",
                    parts=list(iter_parts),
                    tool_calls=iter_tool_calls,
                )
            )
            provider_messages.append(
                ChatMessage(role="tool", parts=[], tool_results=results)
            )

        if not any_tool_used and not assistant_parts:
            yield {
                "event": "error",
                "data": json.dumps({"message": "Empty response from model."}),
            }
            return

        usage: dict[str, Any] = {}
        in_tok = provider_usage.get("input_tokens")
        out_tok = provider_usage.get("output_tokens")
        tps = provider_usage.get("tokens_per_second")
        if in_tok is None:
            in_tok = self._estimate_request_tokens(
                system, provider_messages, tools
            )
        if out_tok is None:
            out_tok = self._estimate_tokens(
                "".join(p.text or "" for p in assistant_parts)
            )
        gen_secs = None
        if generation_started is not None:
            gen_secs = time.monotonic() - generation_started
            if tps is None and out_tok and gen_secs > 0:
                tps = round(out_tok / gen_secs, 1)
        usage["input_tokens"] = in_tok
        usage["output_tokens"] = out_tok
        usage["total_tokens"] = (in_tok or 0) + (out_tok or 0)
        if tps is not None:
            usage["tokens_per_second"] = round(tps, 1)

        msg = ChatMessage(role="assistant", parts=assistant_parts)
        message_id = await self._save_message(
            msg,
            conversation_id,
            usage=usage,
            model=model,
            memories_used=memories_snapshot,
        )
        await self.db.commit()

        if memory_enabled and recent_has_content:
            util_provider, util_model = await self._utility_model_for(provider_id, model)
            extract_task = asyncio.create_task(
                self._extract_memories(
                    conversation_id,
                    util_provider,
                    util_model,
                    provider_id,
                    model,
                    memory_enabled,
                )
            )
            _memory_tasks.add(extract_task)
            extract_task.add_done_callback(_memory_tasks.discard)
        conv = await self.db.get(Conversation, conversation_id)
        if conv:
            if not conv.provider:
                conv.provider = provider_id
                conv.model = model
            first_user = "".join(p.text or "" for p in user_parts).strip()
            if conv.title == "New chat":
                text_parts = [p.text for p in assistant_parts if p.type == "text"]
                if text_parts:
                    first = text_parts[0].strip().replace("\n", " ")
                    conv.title = first[:60]
                if first_user:
                    title_provider, title_model = await self._utility_model_for(provider_id, model)
                    task = asyncio.create_task(
                        self._title_conversation(
                            conversation_id, title_provider, title_model, first_user
                        )
                    )
                    _title_tasks.add(task)
                    task.add_done_callback(_title_tasks.discard)
            await self.db.commit()

        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "usage": usage,
                }
            ),
        }
