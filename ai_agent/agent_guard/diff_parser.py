from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change_type: str
    added_lines: int
    deleted_lines: int
    diff: str
    content_status: str = "text"
    review_scope: str = "task_change"
    size_bytes: int | None = None
    sha256: str = ""
    verification_reason: str = ""
    source_binary_sha256: str = ""


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current_path: str | None = None
    current_lines: list[str] = []
    pending_old_path: str | None = None

    def flush_current() -> None:
        nonlocal current_path, current_lines
        if current_path is None:
            return
        # Some nono versions repeat the file preview after valid hunks.
        # Remove only an exact echo of completed hunk bodies, retaining
        # unexpected trailing changes and the full raw evidence in diff storage.
        # Legacy headerless hunks remain supported.
        lines = []
        remaining_old = remaining_new = 0
        bounded_hunk = False
        hunk_body: list[str] = []
        for index, line in enumerate(current_lines):
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                bounded_hunk = True
                remaining_old = int(match[2]) if match[2] is not None else 1
                remaining_new = int(match[4]) if match[4] is not None else 1
            elif bounded_hunk and not (remaining_old or remaining_new):
                # Empty separators are not hunk context: a context blank line
                # is a literal space and must participate in exact comparison.
                tail = list(current_lines[index:])
                while tail and tail[0] == "":
                    tail.pop(0)
                while tail and tail[-1] == "":
                    tail.pop()
                if hunk_body and tail == hunk_body:
                    break
            elif bounded_hunk:
                if line.startswith(("+", "-", " ")) or line == "\\ No newline at end of file":
                    hunk_body.append(line)
                if line.startswith("+"):
                    remaining_new -= 1
                elif line.startswith("-"):
                    remaining_old -= 1
                elif line.startswith(" "):
                    remaining_old -= 1
                    remaining_new -= 1
            lines.append(line)
        file_diff = "\n".join(lines)
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        deleted = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        change_type = "modified"
        if any(line == "--- /dev/null" for line in lines) or any(line.startswith("new file mode ") for line in lines):
            change_type = "added"
        elif any(line == "+++ /dev/null" for line in lines) or any(line.startswith("deleted file mode ") for line in lines):
            change_type = "deleted"
        content_status = "text" if any(line.startswith("@@") for line in lines) or added or deleted else "not_shown"
        if any(line.startswith(("Binary files ", "GIT binary patch")) for line in lines):
            content_status = "binary"
        files.append(
            ChangedFile(
                path=current_path,
                change_type=change_type,
                added_lines=added,
                deleted_lines=deleted,
                diff=file_diff,
                content_status=content_status,
            )
        )
        current_path = None
        current_lines = []

    def normalize_path(raw: str) -> str:
        path = raw.strip()
        if "\t" in path:
            path = path.split("\t", 1)[0]
        if path.startswith("a/") or path.startswith("b/"):
            return path[2:]
        return path

    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    for raw_line in diff_text.splitlines():
        line = ansi_re.sub("", raw_line)
        if line.startswith("diff --git "):
            flush_current()
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3]
                current_path = b_path[2:] if b_path.startswith("b/") else b_path
            else:
                current_path = "unknown"
            current_lines = [line]
        elif line.startswith("--- "):
            if current_path is not None and current_lines and not current_lines[0].startswith("diff --git "):
                flush_current()
            if current_path is not None:
                current_lines.append(line)
            pending_old_path = normalize_path(line[4:])
        elif line.startswith("+++ "):
            if current_path is not None:
                current_lines.append(line)
                continue
            current_path = normalize_path(line[4:])
            if current_path == "/dev/null" and pending_old_path:
                current_path = pending_old_path
            current_lines = []
            if pending_old_path:
                current_lines.append(f"--- {pending_old_path}")
            current_lines.append(line)
        elif current_path is not None:
            current_lines.append(line)

    flush_current()
    return files


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4)
