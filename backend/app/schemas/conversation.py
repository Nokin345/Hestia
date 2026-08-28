from datetime import datetime

from pydantic import BaseModel


class ConversationCreate(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None
    skill_id: str | None = None
    pinned: bool | None = None
    kb_enabled: bool | None = None
    memory_enabled: bool | None = None
    reasoning_enabled: bool | None = None
    search_enabled: bool | None = None
    code_enabled: bool | None = None
    mcp_tools: list[str] | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    provider: str
    model: str
    skill_id: str | None
    pinned: bool
    kb_enabled: bool
    memory_enabled: bool
    reasoning_enabled: bool
    search_enabled: bool
    code_enabled: bool
    mcp_tools: list[str] = []
    system_prompt: str = ""
    temperature: float = 0.7
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationPatch(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None
    skill_id: str | None = None
    pinned: bool | None = None
    kb_enabled: bool | None = None
    memory_enabled: bool | None = None
    reasoning_enabled: bool | None = None
    search_enabled: bool | None = None
    code_enabled: bool | None = None
    mcp_tools: list[str] | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class MessageRegenerateRequest(BaseModel):
    content: str
    reasoning: bool | None = None
    search: bool | None = None
    code: bool | None = None
    mcp_tools: list[str] | None = None
    kb: bool | None = None
    memory: bool | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class MessagePatchRequest(BaseModel):
    content: str


class MessagePartOut(BaseModel):
    type: str
    text: str = ""
    image_url: str | None = None
    image_mime: str | None = None
    name: str | None = None
    url: str | None = None


class MessageToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict = {}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    parts: list[MessagePartOut]
    model: str | None = None
    tool_calls: list[MessageToolCallOut] = []
    usage: dict[str, int | float | None] | None = None
    memories_used: list[dict] | None = None
    kb_sources: list[dict] | None = None
    kb_line_ranges: dict[str, list[list[int]]] | None = None
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
