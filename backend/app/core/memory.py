import json
import logging
import math
import re
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory
from app.models.conversation import Setting
from app.providers.base import Provider, ProviderCallParams
from app.schemas.common import ChatMessage, MessagePart
from app.schemas.memory import MEMORY_CATEGORIES, MemoryCreate, MemoryPatch

logger = logging.getLogger(__name__)

_MEMORY_KEYS = ("enable_memory", "memory_auto_extract")


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


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


_STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need ought dare "
    "i me my mine we us our ours you your yours he him his she her hers "
    "it its they them their theirs this that these those "
    "and but or nor not no so if then else than too also very "
    "in on at to for of by with from up out about into over after "
    "what when where which who whom how why all each every some any "
    "just very really actually like well also still already even "
    "oh ok okay yes yeah hey hi hello no"
    "there here because while during before until since through between "
    "don't doesnt didn't won't wouldn't couldn't ain't isn't it's i'll i'd "
    "you're i'm we're they're we'll what's that's there's let's".split()
)


def _content_words(text: str) -> list[str]:
    """Meaningful content words: stopwords removed, min len 3 (odysseus-style)."""
    return [
        w
        for w in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    ]


def get_text_similarity(text1: str, text2: str) -> float:
    t1 = tokenize(text1)
    t2 = tokenize(text2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


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
        if get_text_similarity(norm, other) >= 0.7:
            return existing

    # Semantic near-duplicate via the vector store (best effort).
    try:
        from app.core.memory_vector import get_memory_store

        store = await get_memory_store(db)
        if store.healthy:
            similar_id = store.find_similar(text, threshold=0.85)
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
        await _sync_vector_add(db, mem)
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


async def _sync_vector_add(db: AsyncSession, mem: Memory) -> None:
    try:
        from app.core.memory_vector import get_memory_store

        if not mem.text.strip():
            return
        store = await get_memory_store(db)
        if store.healthy:
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
    if not mem_tokens or not query_tokens:
        return 0.0
    avg_len = max(sum(len(s) for s in df) / n, 1)
    k1, b = 1.5, 0.75
    score = 0.0
    for token in query_tokens:
        if token not in mem_tokens:
            continue
        doc_freq = df.get(token, 0)
        idf = math.log((n - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
        mem_len = len(mem_tokens)
        tf_norm = (1 * (k1 + 1)) / (1 + k1 * (1 - b + b * mem_len / avg_len))
        score += idf * tf_norm
    return score


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
      2. Semantic filter (top-10, cosine ≥ 0.2350)
      3. Keyword filter (top-10, BM25 ≥ 0.12)
      4. Union of both candidate sets
      5. If union > 5, rerank by relevance and take top-5
      6. If union ≤ 5, return all without reranking
    """
    if not query.strip():
        return []
    all_mems = await list_memories(db)
    if not all_mems:
        return []

    # Exclude pinned memories from retrieval (they are always injected)
    pool = [m for m in all_mems if not m.pinned]
    if not pool:
        return []

    # --- Step 2: Semantic filter (ChromaDB pre-vectorized) ---
    semantic_ids: set[str] = set()
    try:
        from app.core.memory_vector import get_memory_store

        store = await get_memory_store(db)
        if store.healthy:
            semantic_hits = store.semantic_filter(query, k=10)
            semantic_ids = {mid for mid, _ in semantic_hits}
            logger.debug("semantic filter: %d / %d", len(semantic_ids), len(pool))
    except Exception:
        pass

    # --- Step 3: Keyword filter (BM25 on pool) ---
    query_tokens = set(_content_words(query))
    if not query_tokens:
        if not semantic_ids:
            return []

    keyword_ids: set[str] = set()
    if query_tokens:
        n = len(pool)
        doc_freq: dict[str, int] = {}
        mem_tokens: dict[str, set[str]] = {}
        for m in pool:
            toks = tokenize(m.text)
            mem_tokens[m.id] = toks
            for t in toks:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        kw_candidates: list[tuple[float, Memory]] = []
        for m in pool:
            kw_raw = _bm25_score(query_tokens, mem_tokens[m.id], doc_freq, n)
            kw_norm = min(kw_raw / 6.0, 1.0) if kw_raw > 0 else 0.0

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

            if kw_norm >= 0.12:
                kw_candidates.append((kw_norm, m))

        kw_candidates.sort(key=lambda x: x[0], reverse=True)
        keyword_ids = {m.id for _, m in kw_candidates[:10]}

    # --- Step 4: Union, dedup ---
    union_ids = semantic_ids | keyword_ids
    by_id = {m.id: m for m in pool if m.id in union_ids}
    if not by_id:
        return []
    present_ids = [mid for mid in union_ids if mid in by_id]

    # --- Step 5/6: Rerank if union > 5, otherwise return as-is ---
    if len(present_ids) <= 5:
        return [by_id[mid] for mid in present_ids]

    # Rerank union by relevance
    reranked: list[str] = []
    try:
        from app.config import get_settings
        from app.core.embeddings import get_reranker_engine

        cache_dir = f"{get_settings().data_dir}/fastembed"
        reranker = get_reranker_engine(cache_dir=cache_dir)
        union_docs = [by_id[mid].text for mid in present_ids]
        scores = reranker.rerank(query, union_docs)
        indexed = sorted(zip(present_ids, scores), key=lambda x: x[1], reverse=True)
        reranked = [mid for mid, _ in indexed]
        logger.debug("reranked %d candidates", len(reranked))
    except Exception as e:
        logger.warning("Reranker failed (%s), using union order", e)
        reranked = present_ids

    return [by_id[mid] for mid in reranked[:k]]


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
    for m in await hybrid_retrieve(db, query, k=5):
        if m.id not in seen:
            selected.append((m, "recalled"))
            seen.add(m.id)
    return selected[:max_memories]


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
    "You are a memory extraction assistant. Analyze the conversation and extract "
    "ONLY durable personal facts about the user that would be useful across many "
    "future conversations.\n\n"
    "Good examples: name, job title, city, family members, long-term projects, "
    "strong preferences.\n"
    "Bad examples: what they asked about today, temporary moods, generic "
    "statements, things the assistant said, one-off tasks, opinions on the "
    "current topic.\n\n"
    "Rules:\n"
    "- Extract every durable personal fact the user revealed (usually 2–8; "
    "save generously)\n"
    "- Only extract facts the USER stated or clearly implied\n"
    "- Each fact must be a single short sentence (under 15 words)\n"
    "- If a fact is similar to something likely already known, skip it\n"
    "- If nothing durable was revealed, return []\n\n"
    "Return a JSON array of objects with 'text' and 'category' fields.\n"
    "Categories: 'identity', 'preference', 'event', 'contact', 'fact'.\n\n"
    "Return ONLY valid JSON, no markdown fences."
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
    conversation_text: str,
) -> list[dict[str, str]]:
    """Ask the model to extract memories from a conversation transcript.

    Mirrors odysseus's /api/memory/extract: analyze the entire conversation
    history, pull any factual statements / contacts / addresses / phones the
    user might want to remember, and only keep things specific and useful.
    """
    if not conversation_text.strip():
        return []
    prompt = f"Conversation history:\n{conversation_text[:12000]}\n\nExtract memories."

    async def _attempt(reasoning: bool | None) -> str:
        params = ProviderCallParams(
            model=model,
            system=_EXTRACT_SYSTEM,
            messages=[
                ChatMessage(role="user", parts=[MessagePart(type="text", text=prompt)])
            ],
            tools=[],
            max_tokens=500,
            temperature=0.2,
            reasoning=reasoning,
        )
        out = ""
        async for event in provider.stream(params):
            if event.kind == "text":
                out += event.content
        return out

    reasoning: bool | None = None
    try:
        if await provider.supports_reasoning(model):
            reasoning = False
    except Exception:
        reasoning = None

    candidates: list[bool | None] = [reasoning]
    if reasoning is not None:
        candidates.append(None)

    for reasoning_value in candidates:
        try:
            out = await _attempt(reasoning_value)
        except Exception as e:
            logger.warning("memory extraction failed (reasoning=%s): %s", reasoning_value, e)
            continue
        parsed = _parse_extraction(out)
        if parsed:
            return parsed
    return []
