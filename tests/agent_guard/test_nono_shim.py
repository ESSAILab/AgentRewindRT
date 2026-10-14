from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from ai_agent.agent_guard import nono_shim


def test_nono_shim_runs_real_nono_and_writes_agent_session_event(tmp_path):
    real_nono = tmp_path / "nono.real"
    calls_file = tmp_path / "calls.jsonl"
    real_nono.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

calls = Path(os.environ["CALLS_FILE"])
with calls.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "xdg": os.environ.get("XDG_STATE_HOME")}) + "\\n")

if sys.argv[1:4] == ["rollback", "show", "session-1"]:
    if "--json" in sys.argv:
        print(json.dumps({"session_id": "session-1", "tracked_paths": [os.getcwd()]}))
        sys.exit(0)
    if "--diff" in sys.argv:
        print("diff --git a/README.md b/README.md")
        print("+new")
        sys.exit(0)

print(json.dumps({"session_id": "session-1"}))
sys.exit(0)
""",
        encoding="utf-8",
    )
    real_nono.chmod(0o755)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_home = tmp_path / "state"
    evidence_dir = tmp_path / "evidence"
    events_file = tmp_path / "agent-events.jsonl"

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join([str(repo_root), str(repo_root / "ai_agent"), env.get("PYTHONPATH", "")])
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "CALLS_FILE": str(calls_file),
            "DEEPXDR_REAL_NONO": str(real_nono),
            "DEEPXDR_NONO_STATE_HOME": str(state_home),
            "DEEPXDR_AGENT_EVIDENCE_DIR": str(evidence_dir),
            "DEEPXDR_AGENT_EVENTS_FILE": str(events_file),
            "DEEPXDR_AGENT_ORIGINAL_REQUEST": "update README",
            "DEEPXDR_AGENT_RUN_ID": "run-shim-1",
        }
    )

    result = subprocess.run(
        [str(repo_root / "scripts" / "nono"), "run", "--rollback", "--allow", str(workspace), "--", "codex", "run"],
        cwd=str(workspace),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    calls = [json.loads(line) for line in calls_file.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["argv"] == ["run", "--rollback", "--allow", str(workspace), "--", "codex", "run"]
    assert calls[0]["xdg"] == str(state_home)
    assert ["rollback", "show", "session-1", "--json"] in [call["argv"] for call in calls]
    assert ["rollback", "show", "session-1", "--diff"] in [call["argv"] for call in calls]

    event = json.loads(events_file.read_text(encoding="utf-8").splitlines()[0])
    assert event["type"] == "agent_session"
    assert event["event_type"] == "finished"
    assert event["source"] == "nono-path-shim"
    assert event["run_id"] == "run-shim-1"
    assert event["original_request"] == "update README"
    assert event["workspace"] == str(workspace)
    assert event["agent_command"] == ["codex", "run"]
    assert event["nono"]["session_id"] == "session-1"
    assert event["nono"]["state_home"] == str(state_home)

    diff_text = Path(event["diff_ref"]["uri"]).read_text(encoding="utf-8")
    assert "+new" in diff_text
    assert event["diff_ref"]["sha256"]


def test_nono_shim_publishes_to_agent_session_topic_by_default(monkeypatch):
    published = {}

    async def capture_publish(*, bootstrap_servers, topic, event):
        published.update(
            bootstrap_servers=bootstrap_servers,
            topic=topic,
            event=event,
        )

    monkeypatch.delenv("DEEPXDR_AGENT_EVENTS_FILE", raising=False)
    monkeypatch.setenv("DEEPXDR_AGENT_KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.delenv("DEEPXDR_AGENT_SESSION_TOPIC", raising=False)
    monkeypatch.setattr(nono_shim, "_publish_event_to_kafka", capture_publish)

    event = {"run_id": "run-topic-1"}
    nono_shim._publish_event(event)

    assert published == {
        "bootstrap_servers": "kafka:9092",
        "topic": "agent.session.finished",
        "event": event,
    }


def test_interactive_only_applies_to_agent_launch(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=None, stderr=None)
    monkeypatch.setattr(subprocess, 'run', run)
    nono_shim._run_command(['nono', 'run'], env={'DEEPXDR_NONO_INTERACTIVE': '1'}, interactive=True)
    nono_shim._run_command(['nono', 'rollback', 'show'], env={'DEEPXDR_NONO_INTERACTIVE': '1'})
    assert calls[0]['capture_output'] is False
    assert calls[1]['capture_output'] is True


@pytest.mark.parametrize("exit_code", [0, 7])
def test_opencode_shim_collects_real_plugin_hooks_and_formal_export(tmp_path, monkeypatch, exit_code):
    """Local contract harness: runs the actual plugin, not an actual model/agent."""
    import sys
    from ai_agent.agent_guard.event_validation import validate_finished_session_event
    agent = tmp_path / 'opencode'
    agent.write_text('#!' + sys.executable + '\n' + '''
import json, os, subprocess, sys, time
from pathlib import Path
store = Path(os.environ['TEST_SESSION_STORE'])
if sys.argv[1:] == ['export','ses_test']:
    print(store.read_text()); sys.exit(0)
config = json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
plugin = config['plugin'][-1]
messages=[]
for i,text in enumerate(['创建 wangbo.md','在文件末尾追加日期']):
    mid='msg_'+str(i)
    messages.append({'info':{'id':mid,'sessionID':'ses_test','role':'user','time':{'created':time.time_ns()//1000000}},'parts':[{'type':'text','text':text}]})
script = "const {default: plugin}=await import(process.argv[1]); const hooks=await plugin({directory:process.cwd()}); for (const id of ['msg_0','msg_1']) await hooks['chat.message']({sessionID:'ses_test'},{message:{id},parts:[]});"
subprocess.run(['node','--input-type=module','-e',script,plugin],check=True)
store.write_text(json.dumps({'info':{'id':'ses_test','directory':os.getcwd()},'messages':messages}))
sys.exit(int(os.environ.get('TEST_AGENT_EXIT', '0')))
''')
    agent.chmod(0o755)
    nono = tmp_path / 'nono.real'
    nono.write_text('#!' + sys.executable + '\n' + '''
import json,subprocess,sys
if sys.argv[1]=='run':
    r=subprocess.run(sys.argv[sys.argv.index('--')+1:]); print(json.dumps({'session_id':'nono_test'}));sys.exit(r.returncode)
if '--json' in sys.argv: print('{}')
else: print('diff --git a/wangbo.md b/wangbo.md\\n+++ b/wangbo.md\\n@@\\n+20261012')
''')
    nono.chmod(0o755)
    workspace=tmp_path/'work'; workspace.mkdir(); monkeypatch.chdir(workspace)
    env = {'DEEPXDR_REAL_NONO':str(nono), 'DEEPXDR_AGENT_EVENTS_FILE':str(tmp_path/'events'),
        'DEEPXDR_AGENT_EVIDENCE_DIR':str(tmp_path/'evidence'), 'TEST_SESSION_STORE':str(tmp_path/'export.json'),
        'DEEPXDR_AGENT_ORIGINAL_REQUEST':'这条旧任务必须被忽略', 'DEEPXDR_AGENT_RUN_ID':'integration-run',
        'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'], 'TEST_AGENT_EXIT':str(exit_code)}
    for key,value in env.items(): monkeypatch.setenv(key,value)
    for key in ['DEEPXDR_AGENT_KAFKA_BOOTSTRAP_SERVERS','KAFKA_BOOTSTRAP_SERVERS','OPENCODE_CONFIG_CONTENT']:
        monkeypatch.delenv(key,raising=False)
    args=['run','--rollback','--allow',str(workspace),'--','/usr/bin/env','XDG_STATE_HOME='+str(tmp_path/'agentstate'),'opencode']
    assert nono_shim.main(args)==exit_code
    e=json.loads((tmp_path/'events').read_text())
    assert e['nono']['exit_code']==exit_code
    assert e['conversation']['status']=='complete', e['conversation']['errors']
    assert len(e['conversation']['messages'])==2
    assert e['original_request']=='创建 wangbo.md\n在文件末尾追加日期'
    assert e['agent_command']==args[args.index('--')+1:]
    assert validate_finished_session_event(e)['conversation']['run_id']=='integration-run'
