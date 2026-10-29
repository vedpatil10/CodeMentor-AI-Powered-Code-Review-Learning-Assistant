import pytest

from app.github.diff import DiffLineKind, DiffParseError, parse_unified_diff


def test_parser_tracks_context_addition_and_deletion_lines() -> None:
    patch = """@@ -4,2 +4,3 @@
+before
-old
+replacement
 after"""

    file_diff = parse_unified_diff("src/handler.py", patch)
    hunk_lines = file_diff.hunks[0].lines

    assert [(line.kind, line.old_line, line.new_line) for line in hunk_lines] == [
        (DiffLineKind.ADDITION, None, 4),
        (DiffLineKind.DELETION, 4, None),
        (DiffLineKind.ADDITION, None, 5),
        (DiffLineKind.CONTEXT, 5, 6),
    ]
    assert file_diff.changed_lines == frozenset(
        {("src/handler.py", 4), ("src/handler.py", 5)}
    )


def test_parser_handles_zero_context_addition_and_rename_destination() -> None:
    patch = """@@ -0,0 +1,2 @@
+first
+second"""

    file_diff = parse_unified_diff("src/new_name.py", patch)

    assert file_diff.path == "src/new_name.py"
    assert file_diff.changed_lines == frozenset(
        {("src/new_name.py", 1), ("src/new_name.py", 2)}
    )


def test_parser_tracks_line_numbers_across_multiple_hunks() -> None:
    patch = """@@ -1 +1,2 @@
 context
+first addition
\\ No newline at end of file
@@ -10 +11,2 @@
 another context
+second addition"""

    file_diff = parse_unified_diff("src/handler.py", patch)

    assert file_diff.changed_lines == frozenset(
        {("src/handler.py", 2), ("src/handler.py", 12)}
    )


def test_parser_handles_deletion_only_hunk_without_inline_lines() -> None:
    patch = """@@ -8,2 +8,0 @@
-removed one
-removed two"""

    file_diff = parse_unified_diff("src/handler.py", patch)

    assert [line.old_line for line in file_diff.hunks[0].lines] == [8, 9]
    assert file_diff.changed_lines == frozenset()


def test_parser_handles_empty_or_missing_patch() -> None:
    assert parse_unified_diff("image.png", "").hunks == ()
    assert parse_unified_diff("image.png", "Binary files differ").changed_lines == frozenset()


@pytest.mark.parametrize(
    "patch",
    [
        "@@ -1,2 +1,1 @@\n only one old line",
        "@@ -1,0 +1,1 @@\n+one\n+extra",
        "@@ -1,1 +1,0 @@\n@@ -3,1 +3,1 @@",
    ],
)
def test_parser_rejects_hunks_that_do_not_match_declared_counts(patch: str) -> None:
    with pytest.raises(DiffParseError):
        parse_unified_diff("src/handler.py", patch)