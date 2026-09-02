import json
import logging
import math
import re
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bm25 import bm25_score, content_words, has_content_words, keyword_boost, text_similarity, tokenize
from app.models import Memory
from app.models.conversation import Setting
from app.providers.base import Provider, ProviderCallParams
from app.schemas.common import ChatMessage, MessagePart
from app.schemas.memory import MEMORY_CATEGORIES, MemoryCreate, MemoryPatch

logger = logging.getLogger(__name__)

_MEMORY_KEYS = ("enable_memory", "memory_auto_extract")

# Fusion retrieval: final = VS_WEIGHT*vs + KW_WEIGHT*kw_norm + REC_WEIGHT*recency.
# Weights sum to 1.0 so final is a bounded [0,1] relevance blend.
FUSION_VS_WEIGHT = 0.55
FUSION_KW_WEIGHT = 0.40
FUSION_REC_WEIGHT = 0.05
# Fusion relevance threshold: candidates below this fused score are not injected.
# Tunable — governs recall vs precision on the injected memories.
FUSION_THRESHOLD = 0.19

# Cap on the query fed into retrieval. The cross-encoder's memory grows with
# query length (attention over every query/document pair); long pastes can
# allocate gigabytes and OOM small deployments. Embeddings read ~512 tokens
# anyway, so nothing relevant is lost past this point.
RETRIEVAL_QUERY_MAX_CHARS = 2000

# Semantic near-duplicate threshold: cosine at/above this collapses a new text
# onto an existing memory in the vector store. Tunable — still being tested.
SEMANTIC_DUP_THRESHOLD = 0.8

# Recency freshness (0..1 decay tiebreak): fresh memories score higher.
# RECENT_DECAY=0.05/day → freshness halves every ~20 days.
RECENT_DECAY = 0.05


def _recency_freshness(m: Memory) -> float:
    """Freshness in (0,1]: 1.0 for brand-new memories, decaying toward 0 over time."""
    ref = m.last_recalled_at or m.created_at
    if ref is None:
        return 0.0
    days_old = max((datetime.now(UTC) - ref).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + days_old * RECENT_DECAY)


def _fused_score(vs: float, kw_norm: float, freshness: float) -> float:
    """Bounded [0,1] relevance blend of cosine, BM25, and recency."""
    return (
        FUSION_VS_WEIGHT * vs
        + FUSION_KW_WEIGHT * kw_norm
        + FUSION_REC_WEIGHT * freshness
    )


def _bounded_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


async def load_memory_config(db: AsyncSession) -> dict[str, bool]:
    res = await db.execute(select(Setting).where(Setting.key.in_(_MEMORY_KEYS)))
    rows = {s.key: s.value for s in res.scalars()}
    return {
        "enable_memory": _bounded_bool(rows.get("enable_memory"), True),
        "memory_auto_extract": _bounded_bool(rows.get("memory_auto_extract"), True),
    }


def get_text_similarity(text1: str, text2: str) -> float:
    return text_similarity(text1, text2)


# Recency freshness (0..1 decay tiebreak): fresh memories score higher.
# RECENT_DECAY=0.05/day → freshness halves every ~20 days.
RECENT_DECAY = 0.05


def _recency_freshness(m: Memory) -> float:
    age = time.time() - m.updated_at.timestamp()
    days = age / 86400.0
    return max(0.0, min(1.0, 1.0 - RECENT_DECAY * days))


