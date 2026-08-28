from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class McpHeader(BaseModel):
    key: str = ""
    value: str = ""


class McpServerCreate(BaseModel):
    name: str = Field(
        min_length=1, max_length=100, pattern="^[a-zA-Z0-9_-]+$"
    )
    transport: str = Field(default="http", pattern="^(http|sse)$")
    url: str = Field(min_length=1, max_length=500)
    auth_token: str = ""
    headers: list[McpHeader] = Field(default_factory=list)
    enabled: bool = True
    disabled_tools: list[str] = Field(default_factory=list)


class McpServerUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=100, pattern="^[a-zA-Z0-9_-]+$"
    )
    transport: str | None = Field(default=None, pattern="^(http|sse)$")
    url: str | None = Field(default=None, min_length=1, max_length=500)
    auth_token: str | None = None
    headers: list[McpHeader] | None = None
    enabled: bool | None = None
    disabled_tools: list[str] | None = None


class McpServerOut(BaseModel):
    id: str
    name: str
    transport: str
    url: str
    auth_token: str
    headers: list[McpHeader] = Field(default_factory=list)
    enabled: bool
    disabled_tools: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class McpToolOut(BaseModel):
    name: str
    server: str
    raw_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpServerTestRequest(BaseModel):
    transport: str = Field(default="http", pattern="^(http|sse)$")
    url: str = Field(min_length=1, max_length=500)
    auth_token: str = ""
    headers: list[McpHeader] = Field(default_factory=list)


class McpServerTestResult(BaseModel):
    ok: bool
    message: str
    tools: list[McpToolOut] = Field(default_factory=list)
