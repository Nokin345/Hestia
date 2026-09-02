"""Embedding and reranking for memory retrieval.

All models are local fastembed ONNX — no remote endpoints.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_RERANK_MODEL = "jinaai/jina-reranker-v2-base-multilingual"
_EMBED_CACHE_DIR = None


class EmbeddingEngine:
    """Local embedding via fastembed (ONNX)."""

    def __init__(self, cache_dir: str | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError("fastembed is not installed") from e

        kwargs: dict = {"model_name": _EMBED_MODEL}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self._embedder = TextEmbedding(**kwargs)
        self._dim: int | None = None
        logger.info("EmbeddingEngine loaded %s", _EMBED_MODEL)

    def get_dimension(self) -> int:
        if self._dim is not None:
            return self._dim
        vec = self.encode(["hello"])
        self._dim = int(vec.shape[1])
        return self._dim

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts, return l2-normalized vectors for cosine similarity."""
        if not texts:
            return np.array([], dtype="float32")
        vecs = np.array(list(self._embedder.embed(texts)), dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return vecs / norms


class RerankerEngine:
    """Local reranking via fastembed TextCrossEncoder."""

    def __init__(self, cache_dir: str | None = None):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:
            raise RuntimeError("fastembed.rerank is not installed") from e

        kwargs: dict = {"model_name": _RERANK_MODEL}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self._reranker = TextCrossEncoder(**kwargs)
        logger.info("RerankerEngine loaded %s", _RERANK_MODEL)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return raw logit scores for each document against the query."""
        if not documents:
            return []
        return [float(s) for s in self._reranker.rerank(query, documents)]


_RERANK_ENGINE: "RerankerEngine | None" = None
_EMBED_ENGINE: "EmbeddingEngine | None" = None


def get_embedding_engine(cache_dir: str | None = None) -> EmbeddingEngine:
    global _EMBED_ENGINE
    if _EMBED_ENGINE is None:
        _EMBED_ENGINE = EmbeddingEngine(cache_dir=cache_dir)
    return _EMBED_ENGINE


def get_reranker_engine(cache_dir: str | None = None) -> RerankerEngine:
    global _RERANK_ENGINE
    if _RERANK_ENGINE is None:
        _RERANK_ENGINE = RerankerEngine(cache_dir=cache_dir)
    return _RERANK_ENGINE
