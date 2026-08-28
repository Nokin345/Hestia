import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime


def now() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return uuid.uuid4().hex


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    skill_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    kb_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    search_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    code_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mcp_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=now, onupdate=now
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_results: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    memories_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_line_ranges: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=now, onupdate=now
    )


class SystemPromptPreset(Base):
    __tablename__ = "system_prompt_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=now, onupdate=now
    )
