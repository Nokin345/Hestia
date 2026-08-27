from pydantic import BaseModel, Field


class DefaultsOut(BaseModel):
    default_kb_enabled: bool = False
    default_memory_enabled: bool = False
    default_search_enabled: bool = False
    default_code_enabled: bool = False
    default_mcp_enabled: bool = False
    default_model: str = ""
    utility_model: str = ""
    default_system_prompt: str = ""


class DefaultsUpdate(BaseModel):
    default_kb_enabled: bool | None = None
    default_memory_enabled: bool | None = None
    default_search_enabled: bool | None = None
    default_code_enabled: bool | None = None
    default_mcp_enabled: bool | None = None
    default_model: str | None = None
    utility_model: str | None = None
    default_system_prompt: str | None = None


class SystemPromptPresetOut(BaseModel):
    id: str
    name: str
    content: str


class SystemPromptPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = ""