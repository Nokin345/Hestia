import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TZDateTime


def now() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return uuid.uuid4().hex


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uuid_str)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default="fact")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    uses: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=now, onupdate=now
    )
