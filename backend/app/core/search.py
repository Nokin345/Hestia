import asyncio
import html
import html.parser as _hp
import re
from urllib.parse import parse_qs, urlparse

import httpx

_SEARXNG_TIMEOUT = 10.0
_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_TIMEOUT = 10.0
_FETCH_TIMEOUT = 15.0
_FETCH_MAX_BYTES = 2_000_000
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "blockquote", "pre", "figure",
}

_BINARY_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
    "application/gzip",
    "application/x-gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-bzip",
    "application/x-bzip2",
    "application/x-xz",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "video/mp4",
    "video/webm",
    "audio/mpeg",
    "audio/ogg",
}


class _TextExtractor(_hp.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template", "svg", "head"):
            self._skip_depth += 1
        if self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self._out.append("\n")
        elif self._skip_depth == 0 and tag == "a":
            self._out.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template", "svg", "head"):
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def text(self) -> str:
        raw = "".join(self._out)
        lines = [ln.strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _ddg_redirect(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        uddg = query.get("uddg")
        if uddg:
            return uddg[0]
    except ValueError:
        pass
    return url


async def _search_searxng(
    client: httpx.AsyncClient, query: str, base_url: str, max_results: int
) -> list[dict]:
    resp = await client.get(
        base_url.rstrip("/") + "/search", params={"q": query, "format": "json"}
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("results") or []
    results: list[dict] = []
    for item in raw[:max_results]:
        results.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
            }
        )
    return results


async def _search_duckduckgo(
    client: httpx.AsyncClient, query: str, max_results: int
) -> list[dict]:
    resp = await client.get(
        _DDG_URL, params={"q": query}, headers={"User-Agent": _BROWSER_UA}
    )
    resp.raise_for_status()
    text = resp.text
    titles = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S
    )
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.S)
    results: list[dict] = []
    for i, (href, title) in enumerate(titles[:max_results]):
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        results.append(
            {
                "title": _strip_tags(title),
                "url": _ddg_redirect(href),
                "snippet": snippet,
            }
        )
    return results


async def search_web(
    query: str,
    searxng_url: str = "",
    max_results: int = 5,
    fallback: bool = True,
) -> dict:
    """Search the web via SearXNG, falling back to DuckDuckGo.

    Returns ``{"engine": "searxng"|"duckduckgo"|"none", "results": [...]}``.
    """
    searxng_url = (searxng_url or "").strip()
    async with httpx.AsyncClient(
        timeout=_SEARXNG_TIMEOUT, follow_redirects=True
    ) as client:
        if searxng_url:
            try:
                results = await _search_searxng(
                    client, query, searxng_url, max_results
                )
                if results:
                    return {"engine": "searxng", "results": results}
            except Exception:
                pass
        if fallback:
            try:
                results = await _search_duckduckgo(client, query, max_results)
                return {"engine": "duckduckgo", "results": results}
            except Exception:
                pass
    return {"engine": "none", "results": []}


def _classify_content_type(content_type: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    if ct in ("text/html", "application/xhtml+xml"):
        return "html"
    if ct == "application/json":
        return "json"
    if ct in ("text/plain", "text/xml", "application/xml", "text/x-yaml",
              "application/yaml", "text/yaml", "text/toml", "application/toml"):
        return "text"
    if ct in _BINARY_CONTENT_TYPES:
        return "binary"
    return "generic"


def _old_reddit(url: str) -> str:
    """Rewrite reddit.com/www.reddit.com links to old.reddit.com.

    old.reddit renders server-side HTML that the text extractor handles well;
    new reddit is a JS-heavy SPA that yields little readable content.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "reddit.com" or host.endswith(".reddit.com"):
        # old.reddit can't render new-reddit share shortlinks (/r/x/s/slug)
        if "/s/" in parsed.path:
            return url
        netloc = "old.reddit.com"
        if parsed.port:
            netloc += f":{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return url


async def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a page and return readable content.

    HTML is converted to plain text; JSON and plain/text formats are passed
    through as fenced text. Binary/media responses return ``""``. Output is
    capped at ``max_chars``.
    """
    url = _old_reddit(url)
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
    }
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type") or ""
        if _classify_content_type(ctype) == "binary":
            return ""
        content = resp.content[:_FETCH_MAX_BYTES]
    raw = content.decode("utf-8", errors="ignore")

    kind = _classify_content_type(ctype)
    if kind in ("json", "text"):
        return raw.strip()[:max_chars]

    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = parser.text()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


async def search_and_fetch(
    query: str,
    searxng_url: str = "",
    max_results: int = 5,
    fallback: bool = True,
    fetch_urls: bool = True,
    fetch_limit: int = 3,
    max_chars_per_url: int = 4000,
) -> dict:
    """Search the web and fetch readable text from the top result pages.

    Returns
    ``{"engine", "results": [{title,url,snippet}], "fetched": [{url,text}]}``.
    """
    search = await search_web(query, searxng_url, max_results, fallback)
    results = search.get("results") or []
    fetched: list[dict] = []
    if fetch_urls and results:
        urls = [r["url"] for r in results[:fetch_limit]]
        sem = asyncio.Semaphore(4)

        async def _guarded(url: str) -> dict | None:
            async with sem:
                try:
                    text = await fetch_url(url, max_chars_per_url)
                except Exception:
                    return None
                if not text.strip():
                    return None
                return {"url": url, "text": text}

        done = await asyncio.gather(*[_guarded(u) for u in urls])
        fetched = [item for item in done if item is not None]
    return {"engine": search.get("engine"), "results": results, "fetched": fetched}
