from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding_config import (
    EmbeddingConfig,
    load_embedding_config,
    save_embedding_config,
)
from app.core.embeddings import build_embedding_client
from app.core.memory_vector import get_memory_store, reset_memory_store
from app.db import get_db
from app.schemas.embedding import (
    EmbeddingConfigOut,
    EmbeddingConfigUpdate,
    EmbeddingStatsOut,
    EmbeddingTestResult,
)

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


@router.get("/config", response_model=EmbeddingConfigOut)
async def get_config(db: AsyncSession = Depends(get_db)):
    cfg = await load_embedding_config(db)
    return EmbeddingConfigOut(
        url=cfg.url,
        model=cfg.model,
        has_api_key=bool(cfg.api_key),
    )


@router.patch("/config", response_model=EmbeddingConfigOut)
async def update_config(
    body: EmbeddingConfigUpdate, db: AsyncSession = Depends(get_db)
):
    cfg = await save_embedding_config(
        db,
        url=body.url,
        model=body.model,
        api_key=body.api_key,
    )
    # Any change to the settings invalidates the vector store so it is rebuilt
    # with the next backend / collection / next use.
    reset_memory_store()
    return EmbeddingConfigOut(
        url=cfg.url,
        model=cfg.model,
        has_api_key=bool(cfg.api_key),
    )


@router.get("/stats", response_model=EmbeddingStatsOut)
async def get_stats(db: AsyncSession = Depends(get_db)):
    store = await get_memory_store(db)
    stats = store.get_stats()
    return EmbeddingStatsOut(**stats)


@router.post("/test", response_model=EmbeddingTestResult)
async def test_embedding(
    body: EmbeddingConfigUpdate, db: AsyncSession = Depends(get_db)
):
    """Probe the embedding backend without persisting.

    Reports whether a configured remote endpoint is reachable or whether the
    service would fall back to the local CPU model (mirroring the SearXNG test).
    """
    cfg = EmbeddingConfig(
        url=(body.url if body.url is not None else "").strip(),
        model=(body.model if body.model is not None else "").strip(),
        api_key=body.api_key or "",
    )

    if cfg.use_remote:
        # Probe the remote endpoint directly so we can tell reachable from fallback.
        from app.core.embeddings import RemoteEmbeddingClient

        try:
            client = RemoteEmbeddingClient(cfg.url, cfg.model, cfg.api_key)
            dim = client.get_dimension()
            return EmbeddingTestResult(
                ok=True,
                backend="remote",
                remote_reachable=True,
                fallback=False,
                dimension=dim,
                model=getattr(client, "model", ""),
                message="Remote embedding endpoint is reachable",
            )
        except Exception as e:
            remote_error = str(e)
            # Remote unreachable — probe the local CPU fallback.
            try:
                client, backend = build_embedding_client(
                    EmbeddingConfig(),
                    cache_dir=f"{get_settings().data_dir}/fastembed",
                )
                if client is not None:
                    dim = client.get_dimension()
                    model_name = getattr(client, "model", "")
                    return EmbeddingTestResult(
                        ok=True,
                        backend="local",
                        remote_reachable=False,
                        fallback=True,
                        dimension=dim,
                        model=model_name,
                        message=(
                            "Remote embedding endpoint unreachable — falling back to "
                            f"local fastembed (CPU) model {model_name} (dim {dim}). "
                            f"Remote error: {remote_error[:200]}"
                        ),
                    )
            except Exception as exc:
                remote_error = f"{remote_error}; local: {exc}"
            return EmbeddingTestResult(
                ok=False,
                backend="none",
                remote_reachable=False,
                fallback=False,
                message=f"No embedding backend available. {remote_error}".strip(),
            )

    # No remote configured — test the local CPU model directly.
    try:
        client, backend = build_embedding_client(
            cfg, cache_dir=f"{get_settings().data_dir}/fastembed"
        )
    except Exception as e:
        return EmbeddingTestResult(
            ok=False,
            backend="none",
            message=f"Embedding test failed: {e}",
        )
    if client is None:
        return EmbeddingTestResult(
            ok=False,
            backend="none",
            message="No embedding backend available. Configure a remote endpoint or install fastembed.",
        )
    try:
        dim = client.get_dimension()
        model_name = getattr(client, "model", "")
        return EmbeddingTestResult(
            ok=True,
            backend="local",
            remote_reachable=None,
            fallback=False,
            dimension=dim,
            model=model_name,
            message=f"Local fastembed (CPU) is working — model {model_name}, dim {dim}.",
        )
    except Exception as exc:
        return EmbeddingTestResult(
            ok=False,
            backend="none",
            message=f"Embedding test failed: {exc}",
        )