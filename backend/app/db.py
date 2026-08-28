import datetime as dt
from collections.abc import AsyncGenerator

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class TZDateTime(TypeDecorator):
    """DateTime that always round-trips as timezone-aware UTC from SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value


engine = create_async_engine(get_settings().database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _migrate_sqlite(sync_conn) -> None:
    """Lightweight additive migrations for existing SQLite databases."""
    additions = {
        "provider_configs": {"allowed_models": "TEXT"},
        "messages": {
            "usage": "TEXT",
            "model": "VARCHAR(100)",
            "memories_used": "TEXT",
        },
        "memories": {
            "last_recalled_at": "DATETIME",
        },
        "kb_documents": {
            "enabled": "BOOLEAN DEFAULT 1",
        },
        "conversations": {
            "pinned": "BOOLEAN DEFAULT 0",
            "kb_enabled": "BOOLEAN DEFAULT 0",
            "memory_enabled": "BOOLEAN DEFAULT 1",
            "reasoning_enabled": "BOOLEAN DEFAULT 1",
            "search_enabled": "BOOLEAN DEFAULT 0",
            "code_enabled": "BOOLEAN DEFAULT 0",
            "mcp_tools": "TEXT DEFAULT '[]'",
            "system_prompt": "TEXT DEFAULT ''",
            "temperature": "FLOAT DEFAULT 0.7",
        },
        "mcp_servers": {
            "disabled_tools_json": "TEXT DEFAULT '[]'",
        },
    }
    for table, columns in additions.items():
        existing = {
            row[1]
            for row in sync_conn.exec_driver_sql(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
        for column, ddl in columns.items():
            if column not in existing:
                sync_conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                )
    # mcp_servers is now global-only (managed on the MCP settings page); the
    # per-conversation server selection column is removed.
    _drop_sqlite_columns(sync_conn, "conversations", ["mcp_enabled", "mcp_servers"])


def _drop_sqlite_columns(sync_conn, table: str, columns: list[str]) -> None:
    """Drop columns if present (requires SQLite >= 3.35)."""
    existing = {
        row[1]
        for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    }
    for column in columns:
        if column in existing:
            sync_conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")


async def init_db() -> None:
    from app import models  # noqa: F401

    get_settings().ensure_dirs()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite)
    await _cleanup_empty_conversations()
    await _seed_default_preset()


DEFAULT_PROMPT_PRESET = (
    "You are a helpful assistant. Be clear, concise, and honest. "
    "If you don't know something, say so."
)


async def _seed_default_preset() -> None:
    from sqlalchemy import select

    from app.models import SystemPromptPreset

    async with SessionLocal() as session:
        res = await session.execute(
            select(SystemPromptPreset).where(SystemPromptPreset.name == "default")
        )
        if res.scalar_one_or_none() is None:
            session.add(
                SystemPromptPreset(name="default", content=DEFAULT_PROMPT_PRESET)
            )
            await session.commit()


async def _cleanup_empty_conversations() -> None:
    from sqlalchemy import select

    from app.models import Conversation, Message

    async with SessionLocal() as session:
        with_messages = select(Message.conversation_id).distinct()
        stmt = Conversation.__table__.delete().where(
            Conversation.id.not_in(with_messages)
        )
        await session.execute(stmt)
        await session.commit()
