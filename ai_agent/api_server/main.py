from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_server.routes import router, set_agent_guard_components


def create_app(agent_session_repository=None, agent_rollback_publisher=None) -> FastAPI:
    app = FastAPI(
        title="AgentGuard API",
        description="AI 智能体变更风险分析与恢复 API",
        version="1.0.0",
    )
    cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:30003").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    set_agent_guard_components(agent_session_repository, agent_rollback_publisher)
    app.include_router(router)
    return app
