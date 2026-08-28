"""ChromaDB-backed vector store for the global knowledge base.

Chunks of uploaded KB documents are embedded and stored in a dedicated
Chroma collection (``hestia_kb``). Best effort: if ChromaDB or an embedding
backend is unavailable the store reports not healthy and KB search degrades
to a no-op (empty results).
"""

import asyncio
import logging
import math
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding_lanes import build_embedding_lane

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hestia_kb"
RAG_SIMILARITY_THRESHOLD = 0.2
FUSION_VS_WEIGHT = 0.7
FUSION_KW_WEIGHT = 0.3

_STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need ought dare "
    "i me my mine we us our ours you your yours he him his she her hers "
    "it its they them their theirs this that these those "
    "and but or nor not no so if then else than too very "
    "in on at to for of by with from up out about into over after "
    "what when where which who whom how why all each every some any "
    "just really actually like well also still already even "
    "oh ok okay yes yeah hey hi hello thanks thank please sorry "
    "much more most own other another such only same here there "
    "because while during before until since through between both "
    "few many several none nothing something anything everything "
    "get got make made go going went come came take took "
    "know think want let say tell give see look find way thing "
    "don doesn didn won wouldn couldn shouldn wasn weren isn aren haven hasn "
    "don't doesn't didn't won't wouldn't couldn't shouldn't "
    "it's i'm i've i'll i'd you're you've you'll he's she's we're we've they're they've "
    "accordingly anyway almost certainly clearly completely "
    "exactly finally firstly furthermore generally however "
    "indeed instead later likewise maybe meanwhile moreover never nevertheless now "
    "nowhere otherwise perhaps quite rather regarding secondly similarly "
    "therefore thus wherever whichever "
    "basically literally obviously technically essentially "
    "that's there's here's what's who's how's let's can't".split()
)


