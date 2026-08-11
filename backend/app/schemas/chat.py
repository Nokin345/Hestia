from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import MessagePart


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    provider: str | None = None
    model: str | None = None
    skill_id: str | None = None
    content: str
    parts: list[MessagePart] = Field(default_factory=list)
    reasoning: bool | None = None
    search: bool | None = None
    code: bool | None = None
    mcp_tools: list[str] | None = None
    kb: bool | None = None
    memory: bool | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class ToolStatusEvent(BaseModel):
    type: str = "tool_status"
    name: str
    status: str
    message: str = ""


class ToolResultEvent(BaseModel):
    type: str = "tool_result"
    name: str
    ok: bool
    summary: str = ""


class DeltaEvent(BaseModel):
    type: str = "delta"
    content: str


class DoneEvent(BaseModel):
    type: str = "done"
    message_id: str


class ErrorEvent(BaseModel):
    type: str = "error"
    message: str


class ChatEvent(BaseModel):
    event: Any
