from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Setting
from app.schemas.search import SearchConfigOut

_CONFIG_KEYS = (
    "searxng_url",
    "max_results",
    "fallback",
    "fetch_urls",
    "fetch_limit",
    "max_chars_per_url",
)


def _bounded_int(value: str | None, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


async def load_search_config(db: AsyncSession) -> SearchConfigOut:
    res = await db.execute(select(Setting).where(Setting.key.in_(_CONFIG_KEYS)))
    rows = {s.key: s.value for s in res.scalars()}
    # Env-provided URLs are auto-provisioned: if the admin never saved an
    # explicit value, the .env/compose setting becomes the effective default.
    settings = get_settings()
    searxng_url = (rows.get("searxng_url") or "").strip() or settings.searxng_url.strip()
    return SearchConfigOut(
        searxng_url=searxng_url,
        max_results=_bounded_int(rows.get("max_results"), 5, 1, 50),
        fallback=(rows.get("fallback") or "true").lower() == "true",
        fetch_urls=(rows.get("fetch_urls") or "true").lower() == "true",
        fetch_limit=_bounded_int(rows.get("fetch_limit"), 1, 1, 10),
        max_chars_per_url=_bounded_int(rows.get("max_chars_per_url"), 4000, 500, 50000),
    )
