import json
import subprocess
from pathlib import Path

import pytest

from ai_agent.agent_guard.opencode_session import normalize_exports, prepare_capture


def message(mid, text, time=110, role='user', **part):
    return {'info': {'id': mid, 'sessionID': 'ses_1', 'role': role, 'time': {'created': time}},
            'parts': [{'type': 'text', 'text': text, **part}]}


def exported(workspace, *messages):
    return {'info': {'id': 'ses_1', 'directory': str(workspace)}, 'messages': list(messages)}


def normalize(tmp_path, messages, observed=None, **kwargs):
    return normalize_exports(run_id='run1', workspace=str(tmp_path), started_at=100, ended_at=200,
        observed=observed or [('ses_1', 'msg_1'), ('ses_1', 'msg_2')],
        exports={'ses_1': exported(tmp_path, *messages)}, errors=[], **kwargs)


def test_multiple_turns_and_history_have_explicit_scope(tmp_path):
    result = normalize(tmp_path, [message('old', '创建 text.md', 50),
        message('msg_1', '创建 wangbo.md'), message('msg_2', '追加日期', 150)])
    assert result['status'] == 'complete'
    assert [(m['id'], m['scope']) for m in result['messages']] == [('old', 'history'), ('msg_1', 'current'), ('msg_2', 'current')]
    assert result['messages'][-1]['text'] == '追加日期'


@pytest.mark.parametrize('messages', [
    [message('msg_1', '创建')],
    [message('msg_1', '创建'), message('msg_2', '追加'), message('other', '未关联', 130)],
    [message('msg_1', '创建'), message('msg_2', '追加', synthetic=True)],
    [message('msg_1', '创建'), message('msg_1', '重复'), message('msg_2', '追加')],
])
def test_incomplete_or_unattributed_evidence_is_never_complete(tmp_path, messages):
    assert normalize(tmp_path, messages)['status'] != 'complete'


def test_wrong_workspace_and_child_session_rejected(tmp_path):
    for override in [{'directory': '/another'}, {'parentID': 'parent'}]:
        data = exported(tmp_path, message('msg_1', '创建'))
        data['info'].update(override)
        result = normalize_exports(run_id='r', workspace=str(tmp_path), started_at=100, ended_at=200,
            observed=[('ses_1', 'msg_1')], exports={'ses_1': data}, errors=[])
        assert result['status'] != 'complete'
        assert result['messages'] == []


def test_limits_mark_partial_not_silent_success(tmp_path):
    result = normalize(tmp_path, [message('msg_1', 'x' * 100), message('msg_2', '追加')], max_chars=20)
    assert result['status'] == 'partial'
    assert result['errors']


def test_prepare_preserves_env_and_existing_plugins(tmp_path):
    env = {'PATH': '/usr/bin', 'OPENCODE_CONFIG_CONTENT': json.dumps({'plugin': ['existing'], 'theme': 'system'})}
    capture = prepare_capture(['/usr/bin/env', 'XDG_STATE_HOME=/custom/state', 'opencode', '--model', 'a/b'],
        env=env, workspace=str(tmp_path), run_id='run1')
    try:
        assert capture.export_env['XDG_STATE_HOME'] == '/custom/state'
        config = json.loads(capture.injected_env['OPENCODE_CONFIG_CONTENT'])
        assert config['plugin'][0] == 'existing'
        assert config['plugin'][-1].startswith('file://')
        assert config['theme'] == 'system'
        assert capture.finish()['status'] == 'missing'
        with pytest.raises(RuntimeError, match='运行'):
            prepare_capture(['opencode'], env=env, workspace=str(tmp_path), run_id='other')
    finally:
        capture.close()
    again = prepare_capture(['opencode'], env=env, workspace=str(tmp_path), run_id='again')
    again.close()


def test_non_opencode_is_unchanged(tmp_path):
    assert prepare_capture(['codex', 'run'], env={}, workspace=str(tmp_path), run_id='r') is None


