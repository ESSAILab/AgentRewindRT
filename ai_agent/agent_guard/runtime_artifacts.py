"""Conservative host evidence for embedded OpenCode native-library copies.

This proves byte identity to the selected, unchanged executable, not vendor
trust, process attribution, or general safety of arbitrary temporary libraries.
The backend trusts the authenticated host event just as it trusts the diff ref.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from .diff_parser import ChangedFile, parse_unified_diff

LIB_NAME = re.compile(r'^\.[0-9a-f]{16}-[0-9]{8}\.so$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
MAX_BINARY_BYTES = 512 * 1024 * 1024
MAX_LIBRARY_BYTES = 64 * 1024 * 1024
MAX_FILES = 16


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit or before.st_nlink != 1:
            raise ValueError('not a bounded, singly linked regular file')
        data = handle.read(limit + 1)
        if len(data) != before.st_size or _identity(before) != _identity(os.fstat(handle.fileno())):
            raise ValueError('file changed during verification')
        return data


def _elf(data: bytes, *, shared: bool = False) -> bool:
    if len(data) < 64 or data[:4] != b'\x7fELF' or data[4] != 2 or data[5] not in (1, 2):
        return False
    kind = int.from_bytes(data[16:18], 'little' if data[5] == 1 else 'big')
    return kind == 3 if shared else kind in (2, 3)


@dataclass
class RuntimeBaseline:
    binary_path: str
    resolved_binary: str
    workspace: str
    temp_roots: list[str]
    binary_sha256: str = ''
    before: set[str] = field(default_factory=set)
    reason: str = ''

    @classmethod
    def capture(cls, *, binary: str, workspace: str, temp_roots: list[str]):
        baseline = cls(str(Path(binary).absolute()), str(Path(binary).resolve()), str(Path(workspace).resolve()), [])
        try:
            data = _read_regular(Path(baseline.resolved_binary), MAX_BINARY_BYTES)
            if not _elf(data):
                raise ValueError('OpenCode executable is not a standalone ELF')
            baseline.binary_sha256 = hashlib.sha256(data).hexdigest()
            for root in dict.fromkeys(str(Path(p).resolve()) for p in temp_roots if Path(p).is_absolute()):
                if Path(root).is_relative_to(Path(baseline.workspace)):
                    continue
                baseline.temp_roots.append(root)
                with os.scandir(root) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 100_000:
                            raise ValueError('temporary directory inventory too large')
                        if LIB_NAME.fullmatch(entry.name):
                            baseline.before.add(str(Path(root) / entry.name))
        except (OSError, ValueError) as exc:
            baseline.reason = f'启动前运行依赖基线不可用：{type(exc).__name__}'
        return baseline

    def verify(self, *, diff_text: str, metadata: dict, run_id: str) -> dict:
        result = {'version': 1, 'source': 'opencode_embedded_library', 'run_id': run_id,
                  'workspace': self.workspace, 'diff_sha256': hashlib.sha256(diff_text.encode()).hexdigest(),
                  'binary': {'path': self.resolved_binary, 'sha256': self.binary_sha256}, 'files': [], 'errors': []}
        candidates = [f for f in parse_unified_diff(diff_text)
                      if Path(f.path).is_absolute() and LIB_NAME.fullmatch(Path(f.path).name)
                      and str(Path(f.path).parent) in self.temp_roots
                      and not Path(f.path).is_relative_to(Path(self.workspace))]
        if not candidates:
            return result
        if self.reason:
            result['errors'].append(self.reason)
            return result
        try:
            if str(Path(self.binary_path).resolve()) != self.resolved_binary:
                raise ValueError('executable path changed')
            binary = _read_regular(Path(self.resolved_binary), MAX_BINARY_BYTES)
            if hashlib.sha256(binary).hexdigest() != self.binary_sha256:
                raise ValueError('executable content changed')
        except (OSError, ValueError) as exc:
            result['errors'].append(f'运行后 OpenCode 程序核验失败：{type(exc).__name__}')
            return result
        snapshots = metadata.get('snapshots', []) if isinstance(metadata, dict) else []
        changes = [change for snap in snapshots if isinstance(snap, dict)
                   for change in snap.get('changes', []) if isinstance(change, dict)]
        if len(candidates) > MAX_FILES:
            result['errors'].append('运行依赖候选文件超过核验上限，超出部分保留常规审查')
        for changed in candidates[:MAX_FILES]:
            item = {'path': changed.path, 'classification': 'unverified', 'reason': '未通过运行依赖核验'}
            result['files'].append(item)
            try:
                path = Path(changed.path)
                data = _read_regular(path, MAX_LIBRARY_BYTES)
                item.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            content_status='binary' if _elf(data) else 'not_shown')
                path_changes = [c for c in changes if c.get('path') == changed.path]
                if (changed.change_type != 'added' or changed.content_status != 'not_shown'
                        or str(path) in self.before or path.resolve() != path
                        or len(path_changes) != 1 or path_changes[0].get('type') != '+'
                        or path_changes[0].get('size_delta') != len(data)):
                    raise ValueError('not an unambiguous new file in the nono snapshot')
                if not _elf(data, shared=True):
                    raise ValueError('not an ELF shared library')
                offset = binary.find(data)
                if offset < 0:
                    raise ValueError('library differs from the selected executable')
                item.update(classification='verified_runtime_dependency', embedded_offset=offset,
                            reason='本次新增临时动态库与启动前后未变化的 OpenCode 可执行文件内嵌内容逐字节一致')
            except (OSError, ValueError) as exc:
                item['reason'] = f'未通过运行依赖核验，保留常规审查：{type(exc).__name__}'
        return result


def annotate_runtime_artifacts(files: list[ChangedFile], event: dict) -> list[ChangedFile]:
    """Apply only run/diff-bound host proof; malformed or old events fail closed."""
    evidence = event.get('runtime_artifacts')
    if not isinstance(evidence, dict):
        return files
    binary = evidence.get('binary')
    if (evidence.get('version') != 1 or evidence.get('source') != 'opencode_embedded_library'
            or evidence.get('run_id') != event.get('run_id') or evidence.get('workspace') != event.get('workspace')
            or evidence.get('diff_sha256') != event.get('diff_ref', {}).get('sha256')
            or not isinstance(binary, dict) or not SHA256.fullmatch(str(binary.get('sha256', '')))):
        return files
    proofs = evidence.get('files')
    if not isinstance(proofs, list) or len(proofs) > MAX_FILES:
        return files
    result = []
    for changed in files:
        items = [p for p in proofs if isinstance(p, dict) and p.get('path') == changed.path]
        if len(items) != 1:
            result.append(changed)
            continue
        proof = items[0]
        size = proof.get('size_bytes')
        digest = proof.get('sha256')
        if (type(size) is not int or not 0 < size <= MAX_LIBRARY_BYTES
                or not isinstance(digest, str) or not SHA256.fullmatch(digest)):
            result.append(changed)
            continue
        changed = replace(changed, size_bytes=size, sha256=digest,
                          content_status='binary' if proof.get('content_status') == 'binary' else changed.content_status)
        offset = proof.get('embedded_offset')
        if (proof.get('classification') == 'verified_runtime_dependency' and not evidence.get('errors')
                and type(offset) is int and 0 <= offset < MAX_BINARY_BYTES
                and changed.change_type == 'added' and changed.content_status == 'binary'
                and Path(changed.path).is_absolute() and LIB_NAME.fullmatch(Path(changed.path).name)
                and not Path(changed.path).is_relative_to(Path(event['workspace']))):
            changed = replace(changed, review_scope='runtime_dependency',
                              verification_reason=proof.get('reason', ''), source_binary_sha256=binary['sha256'])
        result.append(changed)
    return result


def finalize_file_evidence(result, files: list[ChangedFile]):
    """Keep runtime evidence visible and prevent an allow based on missing bytes."""
    from .adjudicator import _max_risk
    runtime = [f for f in files if f.review_scope == 'runtime_dependency']
    unknown = [f for f in files if f.review_scope != 'runtime_dependency' and f.content_status != 'text']
    if runtime:
        note = f'另有 {len(runtime)} 个新增临时动态库已核验为 OpenCode 内嵌内容的副本，作为运行依赖保留记录，不单独据此判定任务越界。'
        result = replace(result, summary=result.summary + '\n' + note,
                         findings=[*result.findings, *[{'path': f.path, 'category': 'runtime_dependency',
                            'summary': f.verification_reason, 'sha256': f.sha256, 'size_bytes': f.size_bytes} for f in runtime]])
    if unknown:
        reason = '以下文件未展示内容，文本增删为零不代表空文件或无变化，需人工核验：' + '、'.join(f.path for f in unknown)
        result = replace(result, summary=reason + '\n' + result.summary,
                         risk_level=_max_risk(result.risk_level, 'medium'),
                         verdict='needs_human_review' if result.verdict in ('allow','warn') else result.verdict,
                         recommended_action='ask_user' if result.recommended_action == 'accept' else result.recommended_action,
                         intent_alignment='unknown' if result.intent_alignment == 'aligned' else result.intent_alignment,
                         out_of_intent=None if result.intent_alignment == 'aligned' else result.out_of_intent,
                         intent_alignment_reason=reason if result.intent_alignment == 'aligned' else result.intent_alignment_reason)
    return result
