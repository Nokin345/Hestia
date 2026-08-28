from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.search import search_web
from app.core.search_config import load_search_config
from app.db import get_db
from app.models import Setting
from app.schemas.search import (
    SearchConfigOut,
    SearchConfigUpdate,
    SearchTestRequest,
    SearchTestResult,
)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/config", response_model=SearchConfigOut)
async def get_config(db: AsyncSession = Depends(get_db)):
    return await load_search_config(db)


@router.patch("/config", response_model=SearchConfigOut)
async def update_config(
    body: SearchConfigUpdate, db: AsyncSession = Depends(get_db)
):
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setting = await db.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value="")
            db.add(setting)
        setting.value = str(value)
    await db.commit()
    return await load_search_config(db)


@router.post("/test", response_model=SearchTestResult)
async def test_search(body: SearchTestRequest):
    result = await search_web(
        "opencode search test", body.searxng_url, body.max_results, body.fallback
    )
    engine = result["engine"]
    count = len(result["results"])
    if engine == "searxng":
        return SearchTestResult(
            ok=True,
            engine="searxng",
            results=count,
            message=f"SearXNG is working — {count} result{'' if count == 1 else 's'}.",
        )
    if engine == "duckduckgo":
        return SearchTestResult(
            ok=True,
            engine="duckduckgo",
            results=count,
            message=(
                "SearXNG unavailable (unreachable or returned no results) — "
                f"using DuckDuckGo fallback ({count} result{'' if count == 1 else 's'})."
            ),
        )
    return SearchTestResult(
        ok=False,
        engine="none",
        results=0,
        message="No search engine available.",
    )
