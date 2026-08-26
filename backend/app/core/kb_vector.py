"""ChromaDB-backed vector store for the global knowledge base.

Chunks of uploaded KB documents are embedded and stored in a dedicated
Chroma collection (``hestia_kb``). Best effort: if ChromaDB or an embedding
backend is unavailable the store reports not healthy and KB search degrades
to a no-op (empty results).
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding_lanes import build_embedding_lane

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hestia_kb"
RAG_SIMILARITY_THRESHOLD = 0.35


class KbVectorStore:
    """Vector index over KB document chunks."""

    def __init__(self, lane):
        self._lane = lane

    @property
    def healthy(self) -> bool:
        return self._lane is not None and self._lane.healthy

    def count(self) -> int:
        if not self.healthy:
            return 0
        return self._lane.count()

    def add_document_chunks(self, doc_id: str, chunks: list[str], filename: str) -> None:
        """Embed and index all chunks of a document (replaces any existing)."""
        if not self.healthy or not chunks:
            return
        try:
            self.remove_document(doc_id)
            ids = [f"{doc_id}::{i}" for i in range(len(chunks))]
            self._lane.collection.add(
                ids=ids,
                embeddings=self._lane.encode(chunks),
                documents=chunks,
                metadatas=[
                    {"doc_id": doc_id, "filename": filename, "chunk": i}
                    for i in range(len(chunks))
                ],
            )
        except Exception as e:
            logger.warning("KB vector add failed for %s: %s", doc_id, e)

    def remove_document(self, doc_id: str) -> None:
        if not self.healthy:
            return
        try:
            where = {"doc_id": doc_id}
            existing = self._lane.collection.get(where=where, include=[])
            if existing["ids"]:
                self._lane.collection.delete(ids=existing["ids"])
        except Exception as e:
            logger.warning("KB vector remove failed for %s: %s", doc_id, e)

    def get_document_text(self, doc_id: str) -> str:
        """Reconstruct the extracted text of a document from its chunks."""
        if not self.healthy:
            return ""
        try:
            res = self._lane.collection.get(
                where={"doc_id": doc_id},
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning("KB text fetch failed for %s: %s", doc_id, e)
            return ""
        chunks = [
            (int(meta.get("chunk", 0)), doc or "")
            for doc, meta in zip(res["documents"], res["metadatas"])
        ]
        chunks.sort(key=lambda x: x[0])
        parts: list[str] = []
        for _, chunk in chunks:
            if not chunk:
                continue
            if not parts:
                parts.append(chunk)
                continue
            prev = parts[-1]
            # Strip the sliding-window overlap shared with the previous chunk
            for i in range(min(len(prev), len(chunk), 500), 0, -1):
                if chunk.startswith(prev[-i:]):
                    parts.append(chunk[i:])
                    break
            else:
                parts.append(chunk)
        return "".join(parts)

    def search(
        self,
        query: str,
        k: int = 5,
        threshold: float = RAG_SIMILARITY_THRESHOLD,
        doc_ids: list[str] | None = None,
    ) -> list[dict]:
        """Return relevant chunks above the similarity threshold.

        Each result carries ``document`` (chunk text), ``metadata`` and
        ``similarity`` (0..1, cosine distance inverted). If ``doc_ids`` is
        given, only chunks belonging to those documents are considered.
        """
        if not self.healthy or self.count() == 0:
            return []
        try:
            n = self.count()
            kwargs: dict = {}
            if doc_ids:
                kwargs["where"] = {"doc_id": {"$in": doc_ids}}
            results = self._lane.collection.query(
                query_embeddings=self._lane.encode([query]),
                n_results=min(k * 3, n),
                include=["documents", "metadatas", "distances"],
                **kwargs,
            )
        except Exception as e:
            logger.warning("KB vector search failed: %s", e)
            return []

        docs = results["documents"][0] or []
        metas = results["metadatas"][0] or []
        dists = results["distances"][0] or []
        out: list[dict] = []
        for doc, meta, dist in zip(docs, metas, dists):
            sim = max(0.0, 1.0 - dist)
            if sim < threshold:
                continue
            out.append(
                {
                    "document": doc,
                    "metadata": {
                        "doc_id": meta.get("doc_id", ""),
                        "filename": meta.get("filename", "unknown"),
                        "chunk": meta.get("chunk", 0),
                    },
                    "similarity": round(sim, 3),
                }
            )
            if len(out) >= k:
                break
        return out

    def get_stats(self) -> dict:
        if self._lane is None:
            return {"healthy": False, "count": 0, "lane": None, "model": "intfloat/multilingual-e5-small", "dimension": 384}
        return {
            "healthy": self.healthy,
            "count": self.count(),
            "lane": self._lane.name,
            "model": "intfloat/multilingual-e5-small",
            "dimension": 384,
        }


_lane = None
_lock = asyncio.Lock()


async def get_kb_store(db: AsyncSession) -> KbVectorStore:
    """Get or build the singleton KB store."""
    global _lane
    async with _lock:
        if _lane is not None:
            return KbVectorStore(_lane)
        try:
            settings = get_settings()
            lane = build_embedding_lane(COLLECTION_NAME, settings.data_dir)
            _lane = lane
        except Exception as e:
            logger.warning("KB vector store init failed: %s", e)
            _lane = None
        return KbVectorStore(_lane)


def reset_kb_store() -> None:
    global _lane
    _lane = None
