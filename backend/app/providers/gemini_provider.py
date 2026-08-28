import json
import urllib.parse
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


def _image_data(part: MessagePart) -> tuple[str, str] | None:
    return resolve_image_to_base64(part.image_url, part.image_mime)


class GeminiProvider(Provider):
    id = "gemini"
    name = "Google Gemini"

    _base = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def list_models(self) -> list[ProviderModelInfo]:
        url = f"{self._base}/models?key={self.api_key}"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        out: list[ProviderModelInfo] = []
        for m in data.get("models", []):
            mid = m.get("name", "")
            if not mid:
                continue
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            mid = mid.rsplit("/", 1)[-1]
            out.append(
                ProviderModelInfo(
                    id=mid,
                    name=mid,
                    context_window=m.get("inputTokenLimit"),
                )
            )
        return out

    @staticmethod
    def _to_api_contents(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = "model" if msg.role in ("assistant", "model") else msg.role
            if role == "tool":
                for tr in msg.tool_results:
                    api_messages.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "functionResponse": {
                                        "name": tr.get("name", ""),
                                        "response": {"result": tr.get("content", "")},
                                    }
                                }
                            ],
                        }
                    )
                continue
            parts: list[dict[str, Any]] = []
            for part in msg.parts:
                if part.type == "image_url" and part.image_url:
                    img = _image_data(part)
                    if img:
                        parts.append(
                            {"inlineData": {"mimeType": img[0], "data": img[1]}}
                        )
                elif part.text:
                    parts.append({"text": part.text})
            for tc in msg.tool_calls:
                parts.append({"functionCall": {"name": tc.name, "args": tc.arguments}})
            if not parts:
                parts = [{"text": ""}]
            api_messages.append({"role": role, "parts": parts})
        return api_messages

    @staticmethod
    def _api_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tools:
            return []
        return [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                    for t in tools
                ],
                "functionCallingConfig": {"mode": "AUTO"},
            }
        ]

    async def stream(
        self, params: ProviderCallParams
    ) -> AsyncIterator[ProviderStreamEvent]:
        model = urllib.parse.quote(params.model)
        url = (
            f"{self._base}/models/{model}:streamGenerateContent"
            f"?alt=sse&key={self.api_key}"
        )
        body: dict[str, Any] = {
            "contents": self._to_api_contents(params.messages),
            "generationConfig": {
                "temperature": params.temperature,
                "maxOutputTokens": params.max_tokens,
            },
        }
        if params.system:
            body["systemInstruction"] = {"parts": [{"text": params.system}]}
        if params.tools:
            body["tools"] = self._api_tools(params.tools)
        if params.reasoning is False:
            body.setdefault("generationConfig", {})["thinkingConfig"] = {
                "thinkingBudget": 0
            }

        tool_calls: dict[str, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream("POST", url, headers=self._headers(), json=body) as resp,
        ):
            if resp.status_code != 200:
                text = (await resp.aread()).decode()
                yield ProviderStreamEvent(
                    kind="error", error=f"{resp.status_code}: {text[:500]}"
                )
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                metadata = chunk.get("usageMetadata")
                if metadata:
                    if metadata.get("promptTokenCount") is not None:
                        usage["input_tokens"] = metadata["promptTokenCount"]
                    if metadata.get("candidatesTokenCount") is not None:
                        usage["output_tokens"] = metadata["candidatesTokenCount"]
                    if metadata.get("thoughtsTokenCount"):
                        usage["reasoning_tokens"] = metadata["thoughtsTokenCount"]
                candidates = chunk.get("candidates") or []
                if not candidates:
                    continue
                content = candidates[0].get("content") or {}
                for part in content.get("parts") or []:
                    if "text" in part:
                        if part.get("thought"):
                            yield ProviderStreamEvent(
                                kind="reasoning", content=part["text"]
                            )
                        else:
                            yield ProviderStreamEvent(kind="text", content=part["text"])
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        name = fc.get("name", "")
                        tc = ToolCall(
                            id=f"{name}-{len(tool_calls)}",
                            name=name,
                            arguments=fc.get("args") or {},
                        )
                        tool_calls[name] = tc
                        yield ProviderStreamEvent(kind="tool_call", tool_call=tc)
        yield ProviderStreamEvent(kind="done", usage=usage or None)
