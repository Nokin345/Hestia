import logging
import os
import re
import tempfile

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox")

app = FastAPI(title="Hestia sandbox", version="0.1.0")

RUN_IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
DEFAULT_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "60"))
MEM_LIMIT = os.environ.get("SANDBOX_MEM", "512m")
NANOCPUS = int(os.environ.get("SANDBOX_CPUS", "1000000000"))
VOLUME_PREFIX = "hestia-sandbox"
CODE_DIR = os.environ.get("SANDBOX_CODE_DIR", "/var/lib/sandbox")
HOST_CODE_DIR = os.environ.get("SANDBOX_HOST_DIR", CODE_DIR)

_client = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


_VOLUME_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}$")


def _volume_name(conversation_id: str) -> str:
    safe = re.sub(r"[^a-z0-9_.-]", "", conversation_id.lower())[:80]
    if not _VOLUME_SAFE.match(safe):
        safe = "default"
    return f"{VOLUME_PREFIX}-{safe}"


class RunRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    conversation_id: str = ""
    timeout: int | None = None
    env: dict[str, str] = Field(default_factory=dict)


class RunResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/run", response_model=RunResult)
async def run(body: RunRequest) -> RunResult:
    timeout = min(body.timeout or DEFAULT_TIMEOUT, 300)
    c = client()
    try:
        vol = c.volumes.get(_volume_name(body.conversation_id))
    except docker.errors.NotFound:
        vol = c.volumes.create(_volume_name(body.conversation_id))

    # Persist the submitted code into the conversation's workspace volume, then
    # run it so the file (and anything it produces) survives across turns.
    # The code tempfile lives in a host-backed dir (CODE_DIR), so we bind-mount
    # it into the child container using its host path (HOST_CODE_DIR).
    os.makedirs(CODE_DIR, exist_ok=True)
    container_path = None
    try:
        fd, container_path = tempfile.mkstemp(
            dir=CODE_DIR, suffix=".py", prefix="sbx-"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body.code.replace("\r\n", "\n"))
        host_file = os.path.join(HOST_CODE_DIR, os.path.basename(container_path))

        command = "cp /code/main.py /workspace/main.py && python3 /workspace/main.py"
        kwargs = dict(
            image=RUN_IMAGE,
            detach=True,
            remove=True,
            working_dir="/workspace",
            volumes={
                vol.name: {"bind": "/workspace", "mode": "rw"},
                host_file: {"bind": "/code/main.py", "mode": "ro"},
            },
            network_mode="none",
            mem_limit=MEM_LIMIT,
            nano_cpus=NANOCPUS,
            environment=body.env or None,
            command=["sh", "-c", command],
        )
        try:
            container = c.containers.run(**kwargs)
        except docker.errors.ImageNotFound:
            c.images.pull(RUN_IMAGE)
            container = c.containers.run(**kwargs)
        except docker.errors.DockerException as e:
            raise HTTPException(status_code=503, detail=f"sandbox engine error: {e}")
    finally:
        try:
            if container_path:
                os.unlink(container_path)
        except OSError:
            pass

    timed_out = False
    exit_code = 0
    try:
        res = container.wait(timeout=timeout)
        exit_code = res.get("StatusCode", 0) if isinstance(res, dict) else res or 0
    except (docker.errors.NotFound, TypeError, docker.errors.APIError):
        timed_out = True
        exit_code = 124
        try:
            container.kill()
            container.wait(timeout=10)
        except Exception:
            pass
    except Exception:
        timed_out = True
        exit_code = 124
        try:
            container.kill()
        except Exception:
            pass

    logs = ""
    try:
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
    except Exception:
        pass

    try:
        container.remove(force=True)
    except Exception:
        pass

    if timed_out:
        return RunResult(
            stdout="",
            stderr=logs or "Execution timed out",
            exit_code=124,
            timed_out=True,
        )
    return RunResult(stdout=logs, exit_code=exit_code)