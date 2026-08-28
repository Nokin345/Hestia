import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime


def now() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return uuid.uuid4().hex


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(100))
    transport: Mapped[str] = mapped_column(String(20), default="http")
    url: Mapped[str] = mapped_column(String(500))
    auth_token: Mapped[str] = mapped_column(Text, default="")
    headers_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=now, onupdate=now
    )
