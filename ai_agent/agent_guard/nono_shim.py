from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Sequence

try:
    from agent_guard.opencode_session import prepare_capture, RUNTIME_DIR, normalize_exports
    from agent_guard.nono_wrapper import (
        _combined_output,
        _parse_json,
        _resolve_session_id,
        create_diff_evidence_writer_from_env,
    )
except ModuleNotFoundError:
    from ai_agent.agent_guard.opencode_session import prepare_capture, RUNTIME_DIR, normalize_exports
    from ai_agent.agent_guard.nono_wrapper import (
        _combined_output,
        _parse_json,
        _resolve_session_id,
        create_diff_evidence_writer_from_env,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    real_nono = _resolve_real_nono()
    run_id = os.getenv("DEEPXDR_AGENT_RUN_ID") or f"nono-{uuid.uuid4().hex}"
    state_home = os.getenv("DEEPXDR_NONO_STATE_HOME") or os.getenv("XDG_STATE_HOME")
    if not state_home:
        state_home = str(Path.home() / ".cache" / "deepxdr-nono-shim" / run_id)

    command_env = os.environ.copy()
    command_env["XDG_STATE_HOME"] = state_home
    capture = None
    conversation = None
    launch_args = list(args)
    started_at = time.time_ns() // 1_000_000
    if _is_guarded_run(args):
        try:
            capture = prepare_capture(_extract_agent_command(args), env=command_env,
                workspace=_extract_workspace(args), run_id=run_id)
        except RuntimeError as exc:
            print(f"deepxdr nono shim: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            conversation = normalize_exports(run_id=run_id, workspace=_extract_workspace(args),
                started_at=started_at, ended_at=started_at, observed=[], exports={},
                errors=[f"OpenCode 采集初始化失败：{type(exc).__name__}"])
        if capture:
            separator = args.index("--")
            launch_args = [*args[:separator], "--rollback-exclude", RUNTIME_DIR, "--", *capture.command]
    try:
        result = _run_command([real_nono, *launch_args], env=command_env,
                              interactive=os.getenv("DEEPXDR_NONO_INTERACTIVE") == "1")
        _forward_output(result)
        if capture:
            try:
                conversation = capture.finish()
            except Exception as exc:
                conversation = normalize_exports(run_id=run_id, workspace=capture.workspace,
                    started_at=capture.started_at, ended_at=time.time_ns() // 1_000_000,
                    observed=[], exports={}, errors=[f"会话采集失败：{type(exc).__name__}"])
        elif conversation:
            conversation["ended_at"] = time.time_ns() // 1_000_000
        # A nonzero agent exit can still leave changes; try to publish its evidence.
        if _is_guarded_run(args):
            try:
                event = _build_agent_session_event(
                    args=args, run_id=run_id, state_home=state_home, real_nono=real_nono,
                    command_env=command_env, run_result=result, conversation=conversation,
                    runtime_baseline=capture.runtime_baseline if capture else None,
                )
                _publish_event(event)
            except Exception as exc:
                print(f"deepxdr nono shim: failed to publish agent session event: {exc}", file=sys.stderr)
                return int(result["exit_code"]) or 2
        return int(result["exit_code"])
    finally:
        if capture:
            capture.close()


def _resolve_real_nono() -> str:
    configured = os.getenv("DEEPXDR_REAL_NONO") or os.getenv("NONO_REAL")
    if configured:
        return configured

    discovered = shutil.which("nono.real")
    if discovered:
        return discovered

    raise RuntimeError("DEEPXDR_REAL_NONO must point to the real nono binary, or nono.real must be on PATH")


def _run_command(command: list[str], *, env: dict[str, str], interactive: bool = False) -> dict:
    process = subprocess.run(command, env=env, text=True, capture_output=not interactive, check=False)
    return {
        "exit_code": process.returncode,
        "stdout": process.stdout or "",
        "stderr": process.stderr or "",
    }


def _forward_output(result: dict) -> None:
    if result.get("stdout"):
        print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="", file=sys.stderr)


def _is_guarded_run(args: list[str]) -> bool:
    return bool(args) and args[0] == "run" and "--rollback" in args


