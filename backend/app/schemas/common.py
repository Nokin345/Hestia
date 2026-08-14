from typing import Any

from pydantic import BaseModel, Field


class MessagePart(BaseModel):
    type: str = "text"
    text: str = ""
    image_url: str | None = None
    image_mime: str | None = None
    name: str | None = None
    url: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    parts: list[MessagePart] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
