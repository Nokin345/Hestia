from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class SandboxRunRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    conversation_id: str = ""
    timeout: int | None = None
    env: dict[str, str] = Field(default_factory=dict)


class SandboxRunResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False


@router.get("/health")
async def sandbox_health() -> dict:
    import httpx

    url = f"{get_settings().code_exec_url}/health"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(url)
        res.raise_for_status()
        return res.json()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.post("/run", response_model=SandboxRunResult)
async def sandbox_run(body: SandboxRunRequest) -> SandboxRunResult:
    import httpx

    url = f"{get_settings().code_exec_url}/api/run"
    try:
        async with httpx.AsyncClient(timeout=310) as client:
            res = await client.post(url, json=body.model_dump())
        res.raise_for_status()
        return SandboxRunResult(**res.json())
    except httpx.TimeoutException:
        return SandboxRunResult(
            stdout="",
            stderr="Execution timed out",
            exit_code=124,
            timed_out=True,
        )
    except Exception as exc:
        return SandboxRunResult(
            stdout="",
            stderr=f"sandbox error: {exc}",
            exit_code=1,
        )
