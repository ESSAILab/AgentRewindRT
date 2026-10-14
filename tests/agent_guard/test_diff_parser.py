from __future__ import annotations

from ai_agent.agent_guard.diff_parser import parse_unified_diff


def test_parse_nono_unified_diff_without_git_header():
    diff = """--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""

    files = parse_unified_diff(diff)

    assert len(files) == 1
    assert files[0].path == "README.md"
    assert files[0].added_lines == 1
    assert files[0].deleted_lines == 1


def test_parse_nono_multi_file_unified_diff_without_git_headers():
    diff = """--- /repo/policy.yaml
+++ b//repo/policy.yaml
@@ -1 +1 @@
-mode: observe
+mode: enforce
--- a//repo/service.py
+++ b//repo/service.py
@@ -1 +1 @@
-return 'old'
+return 'new'
"""

    files = parse_unified_diff(diff)

    assert [file.path for file in files] == ["/repo/policy.yaml", "/repo/service.py"]
    assert [file.added_lines for file in files] == [1, 1]
    assert [file.deleted_lines for file in files] == [1, 1]


def test_header_only_creation_is_content_unavailable_not_empty():
    changed = parse_unified_diff('--- /dev/null\n+++ b//tmp/.1234567890abcdef-00000000.so\n')[0]
    assert changed.change_type == 'added'
    assert changed.content_status == 'not_shown'


def test_nono_repeated_display_lines_are_not_counted_as_another_hunk():
    changed = parse_unified_diff('--- /dev/null\n+++ b/file.md\n@@ -0,0 +1,3 @@\n+one\n+two\n+three\n\n+one\n+two\n+three\n')[0]
    assert changed.added_lines == 3
    assert changed.diff.count('+one') == 1


def test_unexpected_trailing_change_is_not_discarded_as_preview():
    changed = parse_unified_diff('--- /dev/null\n+++ b/file.md\n@@ -0,0 +1 @@\n+one\n\n+unexpected\n')[0]
    assert '+unexpected' in changed.diff
    assert changed.added_lines == 2


def test_deleted_and_multiple_hunks_remain_intact():
    diff = '--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n@@ -10,2 +10,2 @@\n same\n-old2\n+new2\n'
    changed = parse_unified_diff(diff)[0]
    assert changed.added_lines == 2 and changed.deleted_lines == 2
    assert changed.change_type == 'modified'
    removed = parse_unified_diff('--- a/file\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n')[0]
    assert removed.change_type == 'deleted' and removed.path == 'file'


def test_git_metadata_phrases_in_content_do_not_change_file_type():
    for phrase in ('new file mode 100644', 'deleted file mode 100644'):
        changed = parse_unified_diff(f'--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+Document {phrase}\n')[0]
        assert changed.change_type == 'modified'


def test_modified_file_exact_nono_preview_is_not_counted_twice():
    body = [' # Smoke target', ' ', ' This file is intentionally incomplete.', '+', '+## Agent Result', '+', '+This file was modified by a real opencode agent under nono.']
    diff = '\n'.join(['--- a/README.md', '+++ b/README.md', '@@ -1,3 +1,7 @@', *body, '', *body, ''])
    changed = parse_unified_diff(diff)[0]
    assert changed.added_lines == 4
    assert changed.deleted_lines == 0
    assert changed.diff.count('+## Agent Result') == 1


def test_modified_file_nonidentical_preview_preserves_evidence():
    diff = '--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n\n-old\n+unexpected\n'
    changed = parse_unified_diff(diff)[0]
    assert '+unexpected' in changed.diff
    assert changed.added_lines == 2


def test_identical_real_hunks_are_not_deduplicated():
    diff = '--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n@@ -8 +8 @@\n-old\n+new\n'
    changed = parse_unified_diff(diff)[0]
    assert changed.added_lines == changed.deleted_lines == 2
