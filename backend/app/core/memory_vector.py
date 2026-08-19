"""ChromaDB-backed vector store for memory entries.

Stores pre-computed embeddings. Best effort: if ChromaDB is unavailable the
store reports not healthy and retrieval degrades gracefully.
"""

import asyncio
import logging

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embeddings import get_embedding_engine

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "hestia_memories"
_SEMANTIC_THRESHOLD = 0.1
_KW_THRESHOLD = 0.12
_TOP_K = 10


class MemoryVectorStore:
    """Vector index over memories for semantic similarity filtering."""

    def __init__(self, engine, collection):
        self._engine = engine
        self._collection = collection

    @property
    def healthy(self) -> bool:
        return self._collection is not None and self._engine is not None

    def count(self) -> int:
        if not self.healthy:
            return 0
        try:
            return int(self._collection.count())
        except Exception:
            return 0

    def add(self, memory_id: str, text: str) -> None:
        if not self.healthy:
            return
        try:
            existing = self._collection.get(ids=[memory_id])
            if existing["ids"]:
                return
            vecs = self._engine.encode([text])
            self._collection.add(
                ids=[memory_id],
                embeddings=vecs.tolist(),
                documents=[text],
            )
        except Exception as e:
            logger.warning("memory vector add failed for %s: %s", memory_id, e)

    def remove(self, memory_id: str) -> None:
        if not self.healthy:
            return
        try:
            self._collection.delete(ids=[memory_id])
        except Exception as e:
            logger.warning("memory vector remove failed for %s: %s", memory_id, e)

    def update(self, memory_id: str, text: str) -> None:
        if not self.healthy:
            return
        try:
            vecs = self._engine.encode([text])
            self._collection.upsert(
                ids=[memory_id],
                embeddings=vecs.tolist(),
                documents=[text],
            )
        except Exception as e:
            logger.warning("memory vector update failed for %s: %s", memory_id, e)

    def semantic_filter(self, query: str, k: int = _TOP_K) -> list[tuple[str, float]]:
        """Return (memory_id, cosine_similarity) pairs above threshold.

        Cosine similarity via normalized dot product:
            v_q = query_vec / norm(query_vec)
            v_p = passage_vec / norm(passage_vec)
            sim = dot(v_q, v_p)
        """
        if not self.healthy or self.count() == 0:
            return []
        try:
            query_vec = self._engine.encode([query])
            results = self._collection.query(
                query_embeddings=query_vec.tolist(),
                n_results=min(k, self.count()),
                include=["distances", "embeddings"],
            )
            ids = results["ids"][0]
            emb_list = results.get("embeddings", [[]])[0]
            dists = results["distances"][0]

            # ChromaDB cosine distance is 1 - cosine_similarity, so sim = 1 - dist
            sims = [(mid, 1.0 - d) for mid, d in zip(ids, dists) if 1.0 - d >= _SEMANTIC_THRESHOLD]
            return sims
        except Exception as e:
            logger.warning("semantic filter failed: %s", e)
            return []

    def find_similar(self, text: str, threshold: float = 0.85) -> str | None:
        """Return the id of the most semantically similar memory, if above threshold."""
        if not self.healthy or self.count() == 0:
            return None
        try:
            query_vec = self._engine.encode([text])
            results = self._collection.query(
                query_embeddings=query_vec.tolist(),
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

    def get_stats(self) -> dict:
        if not self.healthy:
            return {
                "healthy": False,
                "count": 0,
                "lane": None,
                "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                "dimension": 384,
            }
        return {
            "healthy": True,
            "count": self.count(),
            "lane": self._collection.name if self._collection else None,
            "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "dimension": 384,
        }


_store: MemoryVectorStore | None = None
_lock = asyncio.Lock()


async def get_memory_store(db: AsyncSession) -> MemoryVectorStore:
    """Get or create the singleton memory vector store."""
    global _store
    async with _lock:
        if _store is not None:
            return _store
        try:
            settings = get_settings()
            cache_dir = f"{settings.data_dir}/fastembed"
            engine = get_embedding_engine(cache_dir=cache_dir)
            from app.core.chroma_client import get_chroma_client

            chroma = get_chroma_client(settings.data_dir)
            try:
                collection = chroma.get_collection(_COLLECTION_NAME)
            except Exception:
                logger.info(
                    "Creating memory Chroma collection %s (dim=%d)",
                    _COLLECTION_NAME,
                    engine.get_dimension(),
                )
                collection = chroma.get_or_create_collection(
                    name=_COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            _store = MemoryVectorStore(engine, collection)
        except Exception as e:
            logger.warning("Memory vector store init failed: %s", e)
            _store = MemoryVectorStore(None, None)
        return _store


async def _backfill(db: AsyncSession, store: MemoryVectorStore) -> None:
    """Index any memories missing from the vector store (best effort)."""
    indexed = set()
    try:
        results = store._collection.get(include=[])
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
    global _store
    _store = None
