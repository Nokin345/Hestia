from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting
from app.schemas.defaults import DefaultsOut

_CONFIG_KEYS = (
    "default_kb_enabled",
    "default_memory_enabled",
    "default_search_enabled",
    "default_code_enabled",
    "default_mcp_enabled",
    "default_model",
    "utility_model",
    "default_system_prompt",
)


async def load_defaults_config(db: AsyncSession) -> DefaultsOut:
    res = await db.execute(select(Setting).where(Setting.key.in_(_CONFIG_KEYS)))
    rows = {s.key: s.value for s in res.scalars()}
    return DefaultsOut(
        default_kb_enabled=(rows.get("default_kb_enabled") or "false").lower() == "true",
        default_memory_enabled=(rows.get("default_memory_enabled") or "false").lower() == "true",
        default_search_enabled=(rows.get("default_search_enabled") or "false").lower() == "true",
        default_code_enabled=(rows.get("default_code_enabled") or "false").lower() == "true",
        default_mcp_enabled=(rows.get("default_mcp_enabled") or "false").lower() == "true",
        default_model=rows.get("default_model") or "",
        utility_model=rows.get("utility_model") or "",
        default_system_prompt=rows.get("default_system_prompt") or "",
    )