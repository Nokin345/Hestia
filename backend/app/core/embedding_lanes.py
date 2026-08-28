"""Embedding lane helpers for the memory vector store.

ChromaDB fixes a collection's dimension on first insert, so if the embedding
model/endpoint changes we must recreate the collection and re-embed. The
fingerprint is embedded in the collection metadata so a settings change is
detected and the collection is reset without losing rows.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from app.core.embedding_config import EmbeddingConfig
from app.core.embeddings import FastEmbedClient, build_embedding_client

logger = logging.getLogger(__name__)

_COLLECTION_SPACE = "cosine"


@dataclass
class EmbeddingLane:
    name: str
    client: object
    collection: object
    collection_name: str
    model: str
    url: str
    dimension: int
    fingerprint: str

    @property
    def healthy(self) -> bool:
        return self.collection is not None and self.client is not None

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self.client.encode(list(texts))
        return vecs.tolist() if hasattr(vecs, "tolist") else [list(v) for v in vecs]

    def count(self) -> int:
        try:
            return int(self.collection.count())
        except Exception:
            return 0


def _fingerprint(url: str, model: str, dimension: int) -> str:
    raw = f"{url}\n{model}\n{dimension}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _metadata(lane_name: str, url: str, model: str, dimension: int, fingerprint: str) -> dict:
    return {
        "hnsw:space": _COLLECTION_SPACE,
        "embedding_lane": lane_name,
        "embedding_url": url,
        "embedding_model": model,
        "embedding_dimension": dimension,
        "embedding_fingerprint": fingerprint,
    }


def build_embedding_lane(
    base_name: str,
    cfg: EmbeddingConfig,
    data_dir: str,
) -> EmbeddingLane | None:
    """Build a single lane from the current embedding config.

    Returns None if no embedding backend is available (graceful degradation).
    """
    from app.core.chroma_client import get_chroma_client

    client, backend = build_embedding_client(cfg, cache_dir=f"{data_dir}/fastembed")
    if client is None:
        return None

    lane_name = "remote" if backend == "remote" else "fastembed"
    model = getattr(client, "model", "")
    url = getattr(client, "url", "local://fastembed")
    dimension = int(client.get_dimension())
    fp = _fingerprint(url, model, dimension)
    name = f"{base_name}_{lane_name}"
    metadata = _metadata(lane_name, url, model, dimension, fp)

    chroma = get_chroma_client(data_dir)
    collection = _get_or_reset_collection(chroma, name, metadata, client)

    return EmbeddingLane(
        name=lane_name,
        client=client,
        collection=collection,
        collection_name=name,
        model=model,
        url=url,
        dimension=dimension,
        fingerprint=fp,
    )


def _get_or_reset_collection(chroma_client, name: str, metadata: dict, client: Any):
    try:
        collection = chroma_client.get_collection(name)
    except Exception:
        return chroma_client.get_or_create_collection(name=name, metadata=metadata)

    current = collection.metadata or {}
    if not (
        current.get("embedding_fingerprint") not in (None, metadata["embedding_fingerprint"])
        or current.get("embedding_dimension") not in (None, metadata["embedding_dimension"])
    ):
        return collection

    logger.info(
        "Recreating Chroma collection %s for embedding change (%s -> %s)",
        name,
        current.get("embedding_fingerprint"),
        metadata["embedding_fingerprint"],
    )
    preserved = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
    try:
        preserved = collection.get(include=["documents", "metadatas", "embeddings"]) or preserved
    except Exception as e:
        logger.warning("Could not preserve rows for %s: %s", name, e)
        preserved = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

    ids = preserved.get("ids") or []
    docs = preserved.get("documents") or []

    chroma_client.delete_collection(name)
    collection = chroma_client.get_or_create_collection(name=name, metadata=metadata)
    if ids and docs:
        try:
            embeddings = client.encode(list(docs))
            collection.add(
                ids=ids,
                documents=docs,
                embeddings=embeddings,
            )
            logger.info("Re-embedded %s rows after resetting %s", len(ids), name)
        except Exception as e:
            logger.warning("Could not write reset collection %s: %s", name, e)
    return collection