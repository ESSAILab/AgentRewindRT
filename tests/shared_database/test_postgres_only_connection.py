from __future__ import annotations

from ai_agent.shared.database.connection import DatabaseManager


def test_database_manager_has_no_redis_dependency():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")

    assert not hasattr(manager, "redis_url")
    assert not hasattr(manager, "redis_client")
    assert not hasattr(manager, "get_redis_client")
