from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "deploy/migrations/drop_network_analysis_tables.sql"
NETWORK_TABLES = {
    "events",
    "short_ttps",
    "long_ttps",
    "short_ttp_events",
    "long_ttp_events",
    "long_ttp_short_ttps",
    "processing_status",
    "system_metrics",
    "long_ttp_generations",
    "langgraph_checkpoints",
    "langgraph_writes",
    "langgraph_blobs",
}


def test_network_table_migration_has_an_exact_drop_allowlist():
    sql = MIGRATION.read_text(encoding="utf-8")
    dropped_tables = set(
        re.findall(r"DROP\s+TABLE\s+IF\s+EXISTS\s+([a-z_]+)", sql, flags=re.IGNORECASE)
    )

    assert dropped_tables == NETWORK_TABLES
    assert not {"agent_sessions", "agent_adjudications", "agent_rollbacks"} & dropped_tables
    assert "BEGIN;" in sql
    assert "COMMIT;" in sql
