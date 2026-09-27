# AI SEO Master Agent

An autonomous SEO manager: On-Page HTML optimization, Off-Page link-building
prospecting, GMB (Google Business Profile) updates, content repurposing, and
geo/programmatic SEO copy — with a Multi-LLM gateway (OpenAI, Anthropic,
Gemini, GLM, local Ollama).

- **Backend:** FastAPI (Python), LiteLLM, SQLAlchemy async (SQLite default, Postgres supported)
- **Frontend:** Next.js (React, Tailwind) — talks to the backend over `X-API-Key`
- **Auth:** all `/api/*` endpoints require the `X-API-Key` header (shared secret from `SEO_API_KEY`)

## Run locally (backend)

```bash
cp .env.example .env
# generate a secret:  python -c "import secrets; print(secrets.token_hex(32))"
# then set SEO_API_KEY in .env to it
pip install -r backend/requirements.txt
uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

Health check: `curl localhost:8000/health` → `{"status":"ok"}`

Authenticated call example:

```bash
curl -X POST localhost:8000/api/execute \
  -H "Content-Type: application/json" -H "X-API-Key: $SEO_API_KEY" \
  -d '{"task_type":"geo","inputs":{"city":"Chennai","service":"Dentist"},"model_id":"gpt-4o"}'
# -> {"status":"success","task_id":"..."}
curl -H "X-API-Key: $SEO_API_KEY" localhost:8000/api/tasks/<task_id>
```

Run the smoke test (boots the server itself, no manual setup):

```bash
python tests/smoke_test.py
```

## Run locally (frontend)

```bash
cd frontend
cp .env.example .env.local   # set NEXT_PUBLIC_API_URL
npm install
npm run dev
```

## Environment variables (backend)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SEO_API_KEY` | **yes** | — | Shared-secret API key; every `/api/*` call sends it as `X-API-Key`. Server refuses to boot without it. |
| `OPENAI_API_KEY` | no | `dummy` | LLM key fallback when the request doesn't carry `X-OpenAI-Key` |
| `ANTHROPIC_API_KEY` | no | `dummy` | Fallback for `X-Anthropic-Key` |
| `GEMINI_API_KEY` | no | `dummy` | Fallback for `X-Gemini-Key` |
| `ZHIPUAI_API_KEY` | no | `dummy` | Fallback for `X-GLM-Key` |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434` | Used when `model_id` starts with `ollama` |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./seo.db` | e.g. `postgresql+asyncpg://user:pass@host:5432/seo` (needs `asyncpg`) |
| `CORS_ORIGINS` | no | (empty = no CORS) | Comma-separated browser origins, e.g. `https://app.example.com`. Never `*` with credentials. |
| `HTTP_TIMEOUT_SECONDS` | no | `15` | Timeout when fetching a client website |
| `MAX_HTML_CHARS` | no | `10000` | Max HTML characters sent to the LLM |
| `PORT` | no | `8000` | Uvicorn listen port |

Frontend `.env.local`: `NEXT_PUBLIC_API_URL` (e.g. `https://seo-api.example.com`).

## Deploy on Render (backend)

1. New Web Service → connect this repo, root directory: (repo root).
2. Environment: `Docker` (the included `Dockerfile` builds the backend).
3. Set env vars: `SEO_API_KEY` (generate a random secret), the LLM keys you use, `CORS_ORIGINS` (your frontend URL).
4. Deploy. Render health-checks `/health` automatically (path: `/health`).

## API reference

- `GET /health` — public, returns `{"status":"ok"}`
- `POST /api/execute` — enqueue an SEO job. Body: `task_type` (`onpage|offpage|gmb|content|geo`), `inputs` (per-task required fields, URLs must be http(s)), `model_id` (prefix `gpt|claude|gemini|zhipu|glm|ollama`). Optional per-request LLM keys as `X-OpenAI-Key` / `X-Anthropic-Key` / `X-Gemini-Key` / `X-GLM-Key` headers (in-memory only, never stored).
- `GET /api/tasks/{task_id}` — job status (`pending|running|success|error`) + result JSON
- `POST /api/settings/keys` — store per-workspace LLM keys in the local DB (self-host convenience; prefer env vars in production)

All errors are structured JSON: `{"error": {"code": "...", "message": "..."}}` — never stack traces.

## Security notes

- Never commit `.env` (gitignored). `.env.example` ships with dummy placeholders only.
- `POST /api/settings/keys` stores keys in local SQLite — demo/self-host convenience, not a secrets manager.
- The website fetcher blocks non-public targets (SSRF guard): private/loopback hosts are refused.