def test_plugin_records_real_hook_identity(tmp_path):
    plugin = Path(__file__).resolve().parents[2] / 'ai_agent/agent_guard/opencode_plugin.mjs'
    script = '''
import { pathToFileURL } from 'node:url';
const { default: plugin } = await import(pathToFileURL(process.argv[1]));
const hooks = await plugin({directory: process.cwd()});
await hooks['chat.message']({sessionID:'ses_1'}, {message:{id:'msg_1',role:'user'},parts:[]});
'''
    env = __import__('os').environ.copy()
    env['AGENTREWIND_OPENCODE_JOURNAL'] = str(tmp_path / 'journal.jsonl')
    env['AGENTREWIND_OPENCODE_TOKEN'] = 'token'
    subprocess.run(['node', '--input-type=module', '-e', script, str(plugin)], env=env, check=True)
    rows = [json.loads(x) for x in (tmp_path/'journal.jsonl').read_text().splitlines()]
    assert rows[0]['type'] == 'ready'
    assert rows[1]['session_id'] == 'ses_1'
    assert rows[1]['message_id'] == 'msg_1'
    assert all(r['token'] == 'token' for r in rows)


def test_finish_exports_only_observed_sessions_and_marks_failed_export(tmp_path, monkeypatch):
    capture = prepare_capture(['opencode'], env={'PATH': '/usr/bin'}, workspace=str(tmp_path), run_id='r')
    try:
        def row(**data):
            return json.dumps(dict(token=capture.token, directory=str(tmp_path), **data)) + '\n'
        capture.journal.write_text(row(type='ready') + row(type='message', session_id='ses_1', message_id='m1') +
            row(type='message', session_id='ses_2', message_id='m2'))
        requested = []
        def export(sid):
            requested.append(sid)
            if sid == 'ses_2': raise ValueError('failure')
            return exported(tmp_path, message('m1', '创建', capture.started_at))
        monkeypatch.setattr(capture, '_export', export)
        result = capture.finish()
        assert requested == ['ses_1', 'ses_2']
        assert result['status'] == 'partial'
        assert result['messages'][0]['text'] == '创建'
    finally:
        capture.close()


def test_same_session_two_runs_do_not_reuse_prior_current_messages(tmp_path):
    rows = [message('a', '创建', 100), message('b', '追加', 300)]
    result = normalize_exports(run_id='second', workspace=str(tmp_path), started_at=250, ended_at=400,
        observed=[('ses_1', 'b')], exports={'ses_1': exported(tmp_path, *rows)}, errors=[])
    assert result['status'] == 'complete'
    assert [m['id'] for m in result['messages'] if m['scope'] == 'current'] == ['b']


def test_message_count_limit_marks_partial(tmp_path):
    rows = [message('h'+str(i), 'a', 50) for i in range(1000)] + [message('msg_1','创建'), message('msg_2','追加')]
    result = normalize(tmp_path, rows)
    assert result['status'] != 'complete'
    assert len(result['messages']) <= 128


@pytest.mark.parametrize('command', [['env', '--', 'opencode'], ['env', '-u', 'X', 'opencode'], ['bash', '-lc', 'opencode --model a/b']])
def test_unsupported_opencode_wrapper_is_missing_not_legacy(tmp_path, command):
    capture = prepare_capture(command, env={}, workspace=str(tmp_path), run_id='r')
    assert capture is not None
    try:
        assert capture.command == command
        assert capture.finish()['status'] == 'missing'
        assert any('包装' in e for e in capture.finish()['errors'])
    finally:
        capture.close()


def test_malformed_part_cannot_be_silently_dropped(tmp_path):
    row = message('msg_1', '创建')
    row['parts'].append({'type':'text', 'text':123})
    assert normalize(tmp_path, [row, message('msg_2', '追加')])['status'] == 'partial'


def test_attachment_metadata_cannot_overflow_event_limit(tmp_path):
    row = message('msg_1', '创建')
    row['parts'] += [{'type':'file', 'filename':'x'*10000} for _ in range(1000)]
    result = normalize(tmp_path, [row, message('msg_2', '追加')])
    assert result['status'] == 'partial'
    assert len(json.dumps(result, ensure_ascii=False)) < 160000
