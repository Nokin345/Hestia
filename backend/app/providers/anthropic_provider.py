import base64
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
from app.schemas.common import ChatMessage, MessagePart, ToolCall


def _resolve_image(part: MessagePart) -> dict[str, Any]:
    resolved = resolve_image_to_base64(part.image_url, part.image_mime)
    if resolved:
        mime, b64 = resolved
        return {"type": "base64", "media_type": mime, "data": b64}
    mime = part.image_mime or "image/png"
    return {"type": "base64", "media_type": mime, "data": _fetch_b64(part.image_url)}


def _fetch_b64(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        return base64.b64encode(resp.read()).decode()


class AnthropicProvider(Provider):
    id = "anthropic"
    name = "Anthropic"

    _api_version = "2023-06-01"
    _base = "https://api.anthropic.com"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self._api_version,
            "content-type": "application/json",
        }

    async def list_models(self) -> list[ProviderModelInfo]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self._base}/v1/models", headers=self._headers())
            if resp.status_code == 404:
                models = []
            else:
                resp.raise_for_status()
                data = resp.json()
                models = [
                    m
                    for m in data.get("data", [])
                    if m.get("id", "").startswith("claude")
                ]
        out: list[ProviderModelInfo] = []
        for m in models:
            mid = m["id"]
            out.append(
                ProviderModelInfo(
                    id=mid,
                    name=mid,
                    context_window=m.get("context_window"),
                )
            )
        return out

    @staticmethod
    def _to_api_content(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                for tr in msg.tool_results:
                    api_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tr.get("id", ""),
                                    "content": str(tr.get("content", "")),
                                }
                            ],
                        }
                    )
                continue
            if msg.role == "assistant":
                content: list[dict[str, Any]] = [
                    {"type": "text", "text": "".join(p.text for p in msg.parts)}
                ]
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                api_messages.append({"role": "assistant", "content": content})
                continue
            content = []
            for part in msg.parts:
                if part.type == "image_url" and part.image_url:
                    content.append({"type": "image", "source": _resolve_image(part)})
                elif part.text:
                    content.append({"type": "text", "text": part.text})
            if not content:
                content = [{"type": "text", "text": ""}]
            api_messages.append({"role": msg.role, "content": content})
        return api_messages

    @staticmethod
    def _api_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for tool in tools:
            out.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )
        return out

    async def stream(
        self, params: ProviderCallParams
    ) -> AsyncIterator[ProviderStreamEvent]:
        body: dict[str, Any] = {
            "model": params.model,
            "messages": self._to_api_content(params.messages),
            "system": params.system,
            "max_tokens": params.max_tokens,
            "temperature": params.temperature,
            "stream": True,
        }
        if params.tools:
            body["tools"] = self._api_tools(params.tools)
            body["tool_choice"] = {"type": "auto"}
        if params.reasoning is False:
            body["thinking"] = {"type": "disabled"}

        active_tools: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream(
                "POST",
                f"{self._base}/v1/messages",
                headers=self._headers(),
                json=body,
            ) as resp,
        ):
            if resp.status_code != 200:
                text = (await resp.aread()).decode()
                yield ProviderStreamEvent(
                    kind="error", error=f"{resp.status_code}: {text[:500]}"
                )
                return
            current_block = 0
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "message_start":
                    msg = event.get("message") or {}
                    u = msg.get("usage") or {}
                    if u.get("input_tokens") is not None:
                        usage["input_tokens"] = u["input_tokens"]
                elif etype == "message_delta":
                    u = event.get("usage") or {}
                    if u.get("output_tokens") is not None:
                        usage["output_tokens"] = u["output_tokens"]
                elif etype == "content_block_start":
                    block = event.get("content_block") or {}
                    current_block = event.get("index", 0)
                    if block.get("type") == "tool_use":
                        active_tools[current_block] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "arguments": "",
                        }
                elif etype == "content_block_delta":
                    delta = event.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        text = delta.get("text", "")
                        yield ProviderStreamEvent(kind="text", content=text)
                    elif dtype == "thinking_delta":
                        thinking = delta.get("thinking", "")
                        yield ProviderStreamEvent(
                            kind="reasoning", content=thinking
                        )
                    elif dtype == "input_json_delta":
                        idx = event.get("index", 0)
                        if idx in active_tools:
                            active_tools[idx]["arguments"] += delta.get(
                                "partial_json", ""
                            )
                elif etype == "error":
                    err = event.get("error", {})
                    yield ProviderStreamEvent(kind="error", error=str(err))
                    return
        for entry in active_tools.values():
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
