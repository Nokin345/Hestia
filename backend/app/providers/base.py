from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.schemas.common import ChatMessage, ToolCall


@dataclass
class ProviderModelInfo:
    id: str
    name: str
    context_window: int | None = None
    vision: bool = False
    max_output: int | None = None


@dataclass
class ProviderStreamEvent:
    kind: str  # "text" | "reasoning" | "tool_call" | "done" | "error"
    content: str = ""
    tool_call: ToolCall | None = None
    error: str = ""
    usage: dict[str, Any] | None = None


@dataclass
class ProviderCallParams:
    model: str
    system: str
    messages: list[ChatMessage]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 16384
    temperature: float = 0.7
    reasoning: bool | None = None


class Provider(ABC):
    id: str = "base"
    name: str = "Base"
    supports_tools: bool = True
    supports_vision: bool = True

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        *,
        id: str | None = None,
        name: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        if id is not None:
            self.id = id
        if name is not None:
            self.name = name

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def requires_api_key(self) -> bool:
        return True

    @abstractmethod
    async def list_models(self) -> list[ProviderModelInfo]: ...

    @abstractmethod
    def stream(
        self, params: ProviderCallParams
    ) -> AsyncIterator[ProviderStreamEvent]: ...

    async def supports_reasoning(self, model: str) -> bool | None:
        """Whether the model accepts reasoning toggling. None = unknown."""
        return None
