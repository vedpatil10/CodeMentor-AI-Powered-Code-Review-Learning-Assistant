import pytest
from pydantic import ValidationError

from app.review.packet import (
    FilePatchInput,
    FileSkipReason,
    PacketPolicy,
    build_review_packet,
)


def test_packet_preserves_diff_provenance_and_bounded_source_context() -> None:
    file_input = FilePatchInput(
        path="src/handler.py",
        patch="@@ -2,1 +2,1 @@\n-old\n+new",
        source="line one\nline two changed\nline three\nline four",
    )

    packet = build_review_packet(
        [file_input], PacketPolicy(context_radius=1, max_context_lines_per_file=2)
    )

    assert packet.changed_lines == frozenset({("src/handler.py", 2)})
    assert packet.files[0].diff.hunks[0].lines[1].new_line == 2
    assert [line.line_number for line in packet.files[0].source_context] == [1, 2]
    assert [line.provenance for line in packet.files[0].source_context] == [
        "src/handler.py:1",
        "src/handler.py:2",
    ]


def test_packet_skips_deleted_binary_unsupported_and_unsafe_paths() -> None:
    files = [
        FilePatchInput("src/old.py", "", status="removed"),
        FilePatchInput("assets/image.py", "", binary=True),
        FilePatchInput("README.md", "@@ -1 +1 @@\n-old\n+new"),
        FilePatchInput("../outside.py", "@@ -1 +1 @@\n-old\n+new"),
    ]

    packet = build_review_packet(files)

    assert packet.files == ()
    assert [item.reason for item in packet.skipped_files] == [
        FileSkipReason.DELETED,
        FileSkipReason.BINARY,
        FileSkipReason.UNSUPPORTED_LANGUAGE,
        FileSkipReason.INVALID_PATH,
    ]


def test_packet_skips_missing_invalid_and_oversized_patches() -> None:
    files = [
        FilePatchInput("src/missing.py", None),
        FilePatchInput("src/invalid.py", "@@ -1,2 +1,1 @@\n only one line"),
        FilePatchInput("src/large.py", "@@ -1 +1 @@\n-a\n+b", source="x" * 32),
    ]

    packet = build_review_packet(files, PacketPolicy(max_file_bytes=40))

    assert packet.files == ()
    assert [item.reason for item in packet.skipped_files] == [
        FileSkipReason.MISSING_PATCH,
        FileSkipReason.INVALID_PATCH,
        FileSkipReason.FILE_TOO_LARGE,
    ]


def test_packet_enforces_file_and_total_byte_budgets() -> None:
    patch = "@@ -1 +1 @@\n-old\n+new"
    files = [
        FilePatchInput("src/one.py", patch),
        FilePatchInput("src/two.py", patch),
        FilePatchInput("src/three.py", patch),
    ]

    by_count = build_review_packet(files, PacketPolicy(max_files=1))
    by_bytes = build_review_packet(files, PacketPolicy(max_total_bytes=len(patch) * 2 - 1))

    assert len(by_count.files) == 1
    assert [item.reason for item in by_count.skipped_files] == [
        FileSkipReason.FILE_LIMIT,
        FileSkipReason.FILE_LIMIT,
    ]
    assert len(by_bytes.files) == 1
    assert [item.reason for item in by_bytes.skipped_files] == [
        FileSkipReason.TOTAL_BYTE_LIMIT,
        FileSkipReason.TOTAL_BYTE_LIMIT,
    ]


@pytest.mark.parametrize("max_files", [0, 501])
def test_packet_policy_rejects_unbounded_file_limits(max_files: int) -> None:
    with pytest.raises(ValidationError):
        PacketPolicy(max_files=max_files)