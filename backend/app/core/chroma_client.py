"""Singleton ChromaDB persistent client.

Uses ChromaDB's embedded PersistentClient (SQLite-backed) so no separate
service is required. Storage lives under the app's data dir so it persists
across container restarts via the ``backend_data`` volume.
"""

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_client = None
_client_path: str = ""
_lock = threading.Lock()


def get_chroma_client(data_dir: str):
    """Get or create the singleton ChromaDB persistent client."""
    global _client, _client_path
    chroma_dir = str(Path(data_dir) / "chroma")
    with _lock:
        if _client is not None and _client_path == chroma_dir:
            return _client
        import chromadb

        Path(chroma_dir).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=chroma_dir)
        _client_path = chroma_dir
        try:
            _client.heartbeat()
        except Exception:
            logger.warning("ChromaDB heartbeat failed; collection ops will re-probe")
        logger.info("ChromaDB connected: %s", chroma_dir)
        return _client


def reset_client() -> None:
    """Drop the singleton (e.g. after settings change)."""
    global _client
    with _lock:
        _client = None