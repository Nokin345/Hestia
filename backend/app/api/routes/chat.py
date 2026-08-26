import json

from datetime import UTC, datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.chat_engine import ChatEngine
from app.db import get_db
from app.models import Conversation
from app.providers.registry import get_provider_config, list_provider_configs
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _error_event(message: str) -> EventSourceResponse:
    return EventSourceResponse(
        iter([{"event": "error", "data": json.dumps({"message": message})}])
    )


@router.post("")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not body.parts and not body.content:
        return _error_event("Empty message")

    parts = list(body.parts)
    if body.content and not any(p.text == body.content for p in parts):
        from app.schemas.common import MessagePart

        parts.insert(0, MessagePart(type="text", text=body.content))

    provider_id = body.provider
    if not provider_id:
        configs = await list_provider_configs(db, only_enabled=True)
        if configs:
            provider_id = configs[0].id
    if not provider_id:
        return _error_event("No providers configured. Add one in Settings first.")

    cfg = await get_provider_config(db, provider_id)
    if cfg is None:
        return _error_event(f"Unknown provider: {provider_id}")
    if not cfg.enabled:
        return _error_event(
            f"Provider '{provider_id}' is disabled. Enable it in Settings."
        )

    model = body.model
    if not model:
        return _error_event("No model selected. Choose a model in the chat composer.")

    if body.conversation_id:
        conversation_id = body.conversation_id
        conv = await db.get(Conversation, conversation_id)
        if conv is None:
            return _error_event("Conversation not found")
        conv.provider = provider_id
        conv.model = model
        if body.skill_id is not None:
            conv.skill_id = body.skill_id
        if body.kb is not None:
            conv.kb_enabled = body.kb
        if body.memory is not None:
            conv.memory_enabled = body.memory
        if body.reasoning is not None:
            conv.reasoning_enabled = body.reasoning
        if body.search is not None:
            conv.search_enabled = body.search
        if body.code is not None:
            conv.code_enabled = body.code
        if body.mcp_tools is not None:
            conv.mcp_tools = body.mcp_tools
        if body.system_prompt is not None:
            conv.system_prompt = body.system_prompt
        if body.temperature is not None:
            conv.temperature = body.temperature
        conv.updated_at = datetime.now(UTC)
        await db.commit()
    else:
        conv = Conversation(
            title="New chat",
            provider=provider_id,
            model=model,
            skill_id=body.skill_id,
            kb_enabled=bool(body.kb),
            memory_enabled=body.memory if body.memory is not None else False,
            reasoning_enabled=(
                body.reasoning if body.reasoning is not None else True
            ),
            search_enabled=bool(body.search),
            code_enabled=bool(body.code),
            mcp_tools=body.mcp_tools or [],
            system_prompt=body.system_prompt or "",
            temperature=body.temperature if body.temperature is not None else 0.7,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conversation_id = conv.id

    kwargs = {
        "reasoning": (
            body.reasoning if body.reasoning is not None else conv.reasoning_enabled
        ),
        "search": body.search if body.search is not None else conv.search_enabled,
        "code": body.code if body.code is not None else conv.code_enabled,
        "mcp_tools": (
            body.mcp_tools if body.mcp_tools is not None else conv.mcp_tools
        ),
        "kb_enabled": body.kb if body.kb is not None else conv.kb_enabled,
        "memory_enabled": body.memory
        if body.memory is not None
        else conv.memory_enabled,
    }

    engine = ChatEngine(db)
    return EventSourceResponse(
        engine.stream_chat(
            conversation_id,
            provider_id,
            model,
            parts,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            **kwargs,
        )
    )
