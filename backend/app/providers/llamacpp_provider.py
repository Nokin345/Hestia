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


class LlamaCppProvider(Provider):
    id = "llamacpp"
    name = "llama.cpp"

    def requires_api_key(self) -> bool:
        return False

    async def list_models(self) -> list[ProviderModelInfo]:
        # llama.cpp doesn't have a standard models endpoint
        # Return an empty list (user configures model directly)
        return []

    @staticmethod
    def _to_api_content(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role in ("tool",):
                for tr in msg.tool_results:
                    api_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.get("id", ""),
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
                        )
                        or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                continue
            content: str | list[dict[str, Any]]
            if any(p.type == "image_url" for p in msg.parts):
                content = []
                for part in msg.parts:
                    if part.type == "image_url" and part.image_url:
                        resolved = resolve_image_to_base64(
                            part.image_url, part.image_mime
                        )
                        if resolved:
                            mime, b64 = resolved
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{b64}"
                                    },
                                }
                            )
                        else:
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": part.image_url},
                                }
                            )
                    elif part.text:
                        content.append({"type": "text", "text": part.text})
            else:
                content = "".join(p.text for p in msg.parts)
            api_messages.append({"role": msg.role, "content": content})
        return api_messages

    @staticmethod
    def _api_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": tool} for tool in tools]

    async def supports_reasoning(self, model: str) -> bool | None:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -3]
        candidates = [f"{root}/props", f"{self.base_url}/props"]
        async with httpx.AsyncClient(timeout=20) as client:
            for url in candidates:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        continue
                    template = resp.json().get("chat_template") or ""
                    return "enable_thinking" in template
                except Exception:
                    continue
        return None

    async def stream(
        self, params: ProviderCallParams
    ) -> AsyncIterator[ProviderStreamEvent]:
        body: dict[str, Any] = {
            "model": params.model,
            "messages": self._to_api_content(params.messages),
            "stream": True,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "stream_options": {"include_usage": True},
        }
        if params.system:
            body["messages"] = [
                {"role": "system", "content": params.system}
            ] + body["messages"]
        if params.tools:
            body["tools"] = self._api_tools(params.tools)
            body["tool_choice"] = "auto"
        if params.reasoning is not None:
            body["chat_template_kwargs"] = {
                "enable_thinking": bool(params.reasoning)
            }

        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream(
                "POST", f"{self.base_url}/chat/completions", json=body
            ) as resp,
        ):
            if resp.status_code != 200:
                text = (await resp.aread()).decode()
                message = text[:500]
                try:
                    parsed = json.loads(text)
                    parsed_message = (parsed.get("error") or {}).get("message")
                    if parsed_message:
                        message = parsed_message
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield ProviderStreamEvent(
                    kind="error", error=f"{resp.status_code}: {message}"
                )
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                raw_usage = chunk.get("usage")
                if raw_usage:
                    usage["input_tokens"] = (
                        raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens")
                    )
                    usage["output_tokens"] = (
                        raw_usage.get("completion_tokens")
                        or raw_usage.get("output_tokens")
                    )
                timings = chunk.get("timings")
                if timings:
                    if (
                        timings.get("prompt_n") is not None
                        and usage.get("input_tokens") is None
                    ):
                        usage["input_tokens"] = timings["prompt_n"]
                    if timings.get("predicted_n") is not None:
                        usage["output_tokens"] = timings["predicted_n"]
                    if timings.get("predicted_per_second"):
                        usage["tokens_per_second"] = round(
                            timings["predicted_per_second"], 1
                        )
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    yield ProviderStreamEvent(kind="text", content=text)
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                if reasoning:
                    yield ProviderStreamEvent(kind="reasoning", content=reasoning)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tool_calls.setdefault(
                        idx,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] = fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]
        for entry in tool_calls.values():
            try:
                arguments = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {}
            yield ProviderStreamEvent(
                kind="tool_call",
                tool_call=ToolCall(
                    id=entry["id"], name=entry["name"], arguments=arguments
                ),
            )
        yield ProviderStreamEvent(kind="done", usage=usage or None)
