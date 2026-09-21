from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response


load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
MODULE_DIR = Path(__file__).resolve().parent
STATIC_DIR = MODULE_DIR / "static"
TEMPLATE = MODULE_DIR / "templates" / "dashboard.html"

app = FastAPI(title="AgentRewindRT Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/static/{file_path:path}")
async def serve_static_file(file_path: str):
    requested = (STATIC_DIR / file_path).resolve()
    if STATIC_DIR not in requested.parents or not requested.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    content_type, _ = mimetypes.guess_type(requested)
    return Response(
        content=requested.read_bytes(),
        media_type=content_type or "application/octet-stream",
    )


def get_backend_headers() -> dict[str, str]:
    api_key = os.getenv("BACKEND_API_KEY", "").strip()
    return {"X-API-Key": api_key} if api_key else {}


def request_backend(method: str, url: str, **kwargs):
    """Call the configured backend without inheriting host proxy settings."""
    session = requests.Session()
    session.trust_env = False
    try:
        return session.request(method, url, **kwargs)
    finally:
        session.close()


def _backend_json(method: str, path: str, **kwargs):
    try:
        response = request_backend(
            method,
            f"{API_BASE_URL}{path}",
            headers=get_backend_headers(),
            timeout=10,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        status_code = exc.response.status_code if exc.response is not None else 503
        raise HTTPException(status_code=status_code, detail=f"AgentGuard backend unavailable: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    if not TEMPLATE.is_file():
        raise HTTPException(status_code=404, detail="Dashboard template not found")
    return HTMLResponse(
        TEMPLATE.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/agent-sessions")
async def get_agent_session_list(page: int = 1, size: int = 20):
    return _backend_json("GET", f"/agent-sessions?page={page}&size={size}")


@app.get("/api/agent-sessions/{run_id}")
async def get_agent_session_detail(run_id: str):
    return _backend_json("GET", f"/agent-sessions/{run_id}")


@app.post("/api/agent-sessions/{run_id}/accept")
async def accept_agent_session(run_id: str):
    return _backend_json("POST", f"/agent-sessions/{run_id}/accept")


@app.post("/api/agent-sessions/{run_id}/rollback")
async def rollback_agent_session(run_id: str, request: Request):
    return _backend_json(
        "POST",
        f"/agent-sessions/{run_id}/rollback",
        json=await request.json(),
    )


@app.delete("/api/agent-sessions/{run_id}")
async def delete_agent_session(run_id: str):
    return _backend_json("DELETE", f"/agent-sessions/{run_id}")
