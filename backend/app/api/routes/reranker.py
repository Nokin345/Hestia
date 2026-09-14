from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.reranker_config import RerankerConfig, load_reranker_config, save_reranker_config
from app.db import get_db
from app.schemas.reranker import RerankerConfigOut, RerankerConfigUpdate, RerankerTestResult

router = APIRouter(prefix="/api/reranker", tags=["reranker"])


def _out(cfg: RerankerConfig) -> RerankerConfigOut:
    return RerankerConfigOut(url=cfg.url, model=cfg.model, has_api_key=bool(cfg.api_key))


@router.get("/config", response_model=RerankerConfigOut)
async def get_config(db: AsyncSession = Depends(get_db)):
    cfg = await load_reranker_config(db)
    return _out(cfg)


@router.patch("/config", response_model=RerankerConfigOut)
async def update_config(
    body: RerankerConfigUpdate, db: AsyncSession = Depends(get_db)
):
    cfg = await save_reranker_config(
        db,
        url=body.url,
        model=body.model,
        api_key=body.api_key,
    )
    return _out(cfg)


@router.post("/test", response_model=RerankerTestResult)
async def test_reranker(
    body: RerankerConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """Probe the reranker endpoint without persisting."""
    if body.url:
        cfg = RerankerConfig(
            url=(body.url or "").strip(),
            model=(body.model or "").strip(),
            api_key=body.api_key or "",
        )
    else:
        cfg = await load_reranker_config(db)

    if not cfg.use_remote:
        return RerankerTestResult(
            ok=False,
            message="No reranker URL configured — memory ranking uses fused scores only.",
        )

    import httpx

    try:
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                cfg.url,
                headers=headers,
                json={
                    "model": cfg.model,
                    "query": "warmup probe",
                    "documents": ["warmup document one", "warmup document two"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results")
        if not isinstance(results, list) or not results:
            return RerankerTestResult(
                ok=False,
                message=f"Unexpected response shape (missing 'results' array): {str(data)[:200]}",
            )
        return RerankerTestResult(
            ok=True,
            message=f"Reranker OK — returned {len(results)} scored results.",
        )
    except Exception as e:
        return RerankerTestResult(
            ok=False,
            message=f"Reranker test failed: {str(e)[:300]}",
        )
