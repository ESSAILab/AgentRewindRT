from __future__ import annotations

import hmac
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from agent_guard.rollback import build_rollback_requested_event
from api_server.schemas import HealthResponse
from shared.utils.timezone import ChinaTime


router = APIRouter()
agent_session_repository = None
agent_rollback_publisher = None
BACKEND_API_KEY_ENV = "BACKEND_API_KEY"


def require_api_key(api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.getenv(BACKEND_API_KEY_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"API Key 未配置: 设置 {BACKEND_API_KEY_ENV} 环境变量",
        )
    if not api_key or not hmac.compare_digest(api_key.strip(), expected):
        raise HTTPException(status_code=401, detail="Invalid API key")


def set_agent_guard_components(repository, rollback_publisher) -> None:
    global agent_session_repository, agent_rollback_publisher
    agent_session_repository = repository
    agent_rollback_publisher = rollback_publisher


def _require_agent_guard_repository():
    if agent_session_repository is None:
        raise HTTPException(status_code=503, detail="Agent session repository unavailable")
    return agent_session_repository


def _require_agent_rollback_publisher():
    if agent_rollback_publisher is None:
        raise HTTPException(status_code=503, detail="Agent rollback publisher unavailable")
    return agent_rollback_publisher


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        service="agent-guard",
        timestamp=ChinaTime.now(),
        components={
            "agent_session_repository": "healthy" if agent_session_repository else "unhealthy",
            "rollback_publisher": "healthy" if agent_rollback_publisher else "unhealthy",
        },
    )


@router.get("/agent-sessions", dependencies=[Depends(require_api_key)])
async def list_agent_sessions(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    return await _require_agent_guard_repository().list_sessions(page=page, size=size)


@router.get("/agent-sessions/{run_id}", dependencies=[Depends(require_api_key)])
async def get_agent_session(run_id: str):
    session = await _require_agent_guard_repository().get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return session


@router.post("/agent-sessions/{run_id}/accept", dependencies=[Depends(require_api_key)])
async def accept_agent_session(run_id: str):
    session = await _require_agent_guard_repository().update_session(
        run_id,
        {"decision": "accepted", "rollback_status": "not_requested"},
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return {"status": "accepted", "run_id": run_id}


@router.delete("/agent-sessions/{run_id}", dependencies=[Depends(require_api_key)])
async def delete_agent_session(run_id: str):
    repo = _require_agent_guard_repository()
    try:
        deleted = await repo.delete_session(run_id)
    except Exception as exc:
        if exc.__class__.__name__ == "RollbackDeletionBlocked":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent session not found")
    return {"status": "deleted", "run_id": run_id}


@router.post("/agent-sessions/{run_id}/rollback", dependencies=[Depends(require_api_key)])
async def request_agent_session_rollback(run_id: str, request: dict[str, Any]):
    repo = _require_agent_guard_repository()
    publisher = _require_agent_rollback_publisher()
    session = await repo.get_session(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Agent session not found")

    nono = session.get("nono", {})
    nono_session_id = nono.get("session_id") or session.get("nono_session_id")
    if not nono_session_id:
        raise HTTPException(status_code=409, detail="nono session id missing")

    event = build_rollback_requested_event(
        run_id=run_id,
        nono_session_id=nono_session_id,
        requested_by=str(request.get("requested_by", "web_ui")),
        approved=True,
        nono_state_home=nono.get("state_home"),
        snapshot=int(request.get("snapshot", 0)),
    )
    if hasattr(repo, "request_rollback"):
        operation = await repo.request_rollback({**event, "status": "requested"})
    else:
        operation = {**event, "status": "requested"}
        if hasattr(repo, "store_rollback"):
            await repo.store_rollback(operation)

    event = {
        **event,
        "id": operation["id"],
        "nono_state_home": operation.get("nono_state_home", event.get("nono_state_home")),
        "snapshot": int(operation.get("snapshot", event.get("snapshot", 0))),
        "requested_by": operation.get("requested_by", event.get("requested_by", "web_ui")),
    }
    rollback_status = operation.get("status", "requested")
    if rollback_status == "requested" and hasattr(repo, "finish_rollback_publication"):
        try:
            await publisher.publish(event)
        except Exception:
            await repo.finish_rollback_publication(operation["id"], published=False)
            raise
        rollback_status = await repo.finish_rollback_publication(operation["id"], published=True)
    elif operation.get("_created", True) and rollback_status == "requested":
        await publisher.publish(event)

    decisions = {"completed": "rollback_completed", "failed": "rollback_failed"}
    await repo.update_session(
        run_id,
        {
            "decision": decisions.get(rollback_status, "rollback_requested"),
            "rollback_status": rollback_status,
        },
    )
    return {
        "status": "rollback_requested",
        "run_id": run_id,
        "rollback_id": operation["id"],
        "rollback_status": rollback_status,
    }
