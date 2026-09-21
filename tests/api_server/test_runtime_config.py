from __future__ import annotations

from ai_agent.shared.utils.config import load_config


def test_agentguard_config_does_not_require_network_analysis_settings(monkeypatch):
    for name in (
        "ELASTICSEARCH_HOST",
        "ELASTICSEARCH_PORT",
        "KAFKA_TOPIC",
        "KAFKA_GROUP_ID",
        "MCP_SERVER_URL",
        "SHORT_TTP_WINDOW_INTERVAL",
        "LONG_TTP_GENERATION_INTERVAL",
        "MAX_EVENTS_PER_WINDOW",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres/db")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("BACKEND_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "llm-secret")

    config = load_config()

    assert config.database_url.endswith("@postgres/db")
    assert config.kafka_bootstrap_servers == "kafka:9092"
    assert config.openai_api_key == "llm-secret"
    assert not hasattr(config, "elasticsearch_host")
    assert not hasattr(config, "redis_url")
    assert not hasattr(config, "kafka_topic")
    assert not hasattr(config, "mcp_server_url")
