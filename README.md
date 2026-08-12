# Hestia

A self-hosted, local-first AI chat assistant with retrieval-augmented generation (RAG), long-term memory, web search, sandboxed code execution, and MCP tool support. The frontend and API ship in a single container.

## Features

- **Local-first LLMs** — built around [Ollama](https://ollama.com) and [llama.cpp](https://github.com/ggml-org/llama.cpp) as first-class providers, so models run on your own hardware. No API keys required.
- **Cloud models when you want them** — add OpenRouter (a single key covers hundreds of models) or any OpenAI-compatible endpoint (OpenAI, vLLM, GPUStack, Together, llama.cpp servers). Switch providers and models per conversation.
- **Knowledge base (RAG)** — upload documents (PDF, Markdown, plain text, CSV, JSON, XML) into a per-document knowledge base; enable KB retrieval per conversation to ground answers in your own content.
- **Long-term memory** — the assistant auto-extracts and stores facts, preferences, and user details between conversations, retrieves the relevant ones, and can recall memories on demand.
- **Web search** — SearXNG-backed search with DuckDuckGo fallback, including page content fetching as context.
- **Sandboxed code execution** — Python 3.12 in an ephemeral, network-isolated Docker container. The model can run code for precise calculations; files written under `/workspace` persist within a conversation.
- **MCP tool servers** — connect external MCP servers (HTTP transport) and the model can call their tools; toggled per conversation.
- **Semantic embeddings** — local `fastembed` (ONNX, zero-config) or an OpenAI-compatible remote endpoint (llama.cpp, vLLM, Ollama, GPUStack); used for both KB and memory retrieval.
- **Per-conversation toggles** — independently enable/disable KB, memory, web search, code execution, and reasoning for each chat.
- **System prompt presets & defaults** — set a default model and default conversation toggles.

## Providers

Hestia is local-first: the defaults assume models served by **Ollama** or **llama.cpp** on your own machine or LAN.

| Provider type | Default base URL | Key? | Use for |
|---|---|---|---|
| `ollama` | `http://localhost:11434` | no | Local models via Ollama |
| `llamacpp` | `http://localhost:8080/v1` | optional | Local models via a llama.cpp server |
| `openrouter` | `https://openrouter.ai/api/v1` | yes | One key, many cloud models |
| `openai_compat` | (required) | optional | Any OpenAI-compatible endpoint: OpenAI, vLLM, GPUStack, Together, local proxies, etc. |

If your Ollama/llama.cpp server runs on another machine (e.g. a GPU box on your LAN), just set the base URL to that host. No changes to Hestia needed.

## Quick start (self-hosted)

Requirements: Docker with Docker Compose, and the `docker` socket exposed to the sandbox service for isolated code execution.

```bash
git clone https://github.com/Nokin345/Hestia.git
cd Hestia

cp .env.example .env
# edit .env: set AUTH_USERNAME / AUTH_PASSWORD / APP_SECRET

docker compose up -d --build
```

Open http://localhost:8080 and log in with the credentials from `.env`. Defaults are `admin` / `change-me` — change them before exposing the instance.

### Point it at your local models

1. In **Settings → Providers**, add an `ollama` provider (default `http://localhost:11434`) or a `llamacpp` provider (default `http://localhost:8080/v1`).
2. The model picker will list the models served by that endpoint.
3. Set a **default model** in Settings → Defaults.

> `localhost` inside the Hestia container refers to the container itself. If your model server runs on the host or another machine, use its host IP or a Docker-network name (e.g. `http://192.168.1.10:11434`).

### Optional: embeddings and search

The SearXNG URL and embedding URL in `.env` are auto-provisioned exactly as if entered in Settings. They do not disable fallbacks — DuckDuckGo is used if SearXNG is unset or unreachable, and local fastembed (CPU) is used if no embedding URL is set or the remote endpoint fails.

```bash
# .env
SEARXNG_URL=http://your-searxng-host:8080
EMBEDDING_URL=http://your-embed-server:8080/v1/embeddings   # llama.cpp, vLLM, Ollama, GPUStack
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_API_KEY=
```

### Configuration (`docker-compose.yml` / `.env`)

| Variable | Default | Purpose |
|---|---|---|
| `WEB_PORT` | `8080` | Host port for the UI + API (single container) |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | `admin` / `change-me` | Shared team login |
| `APP_SECRET` | — | Signing key for session cookies; use a long random string |
| `TZ` | `UTC` | Timezone injected into the system prompt |
| `SEARXNG_URL` | empty | Optional SearXNG instance for web search |
| `EMBEDDING_URL` | empty | Optional remote embeddings endpoint (OpenAI-compatible) |
| `EMBEDDING_MODEL` | empty | Remote embedding model; server default if empty |
| `EMBEDDING_API_KEY` | empty | Bearer token for the remote embeddings endpoint |

### Persistent data

- **Database, Chroma vectors, and fastembed cache** live under `/app/data` in the named volume `backend_data` (created automatically).
- **Uploads** are stored on the host at `./uploads` (configurable via `UPLOAD_DIR`).
- **Sandbox workspaces** live in per-conversation Docker volumes (`hestia-sandbox-*`, created automatically), so executed files and their outputs persist across turns in the same conversation.

```bash
# backups
docker run --rm -v hestia_backend_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/hestia-data-$(date +%Y%m%d_%H%M%S).tar.gz -C /data .
```

## Configuration in Settings

1. **Providers** — add an Ollama or llama.cpp provider (local-first), or OpenRouter / any OpenAI-compatible endpoint. The model picker lists each provider's models.
2. **Defaults** — set the default model and default conversation toggles.
3. **Search** — SearXNG URL, max results, DuckDuckGo fallback, page fetching.
4. **Memory embeddings** — remote endpoint + model, or leave empty for local fastembed.
5. **System prompts** — manage presets and the applied default system prompt.
6. **MCP** — add HTTP MCP servers; tools appear in new conversations.

## Development

- `backend/` — Python 3.12, FastAPI, SQLAlchemy (async), ChromaDB, pydantic-settings.
- `frontend/` — React + Vite + TypeScript + Tailwind CSS.

```bash
# backend
cd backend && python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/uvicorn app.main:app --reload

# frontend (dev server proxies /api to :8000)
cd frontend && npm install && npm run dev
```

The production `Dockerfile` is multi-stage: builds the frontend, then packages both the API and static assets into a single Python image.

## License

MIT © 2026 Nokin345
