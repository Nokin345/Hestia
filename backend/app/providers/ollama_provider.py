import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.providers.base import (
    Provider,
    ProviderCallParams,
    ProviderModelInfo,
    ProviderStreamEvent,
)
from app.providers.image_resolver import resolve_image_to_base64
from app.schemas.common import ChatMessage, ToolCall


class OllamaProvider(Provider):
    id = "ollama"
    name = "Ollama"

    def requires_api_key(self) -> bool:
        return False

    async def list_models(self) -> list[ProviderModelInfo]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        out: list[ProviderModelInfo] = []
        for m in data.get("models", []):
            mid = m.get("name", "")
            if not mid:
                continue
            out.append(
                ProviderModelInfo(
                    id=mid,
                    name=mid,
                    context_window=m.get("context_length"),
                )
            )
        return out

    @staticmethod
    def _to_api_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                for tr in msg.tool_results:
                    api_messages.append(
                        {
                            "role": "tool",
                            "tool_name": tr.get("name", ""),
                            "content": str(tr.get("content", "")),
                        }
                    )
                continue
            if msg.role == "assistant" and msg.tool_calls:
                api_messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(
                            p.text for p in msg.parts if p.type == "text"
                        ),
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                }
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                continue
            text = "".join(p.text for p in msg.parts)
            images = []
            for p in msg.parts:
                if p.type != "image_url" or not p.image_url:
                    continue
                resolved = resolve_image_to_base64(p.image_url, p.image_mime)
                if resolved:
                    images.append(resolved[1])
                elif p.image_url.startswith("data:"):
                    images.append(p.image_url.partition(",")[2])
            entry: dict[str, Any] = {"role": msg.role, "content": text}
            if images:
                entry["images"] = images
            api_messages.append(entry)
        return api_messages

    @staticmethod
    def _api_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": tool} for tool in tools]

    async def supports_reasoning(self, model: str) -> bool | None:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self.base_url}/api/show", json={"model": model}
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
            caps = data.get("capabilities") or []
            if "thinking" in caps:
                return True
            if caps:
                return False
        except Exception:
            pass
        lowered = model.lower()
        if any(k in lowered for k in ("r1", "reason", "think", "qwen3", "deepseek", "glm")):
            return True
        return None

    async def stream(
        self, params: ProviderCallParams
    ) -> AsyncIterator[ProviderStreamEvent]:
        body: dict[str, Any] = {
            "model": params.model,
            "messages": self._to_api_messages(params.messages),
            "stream": True,
            "options": {
                "temperature": params.temperature,
                "num_predict": params.max_tokens,
            },
        }
        if params.tools:
            body["tools"] = self._api_tools(params.tools)
        if params.reasoning is not None:
            body["think"] = bool(params.reasoning)

        tool_calls: list[ToolCall] = []
        usage: dict[str, Any] = {}
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream(
                "POST", f"{self.base_url}/api/chat", json=body
            ) as resp,
        ):
            if resp.status_code != 200:
                text = (await resp.aread()).decode()
                yield ProviderStreamEvent(
                    kind="error", error=f"{resp.status_code}: {text[:500]}"
                )
                return
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = chunk.get("message") or {}
                content = message.get("content")
                if content:
                    yield ProviderStreamEvent(kind="text", content=content)
                thinking = message.get("thinking")
                if thinking:
                    yield ProviderStreamEvent(
                        kind="reasoning", content=thinking
                    )
                for tc in message.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append(
                        ToolCall(
                            id=f"{fn.get('name', '')}-{len(tool_calls)}",
                            name=fn.get("name", ""),
                            arguments=args or {},
                        )
                    )
                if chunk.get("done"):
                    if chunk.get("prompt_eval_count") is not None:
                        usage["input_tokens"] = chunk["prompt_eval_count"]
                    if chunk.get("eval_count") is not None:
                        usage["output_tokens"] = chunk["eval_count"]
                        eval_duration = chunk.get("eval_duration")
                        if eval_duration:
                            usage["tokens_per_second"] = round(
                                chunk["eval_count"] / (eval_duration / 1e9), 1
                            )
        for tc in tool_calls:
            yield ProviderStreamEvent(kind="tool_call", tool_call=tc)
        yield ProviderStreamEvent(kind="done", usage=usage or None)
