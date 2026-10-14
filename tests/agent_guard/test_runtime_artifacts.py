from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_agent.agent_guard.runtime_artifacts import RuntimeBaseline, annotate_runtime_artifacts
from ai_agent.agent_guard.diff_parser import parse_unified_diff


def elf(body=b'library'):
    return b'\x7fELF\x02\x01\x01' + b'\0' * 9 + b'\x03\0' + b'\0' * 46 + body


def make_fixture(tmp_path):
    workspace = tmp_path / 'work'; workspace.mkdir()
    temp = tmp_path / 'tmp'; temp.mkdir()
    binary = tmp_path / 'opencode'
    library = elf(b'known embedded library')
    binary.write_bytes(elf(b'program') + library + b'end')
    return workspace, temp, binary, library


def diff(path):
    return f'--- /dev/null\n+++ b/{path}\n'


def test_only_new_identical_embedded_library_is_verified(tmp_path):
    work, temp, binary, lib = make_fixture(tmp_path)
    baseline = RuntimeBaseline.capture(binary=str(binary), workspace=str(work), temp_roots=[str(temp)])
    target = temp / '.1234567890abcdef-00000000.so'; target.write_bytes(lib)
    proof = baseline.verify(diff_text=diff(target), metadata={'snapshots':[{'changes':[{'path':str(target),'type':'+','size_delta':len(lib)}]}]}, run_id='r')
    assert proof['files'][0]['classification'] == 'verified_runtime_dependency'
    assert proof['files'][0]['sha256'] == hashlib.sha256(lib).hexdigest()
    event={'run_id':'r','workspace':str(work),'diff_ref':{'sha256':hashlib.sha256(diff(target).encode()).hexdigest()},'runtime_artifacts':proof}
    changed=annotate_runtime_artifacts(parse_unified_diff(diff(target)),event)
    assert changed[0].review_scope == 'runtime_dependency'
    assert changed[0].size_bytes == len(lib)


@pytest.mark.parametrize('case', ['unknown','preexisting','symlink','in_workspace','binary_changed','not_added','wrong_size'])
def test_unknown_or_unreliable_evidence_is_not_exempted(tmp_path, case):
    work, temp, binary, lib = make_fixture(tmp_path)
    target = (work if case=='in_workspace' else temp)/'.1234567890abcdef-00000000.so'
    if case=='preexisting':target.write_bytes(lib)
    baseline=RuntimeBaseline.capture(binary=str(binary),workspace=str(work),temp_roots=[str(temp),str(work)])
    if case=='symlink':
        original=temp/'real.so';original.write_bytes(lib);target.symlink_to(original)
    else:target.write_bytes(elf(b'unknown') if case=='unknown' else lib)
    if case=='binary_changed':binary.write_bytes(binary.read_bytes()+b'changed')
    metadata={'snapshots':[{'changes':[{'path':str(target),'type':'M' if case=='not_added' else '+','size_delta':1 if case=='wrong_size' else target.stat().st_size}]}]}
    proof=baseline.verify(diff_text=diff(target),metadata=metadata,run_id='r')
    assert not any(f['classification']=='verified_runtime_dependency' for f in proof['files'])


def test_proof_cannot_be_reused_for_another_run_or_diff(tmp_path):
    work,temp,binary,lib=make_fixture(tmp_path)
    baseline=RuntimeBaseline.capture(binary=str(binary),workspace=str(work),temp_roots=[str(temp)])
    target=temp/'.1234567890abcdef-00000000.so';target.write_bytes(lib)
    proof=baseline.verify(diff_text=diff(target),metadata={'snapshots':[{'changes':[{'path':str(target),'type':'+','size_delta':len(lib)}]}]},run_id='r')
    for run_id,sha in [('other',proof['diff_sha256']),('r','0'*64)]:
        changed=annotate_runtime_artifacts(parse_unified_diff(diff(target)),{'run_id':run_id,'workspace':str(work),'diff_ref':{'sha256':sha},'runtime_artifacts':proof})
        assert changed[0].review_scope=='task_change'


