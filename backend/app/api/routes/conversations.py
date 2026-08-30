import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.core.chat_engine import ChatEngine, parts_from_json, parts_to_json
from app.db import get_db
from app.models import Conversation, Message
from app.schemas.common import MessagePart
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    ConversationPatch,
    MessageOut,
    MessagePartOut,
    MessagePatchRequest,
    MessageRegenerateRequest,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _message_out(row: Message) -> MessageOut:
    def _usage(raw: str | None) -> dict[str, int | float | None] | None:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _memories(raw: str | None) -> list[dict] | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, list) else None

    def _json_dict(raw: str | None) -> dict | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    return MessageOut(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        parts=[
            MessagePartOut(**p.model_dump()) for p in parts_from_json(row.content)
        ],
        model=row.model,
        tool_calls=json.loads(row.tool_calls) if row.tool_calls else [],
        usage=_usage(row.usage),
        memories_used=_memories(row.memories_used),
        kb_sources=_memories(row.kb_sources),
        kb_line_ranges=_json_dict(row.kb_line_ranges),
        error=row.error,
        created_at=row.created_at,
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    stmt = select(Conversation).order_by(
        Conversation.pinned.desc(), Conversation.updated_at.desc()
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate, db: AsyncSession = Depends(get_db)
):
    conv = Conversation(
        title=body.title or "New chat",
        provider=body.provider or "",
        model=body.model or "",
        skill_id=body.skill_id,
        pinned=bool(body.pinned),
        kb_enabled=bool(body.kb_enabled),
        memory_enabled=(
            body.memory_enabled if body.memory_enabled is not None else False
        ),
        reasoning_enabled=(
            body.reasoning_enabled if body.reasoning_enabled is not None else True
        ),
        search_enabled=bool(body.search_enabled),
        code_enabled=bool(body.code_enabled),
        mcp_tools=body.mcp_tools or [],
        system_prompt=body.system_prompt or "",
        temperature=body.temperature if body.temperature is not None else 0.7,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(
    conversation_id: str, body: ConversationPatch, db: AsyncSession = Depends(get_db)
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(conv, key, value)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    await db.execute(
        Message.__table__.delete().where(Message.conversation_id == conversation_id)
    )
    await db.delete(conv)
    await db.commit()

    # Remove the conversation's attachment folder (/uploads/<convo_id>/) so no
    # files are left behind when the history is deleted.
    upload_dir = Path(get_settings().upload_dir) / conversation_id
    if upload_dir.is_dir():
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    result = await db.execute(stmt)
    return [_message_out(row) for row in result.scalars().all()]


@router.post("/{conversation_id}/messages/partial")
async def save_partial_message(
    conversation_id: str,
    body: list[MessagePart],
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=parts_to_json(body),
        model=conv.model,
        error="interrupted",
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return _message_out(msg)


@router.patch(
    "/{conversation_id}/messages/{message_id}", response_model=MessageOut
)
async def patch_message(
    conversation_id: str,
    message_id: str,
    body: MessagePatchRequest,
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not found")
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    new_parts: list[MessagePart] = []
    replaced = False
    for p in parts_from_json(msg.content):
        if p.type == "text":
            if not replaced:
                new_parts.append(MessagePart(type="text", text=content))
                replaced = True
        else:
            new_parts.append(p)
    if not replaced:
        new_parts.append(MessagePart(type="text", text=content))
    msg.content = parts_to_json(new_parts)

    conv = await db.get(Conversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(msg)
    return _message_out(msg)


@router.delete(
    "/{conversation_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message(
    conversation_id: str, message_id: str, db: AsyncSession = Depends(get_db)
):
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.delete(msg)
    conv = await db.get(Conversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(UTC)
    await db.commit()


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_after(
    conversation_id: str,
    message_id: str,
    body: MessageRegenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = await db.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        latest_user = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                )
                .order_by(Message.created_at, Message.id)
            )
        ).scalars().all()
        if not latest_user:
            raise HTTPException(status_code=404, detail="Message not found")
        msg = latest_user[-1]
    if msg.role != "user":
        raise HTTPException(
            status_code=400, detail="Can only regenerate after a user message"
        )
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    user_parts = list(body.parts)
    if body.content and not any(p.text == body.content for p in user_parts):
        user_parts.insert(0, MessagePart(type="text", text=body.content))
    msg.content = parts_to_json(user_parts)

    ordered = (
        await db.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    ).scalars().all()
    try:
        idx = ordered.index(msg.id)
    except ValueError:
        idx = len(ordered) - 1
    after = ordered[idx + 1 :]
    if after:
        await db.execute(Message.__table__.delete().where(Message.id.in_(after)))
    await db.commit()

    if not conv.provider or not conv.model:
        return EventSourceResponse(
            iter(
                [
                    {
                        "event": "error",
                        "data": json.dumps(
                            {"message": "No model was recorded for this conversation."}
                        ),
                    }
                ]
            )
        )

    engine = ChatEngine(db)
    return EventSourceResponse(
        engine.stream_chat(
            conversation_id,
            conv.provider,
            conv.model,
            [MessagePart(type="text", text=content)],
            save_user=False,
            reasoning=body.reasoning if body.reasoning is not None else conv.reasoning_enabled,
            search=body.search if body.search is not None else conv.search_enabled,
            code=body.code if body.code is not None else conv.code_enabled,
            mcp_tools=(
                body.mcp_tools if body.mcp_tools is not None else conv.mcp_tools
            ),
            kb_enabled=body.kb if body.kb is not None else conv.kb_enabled,
            memory_enabled=body.memory if body.memory is not None else conv.memory_enabled,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
        )
    )
