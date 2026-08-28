import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpServer
from app.schemas.mcp import McpServerTestResult, McpToolOut

logger = logging.getLogger(__name__)

_TOOL_CACHE_TTL = 60.0
_tool_cache: dict[str, tuple[float, list[McpToolOut]]] = {}


def _headers_dict(
    auth_token: str, headers: list[dict[str, str]] | list | None
) -> dict[str, str]:
    out: dict[str, str] = {}
    if auth_token:
        out["Authorization"] = f"Bearer {auth_token}"
    for h in headers or []:
        key = (h.get("key") if isinstance(h, dict) else None) or ""
        value = (h.get("value") if isinstance(h, dict) else None) or ""
        if key:
            out[str(key)] = str(value)
    return out


def _headers_for(server: McpServer) -> dict[str, str]:
    try:
        pairs = json.loads(server.headers_json or "[]")
    except (json.JSONDecodeError, TypeError):
        pairs = []
    return _headers_dict(server.auth_token, pairs)


def _cache_key(server: McpServer) -> str:
    return f"{server.id}:{server.url}:{server.transport}"


def invalidate_mcp_cache(server_id: str | None = None) -> None:
    if server_id is None:
        _tool_cache.clear()
        return
    for key in [k for k in _tool_cache if k.startswith(f"{server_id}:")]:
        _tool_cache.pop(key, None)


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in (schema or {}).items() if k not in ("$schema", "title")}
    if out.get("type") != "object":
        out = {"type": "object", "properties": out.get("properties", {})}
    return out


async def _run_session(
    transport: str, url: str, headers: dict[str, str], fn: Callable[[Any], Any]
) -> Any:
    from mcp import ClientSession

    async def inner(read, write) -> Any:
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)

    if transport == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(url, headers=headers) as (read, write):
            return await inner(read, write)

    import httpx
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30, read=300),
        follow_redirects=True,
    ) as http_client, streamable_http_client(
        url, http_client=http_client
    ) as streams:
        read, write, _ = streams
        return await inner(read, write)


def _serialize_content(result: Any) -> str:
    chunks: list[str] = []
    for item in getattr(result, "content", None) or []:
        t = getattr(item, "type", None)
        if t == "text":
            text = getattr(item, "text", "")
            if text:
                chunks.append(text)
        elif t in ("image", "audio"):
            mime = getattr(item, "mimeType", "") or getattr(item, "mime_type", "")
            data = getattr(item, "data", None) or getattr(item, "blob", None)
            if data is not None:
                s = str(data)
                if len(s) > 4000:
                    s = s[:4000] + f"... (truncated, {len(s)} chars)"
                chunks.append(f"[{t}: {mime}]\n{s}")
            else:
                chunks.append(f"[{t}: {mime}]")
        elif t == "resource":
            uri = getattr(item, "uri", "")
            text = getattr(item, "text", None)
            if text:
                chunks.append(f"[resource: {uri}]\n{text}")
            else:
                chunks.append(f"[resource: {uri}]")
        else:
            chunks.append(str(item))
    text = "\n\n".join(c for c in chunks if c)
    if text:
        return text
    sc = getattr(result, "structuredContent", None)
    if sc is not None:
        return json.dumps(sc, ensure_ascii=False, default=str)
    return "(no output)"


def _to_tool_out(t: Any, server_name: str = "") -> McpToolOut:
    name = getattr(t, "name", "")
    return McpToolOut(
        name=f"{server_name}.{name}" if server_name else name,
        server=server_name,
        raw_name=name,
        description=getattr(t, "description", "") or "",
        input_schema=_sanitize_schema(getattr(t, "inputSchema", None) or {}),
    )


async def list_mcp_tools(server: McpServer) -> list[McpToolOut]:
    key = _cache_key(server)
    cached = _tool_cache.get(key)
    if cached and (time.monotonic() - cached[0]) < _TOOL_CACHE_TTL:
        return cached[1]

    async def do(session: Any) -> list[Any]:
        tools: list[Any] = []
        cursor: str | None = None
        while True:
            res = await session.list_tools(cursor=cursor)
            tools.extend(res.tools)
            cursor = res.nextCursor
            if not cursor:
                break
        return tools

    tools = await asyncio.wait_for(
        _run_session(server.transport, server.url, _headers_for(server), do),
        timeout=45,
    )
    out = [_to_tool_out(t, server.name) for t in tools]
    _tool_cache[key] = (time.monotonic(), out)
    return out


async def list_all_mcp_tools(
    db: AsyncSession,
    server_ids: list[str] | None = None,
    tool_names: list[str] | None = None,
) -> list[McpToolOut]:
    stmt = select(McpServer).where(McpServer.enabled.is_(True))
    if server_ids:
        stmt = stmt.where(McpServer.id.in_(server_ids))
    stmt = stmt.order_by(McpServer.name)
    res = await db.execute(stmt)
    servers = list(res.scalars().all())
    results: list[McpToolOut] = []
    for server in servers:
        try:
            results.extend(await list_mcp_tools(server))
        except Exception as exc:
            logger.warning("MCP: failed to list tools for '%s': %s", server.name, exc)
    if tool_names:
        wanted = set(tool_names)
        results = [t for t in results if t.name in wanted]
    return results


async def call_mcp_tool(
    server: McpServer, tool_name: str, arguments: dict[str, Any]
) -> tuple[bool, str]:
    async def do(session: Any) -> Any:
        return await session.call_tool(tool_name, arguments=arguments)

    try:
        result = await asyncio.wait_for(
            _run_session(server.transport, server.url, _headers_for(server), do),
            timeout=180,
        )
    except TimeoutError:
        return False, f"{server.name}.{tool_name}: MCP call timed out after 180s"
    except Exception as exc:
        return False, f"{server.name}.{tool_name}: {exc}"
    if getattr(result, "isError", False):
        return False, _serialize_content(result)
    return True, _serialize_content(result)


async def get_mcp_server_by_prefix(db: AsyncSession, prefix: str) -> McpServer | None:
    res = await db.execute(
        select(McpServer)
        .where(McpServer.enabled.is_(True), McpServer.name == prefix)
        .limit(1)
    )
    return res.scalars().first()


async def test_mcp_server(
    transport: str, url: str, auth_token: str, headers: list[dict[str, str]]
) -> McpServerTestResult:
    async def do(session: Any) -> list[Any]:
        tools: list[Any] = []
        cursor: str | None = None
        while True:
            res = await session.list_tools(cursor=cursor)
            tools.extend(res.tools)
            cursor = res.nextCursor
            if not cursor:
                break
        return tools

    try:
        tools = await asyncio.wait_for(
            _run_session(transport, url, _headers_dict(auth_token, headers), do),
            timeout=45,
        )
    except Exception as exc:
        return McpServerTestResult(
            ok=False, message=f"Connection failed: {exc}", tools=[]
        )
    if not tools:
        return McpServerTestResult(
            ok=True, message="Connected, but the server exposed no tools.", tools=[]
        )
    return McpServerTestResult(
        ok=True,
        message=f"Connected — {len(tools)} tool(s) available.",
        tools=[_to_tool_out(t) for t in tools],
    )