def _content_words(text: str) -> list[str]:
    return [
        w
        for w in re.findall(
            r"[a-z0-9\u4e00-\u9fff]+(?:[-_][a-z0-9\u4e00-\u9fff]+)*",
            text.lower(),
        )
        if w not in _STOPWORDS
    ]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _bm25_score(query_tokens: set[str], chunk_tokens: set[str], df: dict[str, int], n: int) -> float:
    if not chunk_tokens or not query_tokens:
        return 0.0
    avg_len = max(sum(len(s) for s in df) / n, 1)
    k1, b = 1.5, 0.75
    score = 0.0
    for token in query_tokens:
        if token not in chunk_tokens:
            continue
        doc_freq = df.get(token, 0)
        idf = math.log((n - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
        chunk_len = len(chunk_tokens)
        tf_norm = (1 * (k1 + 1)) / (1 + k1 * (1 - b + b * chunk_len / avg_len))
        score += idf * tf_norm
    return score


def _keyword_boost(query: str, chunk_text: str, kw_norm: float) -> float:
    if query.lower() in chunk_text.lower():
        kw_norm = max(kw_norm, 0.8)
    return kw_norm


def _fused_score(vs: float, kw_norm: float) -> float:
    return FUSION_VS_WEIGHT * vs + FUSION_KW_WEIGHT * kw_norm


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
        from app.core.kb_ingest import join_chunks
        return join_chunks(chunks)

    def get_line_ranges(
        self, doc_id: str, chunk_indices: list[int]
    ) -> list[tuple[int, int]]:
        """Map chunk indices to line numbers in the full document.

        Returns a list of ``(start_line, end_line)`` tuples, one per continuous
        group of chunk indices.  Line numbers are 1-indexed.
        """
        text = self.get_document_text(doc_id)
        if not text or not chunk_indices:
            logger.warning("get_line_ranges: empty text=%s or indices=%s", bool(text), chunk_indices)
            return []

        from app.core.kb_ingest import CHUNK_OVERLAP, CHUNK_SIZE, join_chunks

        step = CHUNK_SIZE - CHUNK_OVERLAP

        # Fetch full chunk texts for joining
        res = self._lane.collection.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
        all_chunks = {
            int(meta.get("chunk", 0)): doc or ""
            for doc, meta in zip(res["documents"], res["metadatas"])
        }

        # Group into continuous ranges
        groups: list[list[int]] = []
        current = [chunk_indices[0]]
        for idx in chunk_indices[1:]:
            if idx == current[-1] + 1:
                current.append(idx)
            else:
                groups.append(current)
                current = [idx]
        groups.append(current)

        line_ranges: list[tuple[int, int]] = []
        for group in groups:
            chunks = [(i, all_chunks.get(i, "")) for i in group]
            group_text = join_chunks(chunks)
            pos = text.find(group_text)
            if pos >= 0:
                start_line = text[:pos].count("\n") + 1
                end_line = text[: pos + len(group_text)].count("\n") + 1
                logger.warning(
                    "get_line_ranges doc_id=%s group=%s found at pos=%d lines=%d-%d",
                    doc_id, group, pos, start_line, end_line,
                )
            else:
                # Fallback: calculate from chunk index
                start_pos = group[0] * step
                end_pos = group[-1] * step + CHUNK_SIZE
                start_line = text[: min(start_pos, len(text))].count("\n") + 1
                end_line = text[: min(end_pos, len(text))].count("\n") + 1
                logger.warning(
                    "get_line_ranges doc_id=%s group=%s NOT found via str.find, "
                    "fallback pos=%d lines=%d-%d | group_text[:100]=%r | "
                    "text at start_pos[:100]=%r",
                    doc_id, group, start_pos, start_line, end_line,
                    group_text[:100],
                    text[start_pos:start_pos + 100],
                )
            line_ranges.append((start_line, end_line))
        return line_ranges

    def search(
        self,
        query: str,
        k: int = 5,
        threshold: float = RAG_SIMILARITY_THRESHOLD,
        doc_ids: list[str] | None = None,
        context_chunks: int = 1,
    ) -> list[dict]:
        """Hybrid (semantic + keyword) search with context expansion.

        Each chunk is scored via ``_fused_score = 0.5 * vs + 0.5 * kw_norm``.
        Results above threshold are expanded with ``context_chunks`` neighbors
        on each side. Neighbors inherit the parent match's fused score.
        """
        if not self.healthy or self.count() == 0:
            return []

        # --- Fetch all candidate chunks ---
        try:
            n = self.count()
            where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
            all_data = self._lane.collection.get(
                where=where,
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning("KB fetch failed: %s", e)
            return []

        all_ids = all_data["ids"] or []
        all_docs = all_data["documents"] or []
        all_metas = all_data["metadatas"] or []
        if not all_ids:
            return []

        # --- BM25 keyword scores ---
        query_tokens = set(_content_words(query))
        dt = {doc or "": _tokenize(doc or "") for doc in all_docs}
        df: dict[str, int] = {}
        for toks in dt.values():
            for t in toks:
                df[t] = df.get(t, 0) + 1

        kw_scores: dict[str, float] = {}
        for cid, doc in zip(all_ids, all_docs):
            raw = _bm25_score(query_tokens, dt.get(doc or "", set()), df, n)
            kw_norm = min(raw / 6.0, 1.0) if raw > 0 else 0.0
            kw_norm = _keyword_boost(query, doc or "", kw_norm)
            kw_scores[cid] = kw_norm

        # --- Semantic vector scores ---
        try:
            vec_results = self._lane.collection.query(
                query_embeddings=self._lane.encode([query]),
                n_results=min(k * 10, n),
                include=["distances"],
                where=where,
            )
        except Exception as e:
            logger.warning("KB vector search failed: %s", e)
            vec_results = None

        vs_scores: dict[str, float] = {}
        if vec_results:
            for cid, dist in zip(
                (vec_results["ids"][0] or []),
                (vec_results["distances"][0] or []),
            ):
                vs_scores[cid] = max(0.0, 1.0 - dist)

        # --- Fuse scores ---
        scored: dict[str, dict] = {}
        for cid, doc, meta in zip(all_ids, all_docs, all_metas):
            vs = vs_scores.get(cid, 0.0)
            kw = kw_scores.get(cid, 0.0)
            fused = _fused_score(vs, kw)
            if fused < threshold:
                continue
            scored[cid] = {
                "document": doc,
                "metadata": {
                    "doc_id": meta.get("doc_id", ""),
                    "filename": meta.get("filename", "unknown"),
                    "chunk": meta.get("chunk", 0),
                },
                "similarity": round(fused, 3),
                "role": "match",
            }

        if not scored:
            return []

        if context_chunks <= 0:
            return list(scored.values())[:k]

        # --- Expand with context chunks ---
        wanted: dict[str, tuple[int, str, dict]] = {}
        for cid, entry in scored.items():
            doc_id = entry["metadata"]["doc_id"]
            chunk_i = entry["metadata"]["chunk"]
            for offset in range(-context_chunks, context_chunks + 1):
                nid = f"{doc_id}::{chunk_i + offset}"
                if nid not in wanted:
                    wanted[nid] = (chunk_i + offset, doc_id, entry)

        try:
            fetched = self._lane.collection.get(
                ids=list(wanted.keys()),
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning("KB neighbor fetch failed: %s", e)
            return list(scored.values())[:k]

        chunk_map: dict[str, dict] = {}
        for fid, fdoc, fmeta in zip(
            fetched["ids"], fetched["documents"], fetched["metadatas"]
        ):
            chunk_map[fid] = {
                "document": fdoc,
                "metadata": {
                    "doc_id": fmeta.get("doc_id", ""),
                    "filename": fmeta.get("filename", "unknown"),
                    "chunk": fmeta.get("chunk", 0),
                },
            }

        out: list[dict] = []
        added: set[str] = set()
        match_count = 0
        for cid in sorted(scored, key=lambda x: scored[x]["similarity"], reverse=True):
            if match_count >= k:
                break
            entry = scored[cid]
            doc_id = entry["metadata"]["doc_id"]
            chunk_i = entry["metadata"]["chunk"]

            for offset in range(-context_chunks, context_chunks + 1):
                nid = f"{doc_id}::{chunk_i + offset}"
                if nid in chunk_map and nid not in added:
                    item = chunk_map[nid]
                    if nid in scored:
                        item["role"] = "match"
                        item["similarity"] = scored[nid]["similarity"]
                    else:
                        item["role"] = "context"
                        item["similarity"] = entry["similarity"]
                    out.append(item)
                    added.add(nid)

            match_count += 1

        return out

    def get_stats(self) -> dict:
        if self._lane is None:
            return {"healthy": False, "count": 0, "lane": None, "dimension": 384}
        return {
            "healthy": self.healthy,
            "count": self.count(),
            "lane": self._lane.name,
            "dimension": self._lane.dimension,
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