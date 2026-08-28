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
from app.core.memory import (
    create_memory,
    extract_memories_with_model,
    find_duplicate,
    format_memory_context,
    load_memory_config,
    process_inline_command,
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
            "Use this to read the full content of a specific page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to read."}
            },
            "required": ["url"],
        },
    },
]

_CODE_TOOL: dict[str, Any] = {
    "name": "run_code",
    "description": (
        "Execute Python code and return its printed output. The code runs in a "
        "sandboxed, network-isolated Linux container (Python 3.12). Files written "
        "under /workspace persist across calls within this conversation.\n\n"
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
            "code": {
                "type": "string",
                "description": "The full Python 3 program to execute. It is saved as "
                "main.py in /workspace and run with python3 main.py. Print the "
                "result with print() so it is returned to you.",
            }
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
                reasoning = None
                try:
                    if await provider.supports_reasoning(model):
                        reasoning = False
                except Exception:
                    reasoning = None
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
                        max_tokens=64,
                        temperature=0.5,
                        reasoning=reasoning,
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

    async def _conversation_transcript(
        self, db: AsyncSession, conversation_id: str, max_messages: int = 60, max_chars: int = 12000
    ) -> str:
        """Render the conversation's user/assistant text as a plain transcript.

        Mirrors odysseus's /api/memory/extract, which runs extraction against
        the entire conversation history rather than the latest exchange.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(max_messages)
        )
        rows = list(reversed((await db.execute(stmt)).scalars().all()))
        lines: list[str] = []
        total = 0
        for row in rows:
            if row.role not in ("user", "assistant"):
                continue
            parts = parts_from_json(row.content)
            text = "".join(p.text or "" for p in parts if p.type == "text").strip()
            if not text:
                continue
            chunk = f"{'User' if row.role == 'user' else 'Assistant'}: {text[:2000]}"
            lines.append(chunk)
            total += len(chunk)
            if total >= max_chars:
                break
        return "\n\n".join(lines)

    async def _extract_memories(
        self,
        conversation_id: str,
        provider_id: str,
        model: str,
        memory_enabled: bool = True,
        saved_queue: asyncio.Queue[str] | None = None,
    ) -> None:
        try:
            async with SessionLocal() as db:
                cfg = await load_memory_config(db)
                if not memory_enabled or not cfg["memory_auto_extract"]:
                    return
                provider = await get_provider(db, provider_id)
                if provider is None:
                    return
                transcript = await self._conversation_transcript(db, conversation_id)
                if not transcript:
                    return
                extracted = await extract_memories_with_model(
                    provider, model, transcript
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
                    if mem is not None and saved_queue is not None:
                        await saved_queue.put(mem.text)
        except Exception:
            return

    async def _remember_response(
        self,
        conversation_id: str,
        provider_id: str,
        model: str,
        remembered: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if remembered:
            await create_memory(
                self.db,
                MemoryCreate(text=remembered),
                source="inline",
                conversation_id=conversation_id,
            )
        ack = "Got it — I've saved that memory."
        msg = ChatMessage(role="assistant", parts=[MessagePart(type="text", text=ack)])
        message_id = await self._save_message(msg, conversation_id, model=model)
        conv = await self.db.get(Conversation, conversation_id)
        if conv:
            if not conv.provider:
                conv.provider = provider_id
                conv.model = model
            if conv.title == "New chat" and remembered:
                conv.title = remembered.replace("\n", " ")[:60]
        await self.db.commit()
        yield {
            "event": "memory_saved",
            "data": json.dumps({}),
        }
        yield {
            "event": "delta",
            "data": json.dumps({"content": ack}),
        }
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                }
            ),
        }

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
            try:
                import httpx

                url = f"{self.settings.code_exec_url}/api/run"
                data = {"code": code, "conversation_id": conversation_id}
                res = await asyncio.wait_for(
                    httpx.AsyncClient(timeout=300).post(url, json=data), timeout=300
                )
                result = res.json()
                stdout = str(result.get("stdout") or "")
                stderr = str(result.get("stderr") or "")
                timed_out = bool(result.get("timed_out"))
                exit_code = int(result.get("exit_code") or 0)
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
            text = await fetch_url(url, cfg.max_chars_per_url)
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
        saved_queue: asyncio.Queue[str] | None = None
        extract_task: asyncio.Task | None = None

        if memory_enabled and user_text:
            is_command, remembered = process_inline_command(user_text)
            if is_command:
                async for event in self._remember_response(
                    conversation_id, provider_id, model, remembered
                ):
                    yield event
                return

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
            f"\n\nCurrent time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"({now.strftime('%A')}).\n"
            f"Current location: {city} (timezone {tz}, {off_label})."
        )
        memories_snapshot: list[dict[str, Any]] | None = None
        if memory_enabled:
            memories = await select_memories_for_query(self.db, user_text)
            memory_context = format_memory_context(
                [m for m, _ in memories]
            )
            if memory_context:
                system += f"\n\n{memory_context}"
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
                    rag_sources = [
                        {
                            "filename": r["metadata"].get("filename", "unknown"),
                            "similarity": r.get("similarity", 0.0),
                        }
                        for r in results
                    ]
                    rag_content = "Relevant documents:\n\n" + "\n\n---\n\n".join(
                        f"[{s['filename']}]\n{r['document']}"
                        for s, r in zip(rag_sources, results)
                    )
                    if len(rag_content) > 10000:
                        rag_content = rag_content[:10000] + "\n[Truncated]"
                    system += f"\n\n{rag_content}"
                    yield {
                        "event": "kb_retrieved",
                        "data": json.dumps(
                            {
                                "count": len(results),
                                "sources": rag_sources,
                            }
                        ),
                    }
            except Exception as exc:
                logger.warning("KB retrieval failed: %s", exc)
        tools: list[dict[str, Any]] = [
            dict(t) for t in _SEARCH_TOOLS
        ] if search else []
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

        if memory_enabled:
            saved_queue = asyncio.Queue()
            extract_task = asyncio.create_task(
                self._extract_memories(
                    conversation_id,
                    provider_id,
                    model,
                    memory_enabled,
                    saved_queue,
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
                    task = asyncio.create_task(
                        self._title_conversation(
                            conversation_id, provider_id, model, first_user
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

        if saved_queue is not None and extract_task is not None:
            # Fire-and-forget: don't block the SSE response on the background
            # memory extraction. Awaiting it here kept the stream open for
            # seconds after `done`, which delayed the streaming->static swap.
            # Extraction continues in _memory_tasks (own DB session); drain
            # only what is already queued.
            while not saved_queue.empty():
                saved_text = saved_queue.get_nowait()
                yield {
                    "event": "memory_saved",
                    "data": json.dumps({"text": saved_text, "count": 1}),
                }
