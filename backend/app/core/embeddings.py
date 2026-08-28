"""Embedding clients for semantic memory search.

Priority order based on settings:
  1. Remote HTTP API (OpenAI-compatible /v1/embeddings) when embedding_url set
  2. Local fastembed (ONNX, ~50MB download) as zero-config fallback

Modeled after the Odysseus memory implementation.
"""

import logging

import httpx
import numpy as np

from app.core.embedding_config import EmbeddingConfig

logger = logging.getLogger(__name__)

_DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class RemoteEmbeddingClient:
    """OpenAI-compatible embeddings client supported by llama.cpp / vLLM / Ollama."""

    def __init__(self, url: str, model: str, api_key: str = ""):
        self.url = url
        self.model = model
        self.api_key = api_key
        self._dim: int | None = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0)
        )
        self._batch_size = 8
        self._max_chars = 900

    def get_dimension(self) -> int:
        if self._dim is not None:
            return self._dim
        vec = self.encode(["hello"])
        self._dim = int(vec.shape[1])
        logger.info("Embedding dimension: %s (model=%s)", self._dim, self.model)
        return self._dim

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype="float32")
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            all_vecs.extend(self._embedd_batch(batch))
        vecs = np.array(all_vecs, dtype="float32")
        if vecs.size:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            vecs = vecs / norms
        if self._dim is None and vecs.size:
            self._dim = int(vecs.shape[1])
        return vecs

    def _embedd_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            payload: dict = {"input": batch}
            if self.model:
                payload["model"] = self.model
            resp = self._client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response is None or e.response.status_code != 400:
                raise
            if len(batch) > 1:
                return [
                    v for b in batch for v in self._embedd_batch([b[: self._max_chars]])
                ]
            raise
        embeddings = data.get("data", [])
        embeddings.sort(key=lambda e: e.get("index", 0))
        return [list(emb["embedding"]) for emb in embeddings]


class FastEmbedClient:
    """Local embedding client using fastembed (ONNX). No external service needed."""

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2", cache_dir: str | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. Either install it (pip install fastembed) "
                "or configure a remote embeddings endpoint."
            ) from e
        self.model = model
        kwargs: dict = {"model_name": model}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
            import os

            os.makedirs(cache_dir, exist_ok=True)
        self._embedding = TextEmbedding(**kwargs)
        self._dim: int | None = None
        logger.info("FastEmbed loaded local model=%s", model)

    def get_dimension(self) -> int:
        if self._dim is not None:
            return self._dim
        vec = self.encode(["hello"])
        self._dim = int(vec.shape[1])
        return self._dim

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype="float32")
        vecs = np.array(list(self._embedding.embed(texts)), dtype="float32")
        if vecs.size:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            vecs = vecs / norms
        if self._dim is None and vecs.size:
            self._dim = int(vecs.shape[1])
        return vecs


def build_embedding_client(cfg: EmbeddingConfig, cache_dir: str | None = None):
    """Factory: try remote HTTP first, fall back to local fastembed.

    Returns ``(client, backend)`` where backend is ``"remote"`` or
    ``"local"``, or ``(None, "none")`` if neither is available.
    """
    if cfg.use_remote:
        try:
            client = RemoteEmbeddingClient(cfg.url, cfg.model, cfg.api_key)
            client.get_dimension()
            return client, "remote"
        except Exception as e:
            logger.warning("Remote embedding endpoint unavailable (%s); trying local", e)
    try:
        client = FastEmbedClient(model="sentence-transformers/all-MiniLM-L6-v2", cache_dir=cache_dir)
        client.get_dimension()
        return client, "local"
    except ImportError:
        logger.error("fastembed not installed — run: pip install fastembed")
    except Exception as e:
        logger.error("FastEmbed init failed: %s", e)
    return None, None