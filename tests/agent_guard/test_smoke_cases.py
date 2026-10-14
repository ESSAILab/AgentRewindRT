from __future__ import annotations

import subprocess

from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.context_planner import plan_context
from ai_agent.agent_guard.diff_parser import estimate_token_count, parse_unified_diff
from scripts.agentguard_smoke_cases import prepare_smoke_case
from scripts.agentguard_smoke_cases import original_request_for_case


SMOKE_CONFIG = AgentGuardConfig(
    small_diff_token_limit=200,
    medium_diff_token_limit=800,
    file_token_limit=300,
    hunk_token_limit=80,
)


def _git_diff(workspace):
    result = subprocess.run(
        ["git", "diff", "--no-index", "--", "before", "after"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode in (0, 1)
    return result.stdout


def test_small_smoke_case_triggers_file_level_strategy(tmp_path):
    command = prepare_smoke_case("small", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/README.md README.md"]
    assert plan.strategy == "file_level"


def test_medium_smoke_case_triggers_hunk_summary_strategy(tmp_path):
    command = prepare_smoke_case("medium", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/service.py service.py && cp after/policy.yaml policy.yaml"]
    assert plan.strategy == "hunk_summary"
    assert len(changed_files) == 2


def test_large_smoke_case_triggers_risk_only_strategy(tmp_path):
    command = prepare_smoke_case("large", tmp_path)

    diff_text = _git_diff(tmp_path)
    changed_files = parse_unified_diff(diff_text)
    plan = plan_context(total_tokens=estimate_token_count(diff_text), files=changed_files, risk_signals_by_file={}, config=SMOKE_CONFIG)

    assert command == ["/bin/sh", "-c", "cp after/generated_policy.json generated_policy.json"]
    assert plan.strategy == "risk_only"


def test_agent_smoke_case_runs_real_opencode_agent(tmp_path):
    command = prepare_smoke_case("agent", tmp_path)

    assert command == [
        "opencode",
        "run",
        "--model",
        "agent-test/deepseek-v4-flash",
        original_request_for_case("agent"),
    ]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Smoke target\n\nThis file is intentionally incomplete.\n"
    assert (tmp_path / "opencode.json").exists()


def test_agent_case_configurable_model_and_endpoint(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("AGENTGUARD_SMOKE_MODEL", "demo/custom-model")
    monkeypatch.setenv("AGENTGUARD_SMOKE_BASE_URL", "https://example.test/v1")
    command = prepare_smoke_case("agent", tmp_path)
    assert command[3] == "demo/custom-model"
    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["provider"]["demo"]["options"]["baseURL"] == "https://example.test/v1"
    assert config["provider"]["demo"]["options"]["apiKey"] == "{env:OPENAI_API_KEY}"


def test_agent_shell_launch_is_capture_compatible(tmp_path):
    import json
    import os
    import shutil
    import sys
    from pathlib import Path
    from ai_agent.agent_guard.opencode_session import _agent_invocation

    repo = tmp_path / "repo with spaces"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "scripts"
    for name in ("agentguard-smoke-nono.sh", "agentguard_smoke_cases.py", "agentguard_path_policy.py"):
        shutil.copyfile(source / name, scripts / name)
    capture = tmp_path / "launch.json"
    shim = scripts / "nono"
    shim.write_text(f'#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\nPath(os.environ["CAPTURE"]).write_text(json.dumps({{"args":sys.argv[1:],"legacy":os.getenv("DEEPXDR_AGENT_ORIGINAL_REQUEST")}}))\n')
    shim.chmod(0o755)
    workspace = repo / "workspaces" / "smoke"
    state = repo / "state"
    workspace.parent.mkdir()
    state.mkdir()
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
               DEEPXDR_REAL_NONO="/unused/nono", AGENTGUARD_SMOKE_WORKSPACE=str(workspace),
               AGENTGUARD_WORKSPACE_ROOT=str(workspace.parent), AGENTGUARD_NONO_STATE_ROOT=str(state),
               DEEPXDR_NONO_STATE_HOME=str(state), OPENAI_API_KEY="test-only",
               DEEPXDR_AGENT_ORIGINAL_REQUEST="stale request", CAPTURE=str(capture),
               AGENTGUARD_SMOKE_MODEL="custom/model", AGENTGUARD_SMOKE_PROFILE="custom/profile",
               AGENTGUARD_SMOKE_ALLOW_DOMAIN="https://example.test/**")
    subprocess.run(["sh", str(scripts / "agentguard-smoke-nono.sh"), "agent"], env=env, check=True)
    launch = json.loads(capture.read_text())
    args = launch["args"]
    command = args[args.index("--") + 1:]
    invocation = _agent_invocation(command, env)
    assert invocation is not None
    index, actual_env = invocation
    assert command[index:] == ["opencode", "run", "--model", "custom/model", original_request_for_case("agent")]
    assert actual_env["XDG_STATE_HOME"] == str(workspace / ".opencode-runtime/state")
    assert launch["legacy"] is None
    assert args[args.index("--profile") + 1] == "custom/profile"
    assert args[args.index("--allow-domain") + 1] == "https://example.test/**"


def test_agent_default_endpoint_matches_verified_coding_service(tmp_path, monkeypatch):
    import json
    monkeypatch.delenv("AGENTGUARD_SMOKE_BASE_URL", raising=False)
    monkeypatch.delenv("AGENTGUARD_SMOKE_MODEL", raising=False)
    prepare_smoke_case("agent", tmp_path)
    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["provider"]["agent-test"]["options"]["baseURL"] == "https://ark.cn-beijing.volces.com/api/coding/v3"
