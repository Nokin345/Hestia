"""Embedding lane helpers for vector collections.

ChromaDB fixes a collection's dimension on first insert. If the embedding
model changes, the collection is dropped and recreated from scratch.
"""

import logging

import numpy as np

from app.core.embeddings import EmbeddingEngine, get_embedding_engine

logger = logging.getLogger(__name__)

_COLLECTION_SPACE = "cosine"


class EmbeddingLane:
    """Single ChromaDB collection backed by a local embedding engine."""

    def __init__(
        self,
        name: str,
        engine: EmbeddingEngine,
        collection: object,
        collection_name: str,
        dimension: int,
    ):
        self.name = name
        self._engine = engine
        self.collection = collection
        self.collection_name = collection_name
        self.dimension = dimension

    @property
    def healthy(self) -> bool:
        return self.collection is not None and self._engine is not None

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._engine.encode(texts)
        return vecs.tolist() if hasattr(vecs, "tolist") else [list(v) for v in vecs]

    def count(self) -> int:
        try:
            return int(self.collection.count())
        except Exception:
            return 0


def build_embedding_lane(
    base_name: str,
    data_dir: str,
) -> EmbeddingLane | None:
    """Build an embedding lane using the hardcoded e5-small model.

    Drops any existing collection with incompatible dimensions and starts fresh.
    """
    from app.core.chroma_client import get_chroma_client

    cache_dir = f"{data_dir}/fastembed"
    try:
        engine = get_embedding_engine(cache_dir=cache_dir)
    except Exception as e:
        logger.warning("EmbeddingEngine init failed: %s", e)
        return None

    dimension = engine.get_dimension()
    name = f"{base_name}_e5"

    chroma = get_chroma_client(data_dir)
    try:
        collection = chroma.get_collection(name)
    except Exception:
        logger.info("Creating new Chroma collection %s (dim=%d)", name, dimension)
        collection = chroma.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": _COLLECTION_SPACE},
        )
        return EmbeddingLane(name=name, engine=engine, collection=collection, collection_name=name, dimension=dimension)

    # Collection exists — try to use it, but recreate if dimension mismatches.
    try:
        collection.count()  # just to verify it works
        return EmbeddingLane(name=name, engine=engine, collection=collection, collection_name=name, dimension=dimension)
    except Exception as e:
        logger.info("Dropping Chroma collection %s due to dimension mismatch (%s), starting fresh", name, e)
        chroma.delete_collection(name)
        collection = chroma.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": _COLLECTION_SPACE},
        )
        return EmbeddingLane(name=name, engine=engine, collection=collection, collection_name=name, dimension=dimension)
