from __future__ import annotations

from shared.database.models import AgentAdjudication, AgentRollback, AgentSession
from shared.database.connection import Base


def test_agent_guard_tables_are_registered_in_metadata():
    assert AgentSession.__tablename__ == "agent_sessions"
    assert AgentAdjudication.__tablename__ == "agent_adjudications"
    assert AgentRollback.__tablename__ == "agent_rollbacks"
    assert "run_id" in AgentSession.__table__.columns
    assert "diff_ref" in AgentSession.__table__.columns
    assert "nono_state_home" in AgentRollback.__table__.columns


def test_only_agentguard_business_tables_are_registered():
    assert set(Base.metadata.tables) == {
        "agent_sessions",
        "agent_adjudications",
        "agent_rollbacks",
    }
