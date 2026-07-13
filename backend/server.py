import os
import uuid
import json
import asyncio
import httpx
from bs4 import BeautifulSoup
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from dotenv import load_dotenv
from pydantic import BaseModel
import litellm

from database import engine, Base, SessionLocal, get_db
from models import Setting, ExecutionLog

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def fetch_website(url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            return soup.prettify()[:10000]
    except Exception as e:
        return f"Failed to fetch {url}: {e}"

def get_system_prompt(task_type: str) -> str:
    prompts = {
        "onpage": "You are an On-Page SEO Expert. Analyze the provided HTML and target keyword. Output ONLY a raw JSON object with keys: 'optimized_title', 'optimized_meta_description', 'h1_suggestion', 'keyword_density_analysis', 'content_recommendations'. No markdown fences.",
        "offpage": "You are an Off-Page SEO Link Building Expert. Output ONLY a raw JSON object with keys: 'target_domains_to_prospect' (array of types of sites), 'outreach_email_subject', 'outreach_email_body', 'follow_up_email'. No markdown fences.",
        "gmb": "You are a Google My Business (GMB) SEO Expert. Output ONLY a raw JSON object with keys: 'optimized_business_description', 'qa_pairs' (array of 5 Q&A objects with 'q' and 'a'), 'update_posts' (array of 3 short posts). No markdown fences.",
        "content": "You are a Social Media Content SEO Expert. Re-purpose the provided blog post into native social content optimized for semantic search. Output ONLY a raw JSON object with keys: 'twitter_thread' (array of tweets), 'linkedin_article', 'facebook_post'. No markdown fences.",
        "geo": "You are a Local Geo-SEO Expert (Programmatic SEO). Generate hyper-local landing page copy for the given City and Service. Output ONLY a raw JSON object with keys: 'geo_title', 'geo_meta_description', 'local_landmarks_to_mention' (array), 'localized_body_copy' (2 paragraphs). No markdown fences."
    }
    return prompts.get(task_type, "You are an SEO AI.")

async def process_seo_job(task_id: str, task_type: str, inputs_json: str, model_id: str, api_keys: dict):
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
            
            api_key = None
            api_base = None
            
            if model_id.startswith("gpt"):
                api_key = api_keys.get("openai") or os.getenv("OPENAI_API_KEY")
            elif model_id.startswith("claude"):
                api_key = api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")
            elif model_id.startswith("gemini"):
                api_key = api_keys.get("gemini") or os.getenv("GEMINI_API_KEY")
            elif model_id.startswith("zhipu"):
                api_key = api_keys.get("glm") or os.getenv("ZHIPUAI_API_KEY")
            elif model_id.startswith("ollama"):
                api_base = "http://localhost:11434"
                
            if not api_key and not api_base:
                raise Exception(f"No API key provided for {model_id}")

            response = await litellm.acompletion(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                api_key=api_key,
                api_base=api_base,
                max_tokens=3000
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
            print(f"Error processing SEO job: {e}")
            result = await db.execute(select(ExecutionLog).where(ExecutionLog.task_id == task_id))
            log = result.scalar_one_or_none()
            if log:
                log.status = "error"
                log.result_json = json.dumps({"error": str(e)})
                await db.commit()

class ExecuteRequest(BaseModel):
    task_type: str
    inputs: dict
    model_id: str

@app.post("/api/execute")
async def enqueue_task(req: ExecuteRequest, background_tasks: BackgroundTasks, request: Request, db: AsyncSession = Depends(get_db)):
    task_id = str(uuid.uuid4())
    
    log = ExecutionLog(
        task_id=task_id,
        task_type=req.task_type,
        inputs_json=json.dumps(req.inputs),
        model_provider=req.model_id,
        status="pending"
    )
    db.add(log)
    await db.commit()
    
    api_keys = {
        "openai": request.headers.get("X-OpenAI-Key"),
        "anthropic": request.headers.get("X-Anthropic-Key"),
        "gemini": request.headers.get("X-Gemini-Key"),
        "glm": request.headers.get("X-GLM-Key")
    }
    
    background_tasks.add_task(process_seo_job, task_id, req.task_type, json.dumps(req.inputs), req.model_id, api_keys)
    
    return {"status": "success", "task_id": task_id}

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExecutionLog).where(ExecutionLog.task_id == task_id))
    log = result.scalar_one_or_none()
    
    if not log:
        raise HTTPException(status_code=404, detail="Task not found")
        
    result_data = None
    if log.result_json:
        try:
            result_data = json.loads(log.result_json)
        except:
            pass
            
    return {
        "status": log.status,
        "result": result_data,
        "task_type": log.task_type
    }

class ApiKeysUpdate(BaseModel):
    openai_api_key: str = None
    anthropic_api_key: str = None
    gemini_api_key: str = None
    glm_api_key: str = None

@app.post("/api/settings/keys")
async def update_keys(req: ApiKeysUpdate, db: AsyncSession = Depends(get_db)):
    keys = {
        "openai_api_key": req.openai_api_key,
        "anthropic_api_key": req.anthropic_api_key,
        "gemini_api_key": req.gemini_api_key,
        "glm_api_key": req.glm_api_key
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
    uvicorn.run("server:app", host="0.0.0.0", port=8009, reload=True)
