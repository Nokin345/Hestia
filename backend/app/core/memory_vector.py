"""ChromaDB-backed vector store for memory entries.

Stores pre-computed embeddings only (SQLite is the source of truth). Best
effort: if ChromaDB or an embedding backend is unavailable the store reports
not healthy and retrieval degrades to keyword-only.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding_config import load_embedding_config
from app.core.embedding_lanes import build_embedding_lane

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hestia_memories"


class MemoryVectorStore:
    """Vector index over memories for semantic retrieval."""

    def __init__(self, lane):
        self._lane = lane

    @property
    def healthy(self) -> bool:
        return self._lane is not None and self._lane.healthy

    def count(self) -> int:
        if not self.healthy:
            return 0
        return self._lane.count()

    def add(self, memory_id: str, text: str) -> None:
        if not self.healthy:
            return
        try:
            existing = self._lane.collection.get(ids=[memory_id])
            if existing["ids"]:
                return
            self._lane.collection.add(
                ids=[memory_id],
                embeddings=self._lane.encode([text]),
                documents=[text],
            )
        except Exception as e:
            logger.warning("memory vector add failed for %s: %s", memory_id, e)

    def remove(self, memory_id: str) -> None:
        if not self.healthy:
            return
        try:
            self._lane.collection.delete(ids=[memory_id])
        except Exception as e:
            logger.warning("memory vector remove failed for %s: %s", memory_id, e)

    def update(self, memory_id: str, text: str) -> None:
        if not self.healthy:
            return
        try:
            self._lane.collection.upsert(
                ids=[memory_id],
                embeddings=self._lane.encode([text]),
                documents=[text],
            )
        except Exception as e:
            logger.warning("memory vector update failed for %s: %s", memory_id, e)

    def find_similar(self, text: str, threshold: float = 0.90) -> str | None:
        """Return the id of the most semantically similar memory, if above threshold."""
        if not self.healthy or self.count() == 0:
            return None
        try:
            results = self._lane.collection.query(
                query_embeddings=self._lane.encode([text]),
                n_results=1,
                include=["distances"],
            )
            if results["ids"][0]:
                distance = results["distances"][0][0]
                if 1.0 - distance >= threshold:
                    return results["ids"][0][0]
        except Exception as e:
            logger.warning("memory vector similarity search failed: %s", e)
        return None

    def search(self, query: str, k: int = 8) -> list[tuple[str, float]]:
        """Return (memory_id, similarity) pairs by semantic relevance."""
        if not self.healthy or self.count() == 0:
            return []
        try:
            results = self._lane.collection.query(
                query_embeddings=self._lane.encode([query]),
                n_results=min(k, self.count()),
                include=["distances"],
            )
            ids = results["ids"][0]
            sims = [max(0.0, 1.0 - d) for d in results["distances"][0]]
            return list(zip(ids, sims))
        except Exception as e:
            logger.warning("memory vector search failed: %s", e)
            return []

    def get_stats(self) -> dict:
        if self._lane is None:
            return {"healthy": False, "count": 0, "lane": None, "model": None, "dimension": None}
        return {
            "healthy": self.healthy,
            "count": self.count(),
            "lane": self._lane.name,
            "model": self._lane.model,
            "dimension": self._lane.dimension,
        }


_lane = None
_lock = asyncio.Lock()


def _config_key(cfg) -> str:
    return "|".join([cfg.url or "", cfg.model or "", cfg.api_key or ""])


async def get_memory_store(db: AsyncSession) -> MemoryVectorStore:
    """Get (or build) the singleton vector store, reacting to settings changes."""
    global _lane
    async with _lock:
        cfg = await load_embedding_config(db)
        key = _config_key(cfg)
        if _lane is not None and getattr(_lane, "_key", None) == key:
            return MemoryVectorStore(_lane)

        try:
            settings = get_settings()
            lane = build_embedding_lane(COLLECTION_NAME, cfg, settings.data_dir)
            setattr(lane, "_key", key)
            _lane = lane
        except Exception as e:
            logger.warning("Memory vector store init failed: %s", e)
            _lane = None
        store = MemoryVectorStore(_lane)
        if store.healthy:
            await _backfill(db, store)
        return store


async def _backfill(db: AsyncSession, store: MemoryVectorStore) -> None:
    """Index any memories missing from the vector store (best effort)."""
    indexed = set()
    try:
        results = store._lane.collection.get(include=[])
        indexed = set(results["ids"])
    except Exception:
        pass
    try:
        from app.core.memory import list_memories

        missing = [m for m in await list_memories(db) if m.id not in indexed]
        if missing:
            for m in missing:
                store.add(m.id, m.text)
            logger.info("Backfilled %s memories into vector store", len(missing))
    except Exception as e:
        logger.warning("Memory vector backfill failed: %s", e)


def reset_memory_store() -> None:
    global _lane
    _lane = None