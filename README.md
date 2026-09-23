# AI SEO Master Agent

An autonomous SEO manager that performs On-Page HTML optimization, Off-Page link building prospecting, and GMB updates.

## Overview
This repository contains a full-stack implementation of the **AI SEO Master Agent**. 
- **Backend:** FastAPI (Python), LiteLLM (Multi-LLM Support: OpenAI, Anthropic, Gemini, GLM)
- **Frontend:** Next.js (React, Tailwind CSS)
- **Database:** SQLite / PostgreSQL

## Getting Started

### 1. Backend Setup
\\\ash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn server:app --port 8000
\\\

### 2. Frontend Setup
\\\ash
cd frontend
npm install
npm run dev
\\\

## Coordination & Automation
This agent is part of a larger ecosystem. It can be executed natively via its UI, or coordinated as a node in a multi-agent pipeline using the Central Connector System.

## ▶️ Run (backend API)

```bash
cp .env.example .env   # add real LLM keys
pip install -r backend/requirements.txt
uvicorn backend.server:app --host 0.0.0.0 --port 8000
# Frontend (Next.js) lives in frontend/ -> deploy separately, e.g. Cloudflare Pages
```

Docker: `docker build -t seo-master-agent . && docker run -p 8000:8000 --env-file .env seo-master-agent`