async def list_memories(db: AsyncSession) -> list[Memory]:
    stmt = select(Memory).order_by(
        Memory.pinned.desc(), Memory.created_at.desc()
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_memory(db: AsyncSession, memory_id: str) -> Memory | None:
    return await db.get(Memory, memory_id)


async def find_duplicate(db: AsyncSession, text: str) -> Memory | None:
    cleaned = text.strip().lower()
    result = await db.execute(
        select(Memory).where(func.lower(Memory.text) == cleaned).limit(1)
    )
    exact = result.scalars().first()
    if exact is not None:
        return exact

    # Near-duplicate detection: token overlap high enough (and length not too
    # far apart) that the new text states essentially the same fact. Covers
    # variants like "My name is X" vs "The user's name is X" and punctuation /
    # prefix noise produced by auto-extraction.
    norm = _normalize_key(text)
    if not norm:
        return None
    rows = await db.execute(select(Memory).order_by(Memory.updated_at.desc()).limit(400))
    for existing in rows.scalars():
        other = _normalize_key(existing.text)
        if not other:
            continue
        if other == norm:
            return existing
        if text_similarity(norm, other) >= 0.7:
            return existing

    # Semantic near-duplicate via the vector store (best effort).
    try:
        from app.core.memory_vector import get_memory_store

        store = await get_memory_store(db)
        if store.healthy:
            similar_id = store.find_similar(text, threshold=SEMANTIC_DUP_THRESHOLD)
            if similar_id:
                mem = await get_memory(db, similar_id)
                if mem is not None:
                    return mem
    except Exception:
        pass
    return None


def _normalize_key(text: str) -> str:
    t = text.strip().lower()
    for prefix in ("the user's ", "the user is ", "user's ", "user is "):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    t = t.rstrip(".")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


async def create_memory(
    db: AsyncSession,
    data: MemoryCreate,
    source: str = "manual",
    conversation_id: str | None = None,
) -> Memory | None:
    text = data.text.strip()
    if not text:
        return None
    # Manual adds express the user's explicit choice of text, category and
    # pin. Don't silently return a semantic near-duplicate, or their category
    # and pinned selection would be discarded. Dedup stays active for auto and
    # inline extraction where a near-match genuinely means "already known".
    dup = await find_duplicate(db, text) if source != "manual" else None
    if dup is not None:
        return dup
    category = data.category if data.category in MEMORY_CATEGORIES else "fact"
    if data.pinned and await count_pinned_memories(db) >= MAX_PINNED_MEMORIES:
        raise PinLimitExceeded()
    mem = Memory(
        text=text,
        category=category,
        source=source,
        pinned=bool(data.pinned),
        conversation_id=conversation_id,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    await _sync_vector_add(db, mem)
    return mem


async def update_memory(
    db: AsyncSession, memory_id: str, data: MemoryPatch
) -> Memory | None:
    mem = await get_memory(db, memory_id)
    if mem is None:
        return None
    if data.text is not None:
        text = data.text.strip()
        if text:
            mem.text = text
    if data.category is not None and data.category in MEMORY_CATEGORIES:
        mem.category = data.category
    if data.pinned is not None:
        if data.pinned and not mem.pinned:
            if await count_pinned_memories(db) >= MAX_PINNED_MEMORIES:
                raise PinLimitExceeded()
        mem.pinned = data.pinned
    await db.commit()
    await db.refresh(mem)
    if data.text is not None:
        await _sync_vector_add(db, mem, replace=True)
    return mem


async def delete_memory(db: AsyncSession, memory_id: str) -> bool:
    mem = await get_memory(db, memory_id)
    if mem is None:
        return False
    await db.delete(mem)
    await db.commit()
    try:
        from app.core.memory_vector import get_memory_store

        store = await get_memory_store(db)
        if store.healthy:
            store.remove(memory_id)
    except Exception:
        pass
    return True


async def _sync_vector_add(db: AsyncSession, mem: Memory, replace: bool = False) -> None:
    try:
        from app.core.memory_vector import get_memory_store

        if not mem.text.strip():
            return
        store = await get_memory_store(db)
        if store.healthy:
            if replace:
                store.update(mem.id, mem.text)
            else:
                store.add(mem.id, mem.text)
    except Exception:
        pass


async def memory_stats(db: AsyncSession) -> dict[str, Any]:
    rows = await db.execute(
        select(Memory.category, func.count(Memory.id)).group_by(Memory.category)
    )
    categories = {cat: count for cat, count in rows.all()}
    total = sum(categories.values())
    return {"total": total, "categories": categories}


# ---------------------------------------------------------------------------
# Retrieval (hybrid: keyword + optional semantic embeddings)
# ---------------------------------------------------------------------------

_IDENTITY_WORDS = ["name", "who", "i", "am", "called", "identity", "myself", "me", "my"]
_CONTACT_WORDS = ["phone", "email", "address", "contact", "number", "where", "located", "reach", "telephone"]
_PREFERENCE_WORDS = ["like", "prefer", "favorite", "want", "love", "hate", "dislike", "enjoy", "interested"]
_TASK_WORDS = ["todo", "task", "remind", "meeting", "appointment", "schedule", "deadline"]
_FACT_WORDS = ["what", "when", "where", "how", "why", "explain", "describe", "information", "know"]


def _query_type(query: str) -> str | None:
    q = query.lower()
    if any(w in q for w in _IDENTITY_WORDS):
        return "identity"
    if any(w in q for w in _CONTACT_WORDS):
        return "contact"
    if any(w in q for w in _PREFERENCE_WORDS):
        return "preference"
    if any(w in q for w in _TASK_WORDS):
        return "task"
    if any(w in q for w in _FACT_WORDS):
        return "fact"
    return None


def _is_identity_memory(mem: Memory) -> bool:
    text = mem.text
    return bool(
        re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", text)
        or any(
            w in text.lower()
            for w in ["name is", "i'm", "i am", "called", "my name", "named", "call me"]
        )
    )


def _bm25_score(query_tokens: set[str], mem_tokens: set[str], df: dict[str, int], n: int) -> float:
    return bm25_score(query_tokens, mem_tokens, df, n)


_PINNED_CORE_LIMIT = 10
MAX_PINNED_MEMORIES = 10


async def count_pinned_memories(db: AsyncSession) -> int:
    stmt = select(func.count(Memory.id)).where(Memory.pinned.is_(True))
    result = await db.execute(stmt)
    return result.scalar() or 0


class PinLimitExceeded(Exception):
    pass


async def hybrid_retrieve(
    db: AsyncSession, query: str, k: int = 5
) -> list[Memory]:
    """Retrieve memories relevant to the query.

    Pipeline:
      1. Exclude pinned memories (always injected separately)
      2. Semantic + keyword union, each with cosine (vs) and BM25 (kw_norm)
      3. Fuse into a bounded relevance score; keep candidates above FUSION_THRESHOLD
      4. Rerank survivors by cross-encoder relevance, cap at k
    """
    query = query[:RETRIEVAL_QUERY_MAX_CHARS]
    if not query.strip():
        return []
    all_mems = await list_memories(db)
    if not all_mems:
        return []
    pool = [m for m in all_mems if not m.pinned]
    if not pool:
        return []

    candidates = await _union_with_scores(db, query, pool)
    if not candidates:
        return []

    kept = [
        mem
        for mem, vs, kw_norm in candidates
        if _fused_score(vs, kw_norm, _recency_freshness(mem)) > FUSION_THRESHOLD
    ]
    if not kept:
        return []

    # Rerank survivors by cross-encoder relevance (ordering only; does not veto).
    scores = await _rerank_scores(db, query, [mem.text for mem in kept])
    if scores is not None:
        ranked = sorted(zip(kept, scores), key=lambda t: t[1], reverse=True)
        return [mem for mem, _ in ranked[:k]]
    logger.warning("Reranker failed, returning fusion-kept memories")
    return kept[:k]


async def search_memories(
    db: AsyncSession, query: str, limit: int = 50, offset: int = 0, sort: str = "relevance"
) -> list[Memory]:
    """Hybrid (semantic + keyword) search over memories for the management UI.

    Exact keyword matches float to the top, then semantic results. Within each
    group, memories are sorted by the chosen field (relevance=uses, recalled=last_recalled_at, added=created_at).
    """
    query = query[:RETRIEVAL_QUERY_MAX_CHARS]
    if not query.strip():
        return []
    all_mems = await list_memories(db)
    if not all_mems:
        return []
    pool = [m for m in all_mems if not m.pinned]
    if not pool:
        return []

    candidates = await _union_with_scores(db, query, pool)
    if not candidates:
        return []

    query_lower = query.lower()
    exact: list[Memory] = []
    semantic: list[Memory] = []
    for mem, _, _ in candidates:
        if query_lower in mem.text.lower():
            exact.append(mem)
        else:
            semantic.append(mem)

    if sort == "recalled":
        key = lambda m: (m.last_recalled_at or m.created_at)
        reverse = True
    elif sort == "added":
        key = lambda m: m.created_at
        reverse = True
    else:
        key = lambda m: m.uses
        reverse = True

    exact.sort(key=key, reverse=reverse)
    semantic.sort(key=key, reverse=reverse)

    ranked = exact + semantic
    return ranked[offset : offset + limit]


async def _rerank_scores(
    db: AsyncSession, query: str, texts: list[str]
) -> list[float] | None:
    """Cross-encoder scores for a batch of texts.

    Returns None if the reranker is unavailable, so the caller can fall back to
    the fusion-kept order.
    """
    if not texts:
        return None
    try:
        from app.config import get_settings
        from app.core.embeddings import get_reranker_engine

        cache_dir = f"{get_settings().data_dir}/fastembed"
        reranker = get_reranker_engine(cache_dir=cache_dir)
        return reranker.rerank(query, texts)
    except Exception as e:
        logger.warning("Reranker failed (%s)", e)
        return []


async def _union_with_scores(
    db: AsyncSession, query: str, pool: list[Memory]
) -> list[tuple[Memory, float, float]]:
    """Semantic + keyword union retrieval.

    Returns ``(memory, cosine, kw_norm)`` per candidate, where cosine is the
    vector-store similarity (vs) and kw_norm is BM25 scaled to [0,1]. A candidate
    qualifies only when it clears an axis gate — cosine ≥ 0.1 or kw_norm ≥ 0.12.
    Does NOT apply the fusion threshold; that gates injection in hybrid_retrieve.
    """
    by_id = {m.id: m for m in pool}
    scored: dict[str, tuple[float, float]] = {}

    # --- Semantic filter (ChromaDB pre-vectorized) ---
    try:
        from app.core.memory_vector import get_memory_store

        store = await get_memory_store(db)
        if store.healthy:
            for mid, vs in store.semantic_filter(query, k=10):
                if mid in by_id:
                    prev = scored.get(mid, (0.0, 0.0))
                    scored[mid] = (vs, prev[1])
            logger.debug("semantic filter: %d / %d", len(scored), len(pool))
    except Exception:
        pass

    # --- Keyword filter (BM25 on pool) ---
    query_tokens = set(content_words(query))
    if query_tokens:
        n = len(pool)
        doc_freq: dict[str, int] = {}
        mem_tokens: dict[str, set[str]] = {}
        for m in pool:
            toks = tokenize(m.text)
            mem_tokens[m.id] = toks
            for t in toks:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        for m in pool:
            kw_raw = _bm25_score(query_tokens, mem_tokens[m.id], doc_freq, n)
            kw_norm = min(kw_raw / 6.0, 1.0) if kw_raw > 0 else 0.0
            kw_norm = _keyword_boost(query, m, kw_norm)
            if kw_norm >= 0.12 and m.id in by_id:
                prev = scored.get(m.id, (0.0, 0.0))
                scored[m.id] = (prev[0], kw_norm)

    if not scored:
        return []
    return [(by_id[mid], vs, kw) for mid, (vs, kw) in scored.items()]


def _keyword_boost(query: str, m: Memory, kw_norm: float) -> float:
    """Apply query-type and exact-match boosts to a raw normalized BM25 score."""
    mem_lower = m.text.lower()
    boost = 1.0
    qtype = _query_type(query)
    if qtype == "identity":
        boost = 1.4 if _is_identity_memory(m) else boost
    elif qtype == "contact" and any(w in mem_lower for w in ["@", ".com", "phone", "number", "address", "http", "www", "tel:"]):
        boost = 1.3
    elif qtype == "preference" and any(w in mem_lower for w in ["like", "love", "hate", "dislike", "prefer", "favorite", "enjoy", "interested"]):
        boost = 1.3
    elif qtype == "task" and any(w in mem_lower for w in ["todo", "task", "remind", "meeting", "appointment", "schedule", "deadline", "need to"]):
        boost = 1.3
    kw_norm = min(kw_norm * boost, 1.0)

    if query.lower() in m.text.lower():
        kw_norm = max(kw_norm, 0.8)

    return kw_norm


async def select_memories_for_query(
    db: AsyncSession, query: str, max_memories: int = 15
) -> list[tuple[Memory, str]]:
    """Combine user-pinned memories with query retrieval.

    Only memories explicitly pinned by the user are always injected; everything
    else must match the query. Pinned memories are user-decided (via the UI),
    never inferred from category or text.

    Returns ``(memory, type)`` pairs where ``type`` is ``"pinned"`` for
    always-on memories and ``"recalled"`` for query-retrieved ones.
    """
    all_mems = await list_memories(db)
    if not all_mems:
        return []
    selected: list[tuple[Memory, str]] = []
    seen: set[str] = set()
    pinned = [m for m in all_mems if m.pinned]
    for m in pinned[:_PINNED_CORE_LIMIT]:
        selected.append((m, "pinned"))
        seen.add(m.id)
    for m in await hybrid_retrieve(db, query, k=10):
        if m.id not in seen:
            selected.append((m, "recalled"))
            seen.add(m.id)

    # Reset recency for memories actually injected (query-retrieved only).
    final = selected[:max_memories]
    for m, typ in final:
        if typ == "recalled":
            m.last_recalled_at = datetime.now(UTC)
            m.uses = (m.uses or 0) + 1
    await db.commit()

    return final


def format_memory_context(memories: list[Memory]) -> str:
    lines = [
        f"- [{m.category}] {m.text.strip()}"
        for m in memories
        if m.text and m.text.strip()
    ]
    if not lines:
        return ""
    header = (
        "The user has shared the following memories in past conversations. "
        "Do not bring them up unless the user asks or they are directly "
        "relevant to the current question."
    )
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Automatic LLM extraction
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = (
    "Your task is to extract durable, certain information about the USER — including facts, preferences, interests, and notable events — from the "
    "conversation above. Extract from the user's first message — this instruction "
    "message is not the user. The assistant's message is context only — do not "
    "extract facts from it.\n\n"
    "Rules:\n"
    "- Reformulate the user's words into a clear fact about the user\n"
    "- Use 'User' as the subject\n"
    "- Only extract facts that are clearly stated — avoid vague or uncertain statements\n"
    "- If the user is asking a question, return [] — questions contain no facts about the user\n"
    "- Never extract feelings, emotions, or states of mind\n"
    "- Only capture interests the user explicitly states or strongly implies — don't infer them from topics merely discussed\n"
    "- If nothing durable was revealed, return []\n\n"
    "Return a JSON array of {\"text\": \"...\", \"category\": \"...\"}.\n"
    "Categories: identity, preference, event, contact, fact.\n"
    "Your response must start with `[` and end with `]`. No other text."
)


def _parse_extraction(text: str) -> list[dict[str, str]]:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, str):
            t = item.strip()
            if t:
                out.append({"text": t, "category": "fact"})
            continue
        if not isinstance(item, dict):
            continue
        t = str(item.get("text", "")).strip()
        if not t:
            continue
        cat = str(item.get("category", "fact")).strip().lower()
        if cat not in MEMORY_CATEGORIES:
            cat = "fact"
        out.append({"text": t, "category": cat})
    return out


async def extract_memories_with_model(
    provider: Provider,
    model: str,
    user_text: str,
    assistant_text: str = "",
) -> list[dict[str, str]]:
    """Ask the model to extract memories from the user's message.

    The assistant's message is passed as context for resolving pronouns.
    The instructions are inlined in the user message for models that ignore system.
    """
    if not user_text.strip():
        return []
    instructions = _EXTRACT_SYSTEM.strip()
    messages: list[ChatMessage] = [
        ChatMessage(role="user", parts=[MessagePart(text=user_text[:1800])]),
    ]
    if assistant_text:
        messages.append(
            ChatMessage(role="assistant", parts=[MessagePart(text=assistant_text[:2000])])
        )
    messages.append(
        ChatMessage(role="user", parts=[MessagePart(text=instructions)])
    )

    async def _attempt() -> str:
        params = ProviderCallParams(
            model=model,
            system=_EXTRACT_SYSTEM,
            messages=messages,
            tools=[],
            max_tokens=2000,
            temperature=0.2,
            reasoning=False,
        )
        out = ""
        async for event in provider.stream(params):
            if event.kind == "text":
                out += event.content
        return out

    try:
        out = await _attempt()
    except Exception as e:
        logger.warning("memory extraction failed: %s", e)
        return []
    parsed = _parse_extraction(out)
    return parsed