@pytest.mark.parametrize('limits', [(1000,2000),(1,2000),(1,2)])
def test_verified_artifacts_stay_in_record_but_not_task_analysis(tmp_path, limits):
    import json
    from ai_agent.agent_guard.adjudication_graph import run_adjudication_graph
    from ai_agent.agent_guard.config import AgentGuardConfig
    work,temp,binary,lib=make_fixture(tmp_path)
    baseline=RuntimeBaseline.capture(binary=str(binary),workspace=str(work),temp_roots=[str(temp)])
    target=temp/'.1234567890abcdef-00000000.so';target.write_bytes(lib)
    text='--- /dev/null\n+++ b/readme.md\n@@ -0,0 +1 @@\n+hello\n'+diff(target)
    proof=baseline.verify(diff_text=text,metadata={'snapshots':[{'changes':[{'path':str(target),'type':'+','size_delta':len(lib)}]}]},run_id='r')
    class LLM:
        def __init__(self):self.prompts=[]
        def complete(self,prompt):
            self.prompts.append(prompt)
            return json.dumps({'verdict':'allow','risk_level':'low','intent_alignment':'aligned','summary':'符合任务','recommended_action':'accept'})
    llm=LLM()
    event={'run_id':'r','original_request':'创建readme','workspace':str(work),'diff_ref':{'sha256':proof['diff_sha256']},'runtime_artifacts':proof}
    result=run_adjudication_graph(event=event,diff_text=text,config=AgentGuardConfig(small_diff_token_limit=limits[0],medium_diff_token_limit=limits[1]),llm=llm)
    assert len(result.changed_files)==2
    assert result.changed_files[1].review_scope=='runtime_dependency'
    assert all(str(target) not in p for p in llm.prompts)
    assert len(llm.prompts)==(1 if limits[0]==1000 else 2)
    assert result.adjudication.risk_level=='low'
    assert '运行依赖' in result.adjudication.summary


def test_unknown_binary_cannot_receive_unqualified_allow(tmp_path):
    import json
    from ai_agent.agent_guard.adjudication_graph import run_adjudication_graph
    from ai_agent.agent_guard.config import AgentGuardConfig
    class LLM:
        def complete(self,prompt):
            assert '不代表空文件' in prompt
            return json.dumps({'verdict':'allow','risk_level':'low','intent_alignment':'aligned','summary':'安全','recommended_action':'accept'})
    result=run_adjudication_graph(event={'original_request':'修改文件'},diff_text='--- /dev/null\n+++ b//tmp/unknown.so\n',config=AgentGuardConfig(),llm=LLM())
    assert result.adjudication.risk_level=='medium'
    assert result.adjudication.recommended_action=='ask_user'
    assert result.adjudication.intent_alignment=='unknown'
    assert '未展示内容' in result.adjudication.summary


def test_shim_publishes_diff_bound_runtime_evidence(tmp_path, monkeypatch):
    import json
    from ai_agent.agent_guard import nono_shim
    work,temp,binary,lib=make_fixture(tmp_path)
    baseline=RuntimeBaseline.capture(binary=str(binary),workspace=str(work),temp_roots=[str(temp)])
    target=temp/'.1234567890abcdef-00000000.so';target.write_bytes(lib)
    metadata={'snapshots':[{'changes':[{'path':str(target),'type':'+','size_delta':len(lib)}]}]}
    monkeypatch.setattr(nono_shim,'_run_command',lambda args,**kwargs:{'exit_code':0,'stdout':json.dumps(metadata) if '--json' in args else diff(target),'stderr':''})
    monkeypatch.setenv('AGENT_GUARD_DIFF_STORAGE','local')
    monkeypatch.setenv('DEEPXDR_AGENT_EVIDENCE_DIR',str(tmp_path/'evidence'))
    event=nono_shim._build_agent_session_event(args=['run','--rollback','--allow',str(work),'--','opencode'],
        run_id='r',state_home=str(tmp_path/'state'),real_nono='nono',command_env={},
        run_result={'exit_code':0,'stdout':'{"session_id":"s"}','stderr':''},runtime_baseline=baseline)
    assert event['runtime_artifacts']['diff_sha256']==event['diff_ref']['sha256']
    assert event['runtime_artifacts']['files'][0]['classification']=='verified_runtime_dependency'
    assert target.name in Path(event['diff_ref']['uri']).read_text()


def test_modified_or_unshown_library_proof_does_not_hide_business_diff(tmp_path):
    work,temp,binary,lib=make_fixture(tmp_path)
    baseline=RuntimeBaseline.capture(binary=str(binary),workspace=str(work),temp_roots=[str(temp)])
    target=temp/'.1234567890abcdef-00000000.so';target.write_bytes(lib)
    proof=baseline.verify(diff_text=diff(target),metadata={'snapshots':[{'changes':[{'path':str(target),'type':'+','size_delta':len(lib)}]}]},run_id='r')
    # Corrupt the proof: a match may not be claimed for text content or an old file.
    proof['files'][0]['content_status']='text'
    event={'run_id':'r','workspace':str(work),'diff_ref':{'sha256':proof['diff_sha256']},'runtime_artifacts':proof}
    assert annotate_runtime_artifacts(parse_unified_diff(diff(target)),event)[0].review_scope=='task_change'
