from __future__ import annotations

from copy import deepcopy

import pytest

from ai_agent.agent_guard.event_validation import validate_finished_session_event


def valid_event() -> dict:
    return {
        "type": "agent_session",
        "event_type": "finished",
        "run_id": "run-1",
        "original_request": "update README",
        "workspace": "/workspace/project",
        "diff_ref": {"uri": "s3://agent-diffs/run-1.diff", "sha256": "abc"},
        "nono": {"session_id": "session-1", "state_home": "/state/nono"},
    }


def test_valid_finished_session_is_normalized_without_mutating_input():
    event = valid_event()
    original = deepcopy(event)

    normalized = validate_finished_session_event(event)

    assert event == original
    assert normalized is not event
    assert normalized["source"] == "nono-path-shim"
    assert normalized["category"] == "agent_runtime_change"
    assert "baseline_action" not in normalized


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("type",), "other"),
        (("event_type",), "started"),
        (("run_id",), ""),
        (("original_request",), ""),
        (("workspace",), "relative/path"),
        (("diff_ref", "uri"), ""),
        (("diff_ref", "sha256"), ""),
        (("nono", "session_id"), ""),
        (("nono", "state_home"), ""),
    ],
)
def test_invalid_finished_session_is_rejected(path, value):
    event = valid_event()
    target = event
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError):
        validate_finished_session_event(event)
