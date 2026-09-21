from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def validate_finished_session_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an AgentGuard completed-session event."""
    if not isinstance(event, dict):
        raise ValueError("agent session event must be an object")
    if event.get("type") != "agent_session":
        raise ValueError("agent session event type must be agent_session")
    if event.get("event_type") != "finished":
        raise ValueError("agent session event_type must be finished")

    for field in ("run_id", "original_request", "workspace"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"agent session event requires {field}")
    if not Path(event["workspace"]).is_absolute():
        raise ValueError("agent session workspace must be absolute")

    diff_ref = event.get("diff_ref")
    if not isinstance(diff_ref, dict) or not diff_ref.get("uri") or not diff_ref.get("sha256"):
        raise ValueError("agent session event requires diff_ref.uri and diff_ref.sha256")

    nono = event.get("nono")
    if not isinstance(nono, dict) or not nono.get("session_id") or not nono.get("state_home"):
        raise ValueError("agent session event requires nono.session_id and nono.state_home")

    normalized = deepcopy(event)
    normalized.setdefault("source", "nono-path-shim")
    normalized["category"] = "agent_runtime_change"
    normalized.pop("baseline_action", None)
    return normalized
