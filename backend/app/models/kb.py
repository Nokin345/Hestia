import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime


def now() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return uuid.uuid4().hex


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100), default="")
    path: Mapped[str] = mapped_column(String(255))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    text_preview: Mapped[str] = mapped_column(Text, default="")
    extraction_method: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)