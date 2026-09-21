from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_network_analysis_source_trees_are_physically_absent():
    removed_paths = [
        "baseline_adjudication",
        "third_party",
        "ai_agent/data_consumer",
        "ai_agent/ttp_generator",
        "ai_agent/mitre_attck_agent",
        "ai_agent/defense",
        "ai_agent/data",
        "ai_agent/.cache/mitre_attack",
        "ai_agent/shared/models",
        "ai_agent/shared/utils/elasticsearch_config.py",
    ]

    assert [path for path in removed_paths if (REPO_ROOT / path).exists()] == []


def test_only_agentguard_test_suites_remain():
    removed_tests = [
        "tests/baseline_adjudication",
        "tests/test_attack_rag_workflow.py",
        "tests/test_cleanup_baseline.py",
        "tests/test_defense_manager.py",
        "tests/test_kafka_consumer_offsets.py",
        "tests/test_long_ttp_mitre_result.py",
        "tests/test_mcp_client_env.py",
        "tests/test_mcp_server_security.py",
        "tests/test_prompt_evidence_sources.py",
        "tests/test_short_ttp_workflow.py",
        "tests/test_truncate_messages_security.py",
    ]

    assert [path for path in removed_tests if (REPO_ROOT / path).exists()] == []
