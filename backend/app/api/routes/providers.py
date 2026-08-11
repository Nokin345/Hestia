import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ProviderConfig
from app.providers.registry import (
    build_provider,
    deserialize_allowed,
    get_provider_config,
    list_provider_configs,
    mask_key,
    serialize_allowed,
    slugify,
)
from app.schemas.provider import (
    PROVIDER_TYPE_IDS,
    KEYLESS_TYPES,
    ModelEntry,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderModel,
    ProviderOut,
    ProviderTestRequest,
    ProviderTestResponse,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _to_out(cfg: ProviderConfig) -> ProviderOut:
    return ProviderOut(
        id=cfg.id,
        name=cfg.name,
        type=cfg.type,
        base_url=cfg.base_url,
        api_key_masked=mask_key(cfg.api_key),
        enabled=cfg.enabled,
        allowed_models=deserialize_allowed(cfg.allowed_models),
    )


def _to_model_entry(m: ProviderModel, cfg: ProviderConfig) -> ModelEntry:
    return ModelEntry(
        id=m.id,
        provider_id=cfg.id,
        provider_name=cfg.name,
        vision=False,
        context_window=m.context_window,
    )


@router.get("", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    configs = await list_provider_configs(db)
    return [_to_out(cfg) for cfg in configs]


@router.get("/models", response_model=list[ModelEntry])
async def list_allowed_models(db: AsyncSession = Depends(get_db)):
    """All models allowed in chat, across enabled, reachable providers."""
    configs = await list_provider_configs(db, only_enabled=True)

    async def for_config(cfg: ProviderConfig) -> list[ModelEntry]:
        if not cfg.api_key and cfg.type not in KEYLESS_TYPES:
            return []
        allowed = deserialize_allowed(cfg.allowed_models)
        try:
            live = await build_provider(cfg).list_models()
        except Exception:
            return []
        live_ids = {m.id for m in live}
        if allowed is not None:
            return [_to_model_entry(m, cfg) for m in allowed if m.id in live_ids]
        return [_to_model_entry(m, cfg) for m in live]

    results = await asyncio.gather(*(for_config(cfg) for cfg in configs))
    return [m for sub in results for m in sub]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderConfigCreate, db: AsyncSession = Depends(get_db)
):
    if body.type not in PROVIDER_TYPE_IDS:
        raise HTTPException(
            status_code=422, detail=f"Unknown provider type: {body.type}"
        )
    if body.type == "openai_compat" and not (body.base_url or "").strip():
        raise HTTPException(
            status_code=422, detail="Base URL is required for custom endpoints"
        )
    pid = body.id or slugify(body.name)
    if await db.get(ProviderConfig, pid) is not None:
        raise HTTPException(status_code=409, detail=f"Provider '{pid}' already exists")
    cfg = ProviderConfig(
        id=pid,
        name=body.name,
        type=body.type,
        api_key=body.api_key,
        base_url=(body.base_url or "").strip() or None,
        enabled=body.enabled,
        allowed_models=serialize_allowed(body.allowed_models),
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str, body: ProviderConfigUpdate, db: AsyncSession = Depends(get_db)
):
    cfg = await get_provider_config(db, provider_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    data = body.model_dump(exclude_unset=True)
    if "api_key" in data and not data["api_key"]:
        data.pop("api_key")
    for key, value in data.items():
        if key == "base_url":
            value = (value or "").strip() or None
        elif key == "allowed_models":
            value = serialize_allowed(value)
        setattr(cfg, key, value)
    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await get_provider_config(db, provider_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(cfg)
    await db.commit()


@router.get("/{provider_id}/models", response_model=list[ProviderModel])
async def list_models(provider_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await get_provider_config(db, provider_id)
    if cfg is None or not cfg.enabled:
        return []
    if not cfg.api_key and cfg.type not in KEYLESS_TYPES:
        return []
    cached = deserialize_allowed(cfg.allowed_models) or []
    try:
        models = await build_provider(cfg).list_models()
    except Exception:
        if not cached:
            return []
        return [
            m.model_copy(
                update={"available": False, "reason": "unreachable", "vision": False}
            )
            for m in cached
        ]
    live_ids = {m.id for m in models}
    out = [
        ProviderModel(
            id=m.id,
            name=m.name,
            context_window=m.context_window,
            vision=False,
            max_output=m.max_output,
        )
        for m in models
    ]
    for m in cached:
        if m.id not in live_ids:
            out.append(
                m.model_copy(
                    update={"available": False, "reason": "removed", "vision": False}
                )
            )
    return out


@router.get("/{provider_id}/reasoning")
async def provider_reasoning_support(
    provider_id: str, model: str, db: AsyncSession = Depends(get_db)
):
    """Detect whether a model accepts reasoning toggling. reasoning: null = unknown."""
    cfg = await get_provider_config(db, provider_id)
    if cfg is None or not cfg.enabled:
        return {"reasoning": None}
    provider = build_provider(cfg)
    try:
        supported = await provider.supports_reasoning(model)
    except Exception:
        supported = None
    return {"reasoning": supported}


@router.post("/test", response_model=ProviderTestResponse)
async def test_provider(body: ProviderTestRequest):
    if body.type not in PROVIDER_TYPE_IDS:
        return ProviderTestResponse(
            ok=False, message=f"Unknown provider type: {body.type}"
        )
    if body.type == "openai_compat" and not (body.base_url or "").strip():
        return ProviderTestResponse(
            ok=False, message="Base URL is required for custom endpoints"
        )
    if not body.api_key and body.type == "openrouter":
        return ProviderTestResponse(ok=False, message="API key is required")

    cfg = ProviderConfig(
        id="_test",
        name="test",
        type=body.type,
        api_key=body.api_key,
        base_url=(body.base_url or "").strip() or None,
    )
    provider = build_provider(cfg)
    try:
        models = await provider.list_models()
    except Exception as exc:
        return ProviderTestResponse(ok=False, message=str(exc)[:300])
    return ProviderTestResponse(
        ok=True,
        message=f"Connected — {len(models)} models available",
        models=[
            ProviderModel(
                id=m.id,
                name=m.name,
                context_window=m.context_window,
                vision=False,
                max_output=m.max_output,
            )
            for m in models
        ],
    )
