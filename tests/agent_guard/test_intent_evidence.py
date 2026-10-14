import json

import pytest

from ai_agent.agent_guard.intent_evidence import intent_input, enforce_intent_evidence
from ai_agent.agent_guard.adjudicator import AdjudicationResult
from ai_agent.agent_guard.event_validation import validate_finished_session_event
from ai_agent.agent_guard.adjudication_graph import run_adjudication_graph
from ai_agent.agent_guard.config import AgentGuardConfig


def event(status='complete'):
    return {'run_id': 'run1', 'original_request': 'STALE_ENV', 'conversation': {
        'version': 1, 'source': 'opencode_export', 'status': status, 'run_id': 'run1',
        'started_at': 100, 'ended_at': 200, 'sessions': [{'id': 'ses_1', 'title': '测试'}], 'errors': [],
        'messages': [{'id': 'm1', 'session_id': 'ses_1', 'role': 'user', 'scope': 'current', 'created_at': 110, 'text': '创建 wangbo.md'},
                     {'id': 'm2', 'session_id': 'ses_1', 'role': 'user', 'scope': 'current', 'created_at': 120, 'text': '追加日期'}]}}


def test_input_uses_all_actual_turns_not_stale_variable():
    text = intent_input(event())
    assert 'STALE_ENV' not in text
    assert '创建 wangbo.md' in text and '追加日期' in text
    assert 'm1' in text and 'm2' in text
    assert '取消' in text and '助手' in text


@pytest.mark.parametrize('status', ['missing', 'partial', 'ambiguous'])
def test_missing_evidence_overrides_model_allow(status):
    result = enforce_intent_evidence(event(status), AdjudicationResult('allow', 'low', False, '一致', recommended_action='accept', intent_alignment='aligned'))
    assert result.intent_alignment == 'unknown'
    assert result.out_of_intent is None
    assert result.risk_level == 'medium'
    assert result.verdict == 'needs_human_review'
    assert result.recommended_action == 'ask_user'
    assert '证据' in result.summary


def test_legacy_request_is_preserved():
    assert intent_input({'original_request': '旧任务'}) == '旧任务'


def test_missing_evidence_event_accepts_empty_original_request():
    e = event('missing')
    e.update(type='agent_session', event_type='finished', schema_version='1.1', original_request='', workspace='/repo',
        diff_ref={'uri': '/diff', 'sha256': 'abc'}, nono={'session_id': 'n', 'state_home': '/state'})
    e['conversation']['messages'] = []
    assert validate_finished_session_event(e)['original_request'] == ''
    e['conversation']['run_id'] = 'another'
    with pytest.raises(ValueError):
        validate_finished_session_event(e)


@pytest.mark.parametrize('limits', [(1000, 2000), (1, 2000), (1, 2)])
def test_all_graph_strategies_enforce_unknown(limits):
    class LLM:
        def __init__(self): self.prompts=[]
        def complete(self, prompt):
            self.prompts.append(prompt)
            return json.dumps({'verdict':'allow','risk_level':'low','out_of_intent':False,
                'intent_alignment':'aligned','recommended_action':'accept','summary':'一致'})
    llm = LLM()
    result = run_adjudication_graph(event=event('partial'), diff_text='diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print(1)\n',
        config=AgentGuardConfig(small_diff_token_limit=limits[0], medium_diff_token_limit=limits[1]), llm=llm)
    assert result.adjudication.intent_alignment == 'unknown'
    assert result.adjudication.recommended_action == 'ask_user'
    assert all('STALE_ENV' not in p and '追加日期' in p for p in llm.prompts)
