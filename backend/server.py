"""
AI SEO Master Agent — FastAPI backend (production-hardened).

Environment-driven configuration only: see .env.example for every variable.
No hardcoded secrets, URLs, or credentials in this file.
"""
import os
import uuid
import json
import secrets
import asyncio
import ipaddress
import socket
from typing import Literal, Optional, Dict, Any
from urllib.parse import urlparse
from contextlib import asynccontextmanager

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Depends, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
import litellm

from backend.database import engine, Base, SessionLocal, get_db
from backend.models import Setting, ExecutionLog

load_dotenv()

# ---------------------------------------------------------------------------
# Config (env-only; no defaults that carry secrets)
# ---------------------------------------------------------------------------
SEO_API_KEY = os.environ.get("SEO_API_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "15"))
MAX_HTML_CHARS = int(os.environ.get("MAX_HTML_CHARS", "10000"))
TASK_TYPES = ("onpage", "offpage", "gmb", "content", "geo")

REQUIRED_INPUTS = {
    "onpage": ("url", "keyword"),
    "offpage": ("niche",),
    "gmb": ("business_name", "services"),
    "content": ("blog_url",),
    "geo": ("city", "service"),
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not SEO_API_KEY:
        raise RuntimeError(
            "SEO_API_KEY is not set. Copy .env.example to .env and set a strong "
            "random value (e.g. `python -c 'import secrets;print(secrets.token_hex(32))'`)."
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title="AI SEO Master Agent",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,   # never "*" on credentialed endpoints
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    )
# else: no CORS at all (same-origin / server-to-server only)

# ---------------------------------------------------------------------------
# Structured errors — never leak stack traces to clients
# ---------------------------------------------------------------------------
def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Server-side log only; client sees a generic message.
    print(f"Unhandled error on {request.method} {request.url.path}: {type(exc).__name__}")
    return error_response(500, "internal_error", "Unexpected server error.")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(x) for x in e["loc"][1:]) or "body", "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Invalid request.", "details": details}},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return error_response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