def _build_agent_session_event(
    *,
    args: list[str],
    run_id: str,
    state_home: str,
    real_nono: str,
    command_env: dict[str, str],
    run_result: dict,
    conversation: dict | None = None,
    runtime_baseline=None,
) -> dict:
    workspace = _extract_workspace(args)
    agent_command = _extract_agent_command(args)
    session_id = _resolve_session_id(
        run_result=run_result,
        rollback_state_home=Path(state_home),
        workspace=workspace,
        fallback=run_id,
    )

    metadata = _run_command([real_nono, "rollback", "show", session_id, "--json"], env=command_env)
    if metadata["exit_code"] != 0:
        raise RuntimeError(metadata.get("stderr") or "nono rollback metadata lookup failed")

    diff_result = _run_command([real_nono, "rollback", "show", session_id, "--diff"], env=command_env)
    if diff_result["exit_code"] != 0:
        raise RuntimeError(diff_result.get("stderr") or "nono rollback diff lookup failed")

    diff_writer = create_diff_evidence_writer_from_env(
        local_root=os.getenv("DEEPXDR_AGENT_EVIDENCE_DIR")
        or Path.home() / ".cache" / "deepxdr-agent" / "diff-evidence"
    )
    diff_ref = diff_writer.write(
        run_id=run_id,
        diff_text=_combined_output(diff_result),
    )

    artifact_evidence = None
    if runtime_baseline is not None:
        try:
            artifact_evidence = runtime_baseline.verify(diff_text=_combined_output(diff_result),
                metadata=_parse_json(metadata.get("stdout", "")), run_id=run_id)
        except Exception as exc:
            # Classification failure must never suppress the diff or publication.
            artifact_evidence = {"version": 1, "run_id": run_id, "files": [],
                                 "errors": [f"运行依赖核验失败：{type(exc).__name__}"]}

    original_request = os.getenv("DEEPXDR_AGENT_ORIGINAL_REQUEST") or " ".join(agent_command) or "nono run"
    if conversation is not None:
        original_request = "\n".join(m["text"] for m in conversation["messages"]
            if m["role"] == "user" and m["scope"] == "current")[:4000]
    return {
        **({"conversation": conversation} if conversation is not None else {}),
        **({"runtime_artifacts": artifact_evidence} if artifact_evidence is not None else {}),
        "type": "agent_session",
        "event_type": "finished",
        "schema_version": "1.1" if conversation is not None else "1.0",
        "source": "nono-path-shim",
        "run_id": run_id,
        "original_request": original_request,
        "agent_command": agent_command,
        "workspace": workspace,
        "diff_ref": diff_ref,
        "nono": {
            "session_id": session_id,
            "state_home": state_home,
            "rollback_root": str(Path(state_home) / "nono" / "rollbacks"),
            "exit_code": run_result.get("exit_code"),
            "metadata": _parse_json(metadata.get("stdout", "")),
        },
    }


def _extract_workspace(args: list[str]) -> str:
    if "--allow" in args:
        index = args.index("--allow")
        if index + 1 < len(args):
            return str(Path(args[index + 1]).resolve())
    return str(Path.cwd())


def _extract_agent_command(args: list[str]) -> list[str]:
    if "--" not in args:
        return []
    separator = args.index("--")
    return args[separator + 1 :]


def _publish_event(event: dict) -> None:
    events_file = os.getenv("DEEPXDR_AGENT_EVENTS_FILE")
    if events_file:
        path = Path(events_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    bootstrap_servers = os.getenv("DEEPXDR_AGENT_KAFKA_BOOTSTRAP_SERVERS") or os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if bootstrap_servers:
        topic = os.getenv("DEEPXDR_AGENT_SESSION_TOPIC", "agent.session.finished")
        asyncio.run(_publish_event_to_kafka(bootstrap_servers=bootstrap_servers, topic=topic, event=event))

    if not events_file and not bootstrap_servers:
        fallback = Path.home() / ".cache" / "deepxdr-agent" / "agent-events.jsonl"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        with fallback.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


async def _publish_event_to_kafka(*, bootstrap_servers: str, topic: str, event: dict) -> None:
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    await producer.start()
    try:
        await producer.send_and_wait(topic, json.dumps(event, ensure_ascii=False).encode("utf-8"))
    finally:
        await producer.stop()


if __name__ == "__main__":
    raise SystemExit(main())
