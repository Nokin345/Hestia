import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mcp import (
    invalidate_mcp_cache,
    list_all_mcp_tools,
    list_mcp_tools,
    test_mcp_server,
)
from app.db import get_db
from app.models import McpServer
from app.schemas.mcp import (
    McpServerCreate,
    McpServerOut,
    McpServerTestRequest,
    McpServerTestResult,
    McpServerUpdate,
    McpToolOut,
)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _missing() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found"
    )


def _serialize_headers(headers):
    return json.dumps(
        [{"key": h.key, "value": h.value} for h in headers], ensure_ascii=False
    )


def _serialize_disabled_tools(tools: list[str]) -> str:
    return json.dumps(tools, ensure_ascii=False)


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(McpServer).order_by(McpServer.name))
    return list(res.scalars().all())


@router.post("/servers", response_model=McpServerOut, status_code=201)
async def create_server(body: McpServerCreate, db: AsyncSession = Depends(get_db)):
    server = McpServer(
        name=body.name.strip(),
        transport=body.transport,
        url=body.url.strip().rstrip("/"),
        auth_token=body.auth_token or "",
        headers_json=_serialize_headers(body.headers),
        disabled_tools_json=_serialize_disabled_tools(body.disabled_tools),
        enabled=body.enabled,
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


@router.patch("/servers/{server_id}", response_model=McpServerOut)
async def patch_server(
    server_id: str, body: McpServerUpdate, db: AsyncSession = Depends(get_db)
):
    server = await db.get(McpServer, server_id)
    if server is None:
        raise _missing()
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        server.name = data["name"].strip()
    if "transport" in data:
        server.transport = data["transport"]
    if "url" in data:
        server.url = data["url"].strip().rstrip("/")
    if "auth_token" in data:
        server.auth_token = data["auth_token"] or ""
    if "headers" in data:
        server.headers_json = _serialize_headers(data["headers"])
    if "disabled_tools" in data:
        server.disabled_tools_json = _serialize_disabled_tools(data["disabled_tools"])
    if "enabled" in data:
        server.enabled = data["enabled"]
    invalidate_mcp_cache(server_id)
    await db.commit()
    await db.refresh(server)
    return server


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: str, db: AsyncSession = Depends(get_db)):
    server = await db.get(McpServer, server_id)
    if server is None:
        raise _missing()
    await db.delete(server)
    invalidate_mcp_cache(server_id)
    await db.commit()


@router.get("/tools", response_model=list[McpToolOut])
async def list_all_tools(
    server_ids: str | None = None, db: AsyncSession = Depends(get_db)
):
    ids = [i for i in (server_ids or "").split(",") if i] or None
    return await list_all_mcp_tools(db, ids)


@router.post("/servers/{server_id}/test", response_model=McpServerTestResult)
async def test_saved_server(server_id: str, db: AsyncSession = Depends(get_db)):
    server = await db.get(McpServer, server_id)
    if server is None:
        raise _missing()
    try:
        tools = await list_mcp_tools(server)
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
        tools=tools,
    )


@router.get("/servers/{server_id}/tools", response_model=list[McpToolOut])
async def list_server_tools(server_id: str, db: AsyncSession = Depends(get_db)):
    server = await db.get(McpServer, server_id)
    if server is None:
        raise _missing()
    try:
        return await list_mcp_tools(server)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list tools: {exc}",
        )


@router.post("/test", response_model=McpServerTestResult)
async def test_unsaved_config(body: McpServerTestRequest):
    return await test_mcp_server(
        body.transport,
        body.url.strip().rstrip("/"),
        body.auth_token or "",
        [{"key": h.key, "value": h.value} for h in body.headers],
    )
