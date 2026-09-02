"""Shared BM25 scoring and keyword boost functions."""

import math
import re

STOPWORDS = frozenset(
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
    "accordingly almost anyway certainly clearly completely "
    "exactly finally firstly furthermore generally however "
    "indeed instead later likewise maybe meanwhile moreover never nevertheless now "
    "nowhere otherwise perhaps quite rather regarding secondly similarly "
    "therefore thus wherever whichever "
    "basically literally obviously technically essentially "
    "that's there's here's what's who's how's let's can't".split()
)


def tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase alphanumeric words with simple stemming."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {stem(w) for w in words}


def stem(word: str) -> str:
    """Simple suffix-stripping stemmer.

    Strips common English suffixes: es, s, ed, ing, ly, tion, sion, ment, ness.
    Order matters: longer suffixes stripped first.
    """
    # Protect very short words
    if len(word) <= 2:
        return word
    
    # Strip suffixes in order (longest first)
    for suffix in ["tion", "sion", "ment", "ness", "ing", "ed", "es", "s", "e", "ly"]:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[: -len(suffix)]
            break
    
    return word


def content_words(text: str) -> list[str]:
    """Meaningful content words with stopwords removed and stemmed."""
    tokens = tokenize(text)
    return [t for t in tokens if t not in STOPWORDS]


def has_content_words(text: str) -> bool:
    """True if text has any meaningful words (not just greetings/filler)."""
    return bool(content_words(text))


def bm25_score(query_tokens, doc_tokens, df, n):
    """BM25 scoring algorithm.

    Args:
        query_tokens: set of query tokens
        doc_tokens: set of document tokens
        df: dictionary of document frequencies (token -> count)
        n: total number of documents

    Returns:
        BM25 score
    """
    if not doc_tokens or not query_tokens:
        return 0.0
    avg_len = max(sum(len(s) for s in df) / n, 1)
    k1, b = 1.5, 0.75
    score = 0.0
    for token in query_tokens:
        if token not in doc_tokens:
            continue
        doc_freq = df.get(token, 0)
        idf = math.log((n - doc_freq + 0.5) / (doc_freq + 0.5) + 1)
        doc_len = len(doc_tokens)
        tf_norm = (1 * (k1 + 1)) / (1 + k1 * (1 - b + b * doc_len / avg_len))
        score += idf * tf_norm
    return score


def keyword_boost(query: str, text: str, kw_norm: float) -> float:
    """Apply exact-match boost to keyword score."""
    if query.lower() in text.lower():
        kw_norm = max(kw_norm, 0.8)
    return kw_norm


def text_similarity(text1: str, text2: str) -> float:
    """Jaccard similarity between two texts."""
    t1 = tokenize(text1)
    t2 = tokenize(text2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)
