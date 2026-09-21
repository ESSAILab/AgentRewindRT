from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "web_ui/src/web/templates/dashboard.html"
DASHBOARD = ROOT / "web_ui/src/web/dashboard.py"
WEB_UI_SRC = ROOT / "web_ui/src"
if str(WEB_UI_SRC) not in sys.path:
    sys.path.insert(0, str(WEB_UI_SRC))

import web.dashboard as dashboard


def test_template_is_agentguard_only():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "智能体告警" in html
    for forbidden in (
        "analysisMode",
        "switchToNetworkMode",
        "switchToAgentMode",
        "shortTTPs",
        "longTTPs",
        "suricata_alert",
        "openrasp_alert",
        "falco_alert",
    ):
        assert forbidden not in html


def test_web_app_registers_only_agentguard_and_static_routes():
    assert {route.path for route in dashboard.app.routes} == {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/static/{file_path:path}",
        "/",
        "/api/agent-sessions",
        "/api/agent-sessions/{run_id}",
        "/api/agent-sessions/{run_id}/accept",
        "/api/agent-sessions/{run_id}/rollback",
    }
