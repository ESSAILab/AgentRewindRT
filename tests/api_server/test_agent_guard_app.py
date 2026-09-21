from __future__ import annotations

from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository
from api_server.main import create_app


class PublisherStub:
    async def publish(self, _event):
        return None


def test_openapi_contains_only_agentguard_business_routes():
    app = create_app(InMemoryAgentSessionRepository(), PublisherStub())

    assert set(app.openapi()["paths"]) == {
        "/health",
        "/agent-sessions",
        "/agent-sessions/{run_id}",
        "/agent-sessions/{run_id}/accept",
        "/agent-sessions/{run_id}/rollback",
    }


def test_openapi_has_no_network_analysis_terms():
    document = str(
        create_app(InMemoryAgentSessionRepository(), PublisherStub()).openapi()
    ).lower()

    for forbidden in ("short-ttp", "long-ttp", "mitre", "event detail", "feedback"):
        assert forbidden not in document
