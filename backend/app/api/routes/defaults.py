from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.defaults_config import load_defaults_config
from app.db import get_db
from app.models import Setting, SystemPromptPreset
from app.schemas.defaults import (
    DefaultsOut,
    DefaultsUpdate,
    SystemPromptPresetCreate,
    SystemPromptPresetOut,
)

router = APIRouter(prefix="/api/defaults", tags=["defaults"])


@router.get("", response_model=DefaultsOut)
async def get_defaults(db: AsyncSession = Depends(get_db)):
    return await load_defaults_config(db)


@router.patch("", response_model=DefaultsOut)
async def update_defaults(
    body: DefaultsUpdate, db: AsyncSession = Depends(get_db)
):
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setting = await db.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value="")
            db.add(setting)
        setting.value = str(value).lower() if isinstance(value, bool) else str(value)
    await db.commit()
    return await load_defaults_config(db)


@router.get("/presets", response_model=list[SystemPromptPresetOut])
async def list_presets(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(SystemPromptPreset).order_by(SystemPromptPreset.created_at.desc())
    )
    return list(res.scalars().all())


@router.post("/presets", response_model=SystemPromptPresetOut, status_code=201)
async def create_preset(
    body: SystemPromptPresetCreate, db: AsyncSession = Depends(get_db)
):
    preset = SystemPromptPreset(name=body.name, content=body.content)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, db: AsyncSession = Depends(get_db)):
    preset = await db.get(SystemPromptPreset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    await db.delete(preset)
    await db.commit()
    return Response(status_code=204)