# ---------------------------------------------------------------------------
# Auth — shared-secret API key on all /api/* endpoints
# ---------------------------------------------------------------------------
async def require_api_key(request: Request) -> None:
    provided = request.headers.get("X-API-Key", "")
    if not provided or not secrets.compare_digest(provided, SEO_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")

# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# SEO work
# ---------------------------------------------------------------------------
def is_private_url(url: str) -> bool:
    """Block SSRF: refuse non-http(s) schemes and private/loopback targets."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return True
        host = parsed.hostname or ""
        ip = socket.gethostbyname(host)
        return ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback
    except Exception:
        return True

async def fetch_website(url: str) -> str:
    if not url or is_private_url(url):
        return f"Failed to fetch {url}: blocked (non-public or invalid URL)"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for script in soup(["script", "style"]):
                script.extract()
            return soup.prettify()[:MAX_HTML_CHARS]
    except Exception as e:
        return f"Failed to fetch {url}: {type(e).__name__}"

def get_system_prompt(task_type: str) -> str:
    prompts = {
        "onpage": "You are an On-Page SEO Expert. Analyze the provided HTML and target keyword. Output ONLY a raw JSON object with keys: 'optimized_title', 'optimized_meta_description', 'h1_suggestion', 'keyword_density_analysis', 'content_recommendations'. No markdown fences.",
        "offpage": "You are an Off-Page SEO Link Building Expert. Output ONLY a raw JSON object with keys: 'target_domains_to_prospect' (array of types of sites), 'outreach_email_subject', 'outreach_email_body', 'follow_up_email'. No markdown fences.",
        "gmb": "You are a Google My Business (GMB) SEO Expert. Output ONLY a raw JSON object with keys: 'optimized_business_description', 'qa_pairs' (array of 5 Q&A objects with 'q' and 'a'), 'update_posts' (array of 3 short posts). No markdown fences.",
        "content": "You are a Social Media Content SEO Expert. Re-purpose the provided blog post into native social content optimized for semantic search. Output ONLY a raw JSON object with keys: 'twitter_thread' (array of tweets), 'linkedin_article', 'facebook_post'. No markdown fences.",
        "geo": "You are a Local Geo-SEO Expert (Programmatic SEO). Generate hyper-local landing page copy for the given City and Service. Output ONLY a raw JSON object with keys: 'geo_title', 'geo_meta_description', 'local_landmarks_to_mention' (array), 'localized_body_copy' (2 paragraphs). No markdown fences.",
    }
    return prompts.get(task_type, "You are an SEO AI.")

def resolve_llm_config(model_id: str, per_request_keys: Dict[str, Optional[str]]):
    """Pick provider credentials. Per-request headers win; env is the fallback.
    Per-request LLM keys are used only in-memory and never persisted."""
    if model_id.startswith("gpt"):
        key = per_request_keys.get("openai") or os.getenv("OPENAI_API_KEY")
        return model_id, key, None
    if model_id.startswith("claude"):
        key = per_request_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")
        return model_id, key, None
    if model_id.startswith("gemini"):
        key = per_request_keys.get("gemini") or os.getenv("GEMINI_API_KEY")
        return model_id, key, None
    if model_id.startswith(("zhipu", "glm")):
        key = per_request_keys.get("glm") or os.getenv("ZHIPUAI_API_KEY")
        return model_id, key, None
    if model_id.startswith("ollama"):
        return model_id, None, OLLAMA_BASE_URL
    return model_id, None, None

async def process_seo_job(task_id: str, task_type: str, inputs_json: str, model_id: str, per_request_keys: dict):
    async with SessionLocal() as db:
        try:
            result = await db.execute(select(ExecutionLog).where(ExecutionLog.task_id == task_id))
            log = result.scalar_one()
            log.status = "running"
            await db.commit()

            inputs = json.loads(inputs_json)
            user_prompt = ""

            if task_type == "onpage":
                html = await fetch_website(inputs.get("url", ""))
                user_prompt = f"Target Keyword: {inputs.get('keyword')}\n\nURL HTML:\n{html}"
            elif task_type == "offpage":
                user_prompt = f"My Brand/Niche: {inputs.get('niche')}"
            elif task_type == "gmb":
                user_prompt = f"Business Name: {inputs.get('business_name')}\nServices: {inputs.get('services')}"
            elif task_type == "content":
                html = await fetch_website(inputs.get("blog_url", ""))
                user_prompt = f"Blog Post Content:\n{html}"
            elif task_type == "geo":
                user_prompt = f"City/Location: {inputs.get('city')}\nService Offered: {inputs.get('service')}"

            system_prompt = get_system_prompt(task_type)
            model, api_key, api_base = resolve_llm_config(model_id, per_request_keys)

            if not api_key and not api_base:
                raise RuntimeError(f"No API key configured for model '{model_id}'")

            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                api_key=api_key,
                api_base=api_base,
                max_tokens=3000,
            )

            raw_text = response.choices[0].message.content.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            result_data = json.loads(raw_text)

            log.result_json = json.dumps(result_data)
            log.status = "success"
            await db.commit()

        except Exception as e:
            # Server-side log only; DB records a safe error string (no traceback).
            print(f"Error processing SEO job {task_id}: {type(e).__name__}")
            result = await db.execute(select(ExecutionLog).where(ExecutionLog.task_id == task_id))
            log = result.scalar_one_or_none()
            if log:
                log.status = "error"
                log.result_json = json.dumps({"error": f"{type(e).__name__}"})
                await db.commit()

# ---------------------------------------------------------------------------
# Request models with validation
# ---------------------------------------------------------------------------
class ExecuteRequest(BaseModel):
    task_type: Literal["onpage", "offpage", "gmb", "content", "geo"]
    inputs: Dict[str, Any] = Field(..., max_length=50)
    model_id: str = Field(..., min_length=1, max_length=120)

    @field_validator("inputs")
    @classmethod
    def check_inputs(cls, v: Dict[str, Any], info):
        task_type = info.data.get("task_type")
        required = REQUIRED_INPUTS.get(task_type, ())
        missing = [k for k in required if not str(v.get(k, "")).strip()]
        if missing:
            raise ValueError(f"missing required input(s) for '{task_type}': {', '.join(missing)}")
        for key in ("url", "blog_url"):
            if key in v and v[key]:
                parsed = urlparse(str(v[key]))
                if parsed.scheme not in ("http", "https"):
                    raise ValueError(f"'{key}' must be a valid http(s) URL")
        return v

    @field_validator("model_id")
    @classmethod
    def check_model(cls, v: str):
        prefixes = ("gpt", "claude", "gemini", "zhipu", "glm", "ollama")
        if not v.startswith(prefixes):
            raise ValueError(f"model_id must start with one of {prefixes}")
        return v

class ApiKeysUpdate(BaseModel):
    openai_api_key: Optional[str] = Field(default=None, max_length=500)
    anthropic_api_key: Optional[str] = Field(default=None, max_length=500)
    gemini_api_key: Optional[str] = Field(default=None, max_length=500)
    glm_api_key: Optional[str] = Field(default=None, max_length=500)

# ---------------------------------------------------------------------------
# Protected API routes
# ---------------------------------------------------------------------------
@app.post("/api/execute", dependencies=[Depends(require_api_key)])
async def enqueue_task(req: ExecuteRequest, background_tasks: BackgroundTasks, request: Request, db: AsyncSession = Depends(get_db)):
    task_id = str(uuid.uuid4())

    log = ExecutionLog(
        task_id=task_id,
        task_type=req.task_type,
        inputs_json=json.dumps(req.inputs),
        model_provider=req.model_id,
        status="pending",
    )
    db.add(log)
    await db.commit()

    # Per-request LLM keys travel only in headers and in-memory; never persisted.
    per_request_keys = {
        "openai": request.headers.get("X-OpenAI-Key"),
        "anthropic": request.headers.get("X-Anthropic-Key"),
        "gemini": request.headers.get("X-Gemini-Key"),
        "glm": request.headers.get("X-GLM-Key"),
    }

    background_tasks.add_task(process_seo_job, task_id, req.task_type, json.dumps(req.inputs), req.model_id, per_request_keys)

    return {"status": "success", "task_id": task_id}

@app.get("/api/tasks/{task_id}", dependencies=[Depends(require_api_key)])
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExecutionLog).where(ExecutionLog.task_id == task_id))
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(status_code=404, detail="Task not found")

    result_data = None
    if log.result_json:
        try:
            result_data = json.loads(log.result_json)
        except json.JSONDecodeError:
            result_data = None

    return {
        "status": log.status,
        "result": result_data,
        "task_type": log.task_type,
    }

@app.post("/api/settings/keys", dependencies=[Depends(require_api_key)])
async def update_keys(req: ApiKeysUpdate, db: AsyncSession = Depends(get_db)):
    """Store per-workspace LLM keys in the local DB (demo/self-host convenience).

    Note: keys are stored as provided in SQLite. In production prefer env vars.
    """
    keys = {
        "openai_api_key": req.openai_api_key,
        "anthropic_api_key": req.anthropic_api_key,
        "gemini_api_key": req.gemini_api_key,
        "glm_api_key": req.glm_api_key,
    }

    for k, v in keys.items():
        if v:
            res = await db.execute(select(Setting).where(Setting.key == k))
            setting = res.scalar_one_or_none()
            if setting:
                setting.value = v
            else:
                db.add(Setting(key=k, value=v))
    await db.commit()

    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.server:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
