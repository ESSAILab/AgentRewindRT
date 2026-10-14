"""Associate a protected OpenCode run with exported, identified messages.

No newest-session heuristics and no prompt-history fallback. Collection errors
are evidence states, not permission to replace user intent with a command line.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime_artifacts import RuntimeBaseline

MAX_CHARS = 64_000
MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_SESSIONS = 8
MAX_MESSAGES = 128
RUNTIME_DIR = '.agentrewind-opencode'
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,160}$')


def _agent_invocation(command: list[str], env: dict[str, str]):
    actual_env = dict(env)
    index = 0
    if command and Path(command[0]).name == 'env':
        index = 1
        while index < len(command) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', command[index]):
            key, value = command[index].split('=', 1)
            actual_env[key] = value
            index += 1
    if index >= len(command) or Path(command[index]).name != 'opencode':
        return None
    return index, actual_env


@dataclass
class Capture:
    command: list[str]
    export_env: dict[str, str]
    injected_env: dict[str, str]
    workspace: str
    run_id: str
    started_at: int
    token: str
    journal: Path
    binary: str
    lock: Any
    unsupported: str = ''
    runtime_baseline: RuntimeBaseline | None = None

    def close(self):
        if not self.lock.closed:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()

    def finish(self) -> dict:
        ended_at = time.time_ns() // 1_000_000
        errors = [self.unsupported] if self.unsupported else []
        observed = []
        ready = False
        try:
            if self.journal.stat().st_size > 1_000_000:
                raise ValueError('采集日志超过容量限制')
            for line in self.journal.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row.get('token') != self.token or Path(row.get('directory', '')).resolve() != Path(self.workspace):
                    raise ValueError('采集日志的运行或目录关联不匹配')
                if row.get('type') == 'ready':
                    ready = True
                elif row.get('type') == 'message':
                    pair = (row.get('session_id'), row.get('message_id'))
                    if not all(isinstance(x, str) and IDENTIFIER.fullmatch(x) for x in pair):
                        raise ValueError('会话或消息 ID 无效')
                    if pair not in observed:
                        observed.append(pair)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'会话关联日志不可用：{type(exc).__name__}')
        if not ready:
            errors.append('未收到 OpenCode 插件就绪记录')
        if not observed:
            errors.append('未采集到本次运行的用户消息关联')
        exports = {}
        session_ids = list(dict.fromkeys(s for s, _ in observed))
        if len(session_ids) > MAX_SESSIONS:
            errors.append('会话数量超过采集上限')
        for session_id in session_ids[:MAX_SESSIONS]:
            if self.unsupported:
                break
            try:
                exports[session_id] = self._export(session_id)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                # Never include subprocess stderr: it can contain provider credentials.
                errors.append(f'会话 {session_id} 导出失败：{type(exc).__name__}')
        return normalize_exports(run_id=self.run_id, workspace=self.workspace,
            started_at=self.started_at, ended_at=ended_at, observed=observed,
            exports=exports, errors=errors)

    def _export(self, session_id: str) -> dict:
        # Redirect to a bounded-on-read local artifact instead of retaining arbitrary
        # subprocess output in memory. Export uses the agent's effective XDG env.
        target = self.journal.parent / f'{session_id}.json'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            result = subprocess.run([self.binary, 'export', session_id], cwd=self.workspace,
                env=self.export_env, stdout=output, stderr=subprocess.DEVNULL, timeout=45, check=False)
        if result.returncode:
            raise ValueError('export exited unsuccessfully')
        if target.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError('export too large')
        value = json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('export must be an object')
        return value


def prepare_capture(command: list[str], *, env: dict[str, str], workspace: str, run_id: str) -> Capture | None:
    invocation = _agent_invocation(command, env)
    unsupported_wrapper = invocation is None
    if unsupported_wrapper:
        if not any(re.search(r'(^|[\s/])opencode($|\s)', arg) for arg in command):
            return None
        index, actual_env = 0, dict(env)
    else:
        index, actual_env = invocation
    workspace = str(Path(workspace).resolve())
    lock_root = Path.home() / '.cache' / 'agentrewind-opencode-locks'
    lock_root.mkdir(parents=True, exist_ok=True)
    lock = (lock_root / hashlib.sha256(workspace.encode()).hexdigest()).open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('该工作目录已有受保护的 OpenCode 运行，请结束后再启动') from None
    try:
        token = uuid.uuid4().hex
        runtime = Path(workspace) / RUNTIME_DIR / token
        runtime.mkdir(parents=True, mode=0o700)
        plugin = runtime / 'capture.mjs'
        shutil.copyfile(Path(__file__).with_name('opencode_plugin.mjs'), plugin)
        journal = runtime / 'journal.jsonl'
        config = json.loads(actual_env.get('OPENCODE_CONFIG_CONTENT') or '{}')
        if not isinstance(config, dict) or not isinstance(config.get('plugin', []), list):
            raise ValueError('OPENCODE_CONFIG_CONTENT 必须是 JSON 对象，plugin 必须是数组')
        config['plugin'] = [*config.get('plugin', []), plugin.as_uri()]
        injected = {'OPENCODE_CONFIG_CONTENT': json.dumps(config, ensure_ascii=False),
            'AGENTREWIND_OPENCODE_JOURNAL': str(journal), 'AGENTREWIND_OPENCODE_TOKEN': token}
        # Put our env assignments after the user's env assignments so a stale
        # collector/config variable cannot change the association for this run.
        assignments = [f'{k}={v}' for k, v in injected.items()]
        launch = [*command[:index], *assignments, *command[index:]] if index else ['/usr/bin/env', *assignments, *command]
        binary = shutil.which(command[index], path=actual_env.get('PATH')) or command[index]
        # Export must not initialize the capture plugin a second time.
        export_env = dict(actual_env)
        export_env.pop('AGENTREWIND_OPENCODE_JOURNAL', None)
        export_env.pop('AGENTREWIND_OPENCODE_TOKEN', None)
        unsupported = '不支持该 OpenCode 命令包装形式，无法关联实际交互' if unsupported_wrapper else ''
        if unsupported_wrapper:
            launch = list(command)
        if any(arg == 'attach' or arg == '--attach' or arg.startswith('--attach=') for arg in command[index + 1:]):
            unsupported = '远程 attach 模式无法使用本地运行关联，意图证据不足'
        baseline = None
        if not unsupported:
            baseline = RuntimeBaseline.capture(binary=binary, workspace=workspace,
                temp_roots=[actual_env.get('BUN_TMPDIR') or actual_env.get('TMPDIR') or '/tmp',
                            actual_env.get('TMPDIR') or '/tmp'])
        return Capture(launch, export_env, injected, workspace, run_id, time.time_ns() // 1_000_000,
                       token, journal, binary, lock, unsupported, baseline)
    except Exception:
        lock.close()
        raise


def normalize_exports(*, run_id: str, workspace: str, started_at: int, ended_at: int,
                      observed: list[tuple[str, str]], exports: dict[str, dict], errors: list[str],
                      max_chars: int = MAX_CHARS) -> dict:
    errors = list(errors)
    messages, sessions = [], []
    seen = set()
    remaining = max_chars
    ambiguous = False
    for sid in dict.fromkeys(s for s, _ in observed):
        data = exports.get(sid)
        if not isinstance(data, dict):
            errors.append(f'缺少会话 {sid} 的正式导出')
            continue
        info = data.get('info', {})
        if (not isinstance(info, dict) or info.get('id') != sid or info.get('parentID')
                or not isinstance(info.get('directory'), str)
                or Path(info['directory']).resolve() != Path(workspace).resolve()):
            errors.append(f'会话 {sid} 身份或工作目录不匹配')
            ambiguous = True
            continue
        sessions.append({'id': sid, 'title': str(info.get('title', ''))[:300]})
        rows = data.get('messages', [])
        if not isinstance(rows, list):
            errors.append(f'会话 {sid} 消息格式无效')
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('info'), dict):
                errors.append('消息格式无效')
                continue
            meta = row['info']
            mid, role = meta.get('id'), meta.get('role')
            if role not in ('user', 'assistant'):
                continue
            pair = (sid, mid)
            if not isinstance(mid, str) or not IDENTIFIER.fullmatch(mid) or meta.get('sessionID') != sid or pair in seen:
                errors.append('消息身份不匹配或重复')
                continue
            seen.add(pair)
            timing = meta.get('time')
            created = timing.get('created') if isinstance(timing, dict) else None
            if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
                errors.append(f'消息 {mid} 缺少时间')
                continue
            current = pair in observed
            if current and (role != 'user' or not started_at <= created <= ended_at):
                errors.append(f'消息 {mid} 不属于本次运行边界')
                continue
            if created > ended_at:
                errors.append(f'消息 {mid} 超出本次运行边界')
                continue
            parts = row.get('parts', [])
            if not isinstance(parts, list):
                errors.append(f'消息 {mid} 内容格式无效')
                continue
            if any(not isinstance(p, dict) or (p.get('type') == 'text' and not isinstance(p.get('text'), str)) for p in parts):
                errors.append(f'消息 {mid} 包含损坏的内容片段')
            text_parts = [p.get('text', '') for p in parts if isinstance(p, dict) and p.get('type') == 'text'
                          and not p.get('synthetic') and not p.get('ignored') and isinstance(p.get('text', ''), str)]
            text = '\n'.join(text_parts)
            if role == 'user' and created >= started_at and not current and text.strip():
                errors.append(f'运行期间消息 {mid} 未被本次采集关联')
                ambiguous = True
                continue
            attachments = [{'type': p.get('type'), 'filename': str(p.get('filename', ''))[:300]}
                           for p in parts if isinstance(p, dict) and p.get('type') in ('file', 'agent')]
            if len(attachments) > 10:
                attachments = attachments[:10]
                errors.append('附件数量超过上限')
            if attachments:
                errors.append(f'消息 {mid} 包含未解析的附件或代理引用')
            if current and not text.strip():
                errors.append(f'消息 {mid} 没有可用的真实用户文本')
            if not text and not attachments:
                continue
            if len(text) > remaining:
                errors.append('对话超过采集字符上限，证据已截断')
                text = text[:remaining]
            remaining -= len(text)
            if len(messages) >= MAX_MESSAGES:
                errors.append('对话超过消息数量上限，证据已截断')
                continue
            if text or attachments:
                messages.append({'id': mid, 'session_id': sid, 'role': role, 'created_at': created,
                    'scope': 'current' if current or created >= started_at else 'history',
                    'text': text, 'attachments': attachments})
    for pair in observed:
        if pair not in seen:
            errors.append(f'未找到已关联消息 {pair[1]}')
    messages.sort(key=lambda m: (m['created_at'], m['session_id'], m['id']))
    # Include metadata in the budget too, so the collector cannot emit an event
    # that the consumer rejects instead of retaining partial evidence.
    while messages and len(json.dumps(messages, ensure_ascii=False)) > 120_000:
        messages.pop(0)
        errors.append('对话总容量超过上限，证据已截断')
    usable = any(m['role'] == 'user' and m['scope'] == 'current' and m['text'].strip() for m in messages)
    status = 'ambiguous' if ambiguous else 'partial' if errors and usable else 'missing' if not usable else 'complete'
    return {'version': 1, 'source': 'opencode_export', 'status': status, 'run_id': run_id,
            'started_at': started_at, 'ended_at': ended_at, 'sessions': sessions, 'messages': messages,
            'errors': list(dict.fromkeys(errors))[:30]}
