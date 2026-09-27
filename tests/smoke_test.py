#!/usr/bin/env python3
"""
Smoke test for seo-master-agent backend.

Boots uvicorn from a fresh env (only SEO_API_KEY + dummy values set),
then asserts:
  - /health -> 200 {"status": "ok"} (no auth required)
  - /api/* without X-API-Key -> 401 structured JSON error
  - /api/execute with bad task_type / missing inputs / bad URL -> 422 structured JSON error
  - /api/execute valid payload -> 200 {"status": "success", "task_id": ...}
  - /api/tasks/<id> -> 200 with a task status
  - error bodies are structured JSON {"error": {"code", "message"}} with no stack traces

Run:  python tests/smoke_test.py
Exit code 0 = pass, non-zero = fail.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = "18099"
BASE = f"http://localhost:{PORT}"
KEY = "smoke-test-key-do-not-use-in-prod"


def http(method, path, body=None, key=KEY):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", "X-API-Key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw}


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f": {name}" + (f" ({detail})" if detail and not cond else ""))
    return cond


def main():
    ok = True
    env = {
        **os.environ,
        "SEO_API_KEY": KEY,
        "DATABASE_URL": "sqlite+aiosqlite:////tmp/smoke-seo.db",
        "PORT": PORT,
    }
    # remove any real-ish LLM keys from the inherited env so the test is hermetic
    for k in list(env):
        if k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ZHIPUAI_API_KEY"):
            env.pop(k, None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", PORT],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # wait for /health
        healthy = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                code, body = http("GET", "/health")
                if code == 200 and body.get("status") == "ok":
                    healthy = True
                    break
            except Exception:
                pass
        ok &= check("boot + /health 200", healthy)
        if not healthy:
            print("Server did not come up healthy; aborting.")
            return 1

        # auth
        code, body = http("GET", "/api/tasks/abc", key="WRONG")
        ok &= check("bad API key -> 401", code == 401)
        ok &= check("401 is structured JSON error", isinstance(body.get("error"), dict) and "code" in body["error"], str(body)[:120])
        code, _ = http("POST", "/api/execute", body={"task_type": "geo", "inputs": {"city": "x", "service": "y"}, "model_id": "gpt-4o"}, key="")
        ok &= check("missing API key -> 401", code == 401)

        # validation
        code, body = http("POST", "/api/execute", body={"task_type": "bogus", "inputs": {}, "model_id": "gpt-4o"})
        ok &= check("bad task_type -> 422", code == 422)
        ok &= check("422 is structured JSON error", body.get("error", {}).get("code") == "validation_error", str(body)[:160])
        code, _ = http("POST", "/api/execute", body={"task_type": "onpage", "inputs": {"url": "https://example.com"}, "model_id": "gpt-4o"})
        ok &= check("missing keyword -> 422", code == 422)
        code, _ = http("POST", "/api/execute", body={"task_type": "onpage", "inputs": {"url": "ftp://x", "keyword": "y"}, "model_id": "gpt-4o"})
        ok &= check("non-http URL -> 422", code == 422)
        code, _ = http("POST", "/api/execute", body={"task_type": "geo", "inputs": {"city": "x", "service": "y"}, "model_id": "mystery-model"})
        ok &= check("bad model_id -> 422", code == 422)

        # happy path enqueue (job will error in background: no LLM key -> expected "error" status)
        code, body = http("POST", "/api/execute", body={"task_type": "geo", "inputs": {"city": "Chennai", "service": "Dentist"}, "model_id": "gpt-4o"})
        ok &= check("valid enqueue -> 200", code == 200, str(body)[:120])
        task_id = body.get("task_id")
        ok &= check("enqueue returns task_id", bool(task_id))
        if task_id:
            time.sleep(3)  # let the background job attempt + fail without an LLM key
            code, body = http("GET", f"/api/tasks/{task_id}")
            ok &= check("task status -> 200", code == 200, str(body)[:160])
            ok &= check("task status is a known value", body.get("status") in ("pending", "running", "success", "error"), str(body)[:160])

        code, _ = http("GET", "/api/tasks/does-not-exist")
        ok &= check("unknown task -> 404", code == 404)
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        try:
            os.remove("/tmp/smoke-seo.db")
        except OSError:
            pass
    print("\nSMOKE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
