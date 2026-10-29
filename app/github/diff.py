"""Parse unified diff patches into explicit old/new line mappings."""

import re
from dataclasses import dataclass
from enum import StrEnum

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffParseError(ValueError):
    """Raised when a patch hunk does not match its declared line counts."""


class DiffLineKind(StrEnum):
    CONTEXT = "context"
    ADDITION = "addition"
    DELETION = "deletion"


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: DiffLineKind
    content: str
    old_line: int | None
    new_line: int | None


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True, slots=True)
class FileDiff:
    path: str
    hunks: tuple[DiffHunk, ...]

    @property
    def changed_lines(self) -> frozenset[tuple[str, int]]:
        """Return added line locations eligible for inline review comments."""
        return frozenset(
            (self.path, line.new_line)
            for hunk in self.hunks
            for line in hunk.lines
            if line.kind is DiffLineKind.ADDITION and line.new_line is not None
        )


def parse_unified_diff(path: str, patch: str) -> FileDiff:
    """Parse a GitHub file patch, preserving line numbers for each hunk."""
    lines = patch.splitlines()
    hunks: list[DiffHunk] = []
    index = 0

    while index < len(lines):
        match = _HUNK_HEADER.match(lines[index])
        if match is None:
            if hunks and lines[index].startswith((" ", "+", "-")):
                raise DiffParseError("unaccounted diff line after completed hunk")
            index += 1
            continue

        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)
        old_line = old_start
        new_line = new_start
        consumed_old = 0
        consumed_new = 0
        hunk_lines: list[DiffLine] = []
        index += 1

        while consumed_old < old_count or consumed_new < new_count:
            if index >= len(lines) or lines[index].startswith("@@ "):
                raise DiffParseError("hunk ended before its declared line counts were met")

            patch_line = lines[index]
            index += 1

            if patch_line.startswith("\\"):
                continue
            if patch_line.startswith(" "):
                if consumed_old >= old_count or consumed_new >= new_count:
                    raise DiffParseError("context line exceeds the declared hunk counts")
                hunk_lines.append(
                    DiffLine(DiffLineKind.CONTEXT, patch_line[1:], old_line, new_line)
                )
                old_line += 1
                new_line += 1
                consumed_old += 1
                consumed_new += 1
            elif patch_line.startswith("+"):
                if consumed_new >= new_count:
                    raise DiffParseError("addition exceeds the declared new-line count")
                hunk_lines.append(
                    DiffLine(DiffLineKind.ADDITION, patch_line[1:], None, new_line)
                )
                new_line += 1
                consumed_new += 1
            elif patch_line.startswith("-"):
                if consumed_old >= old_count:
                    raise DiffParseError("deletion exceeds the declared old-line count")
                hunk_lines.append(
                    DiffLine(DiffLineKind.DELETION, patch_line[1:], old_line, None)
                )
                old_line += 1
                consumed_old += 1
            else:
                raise DiffParseError("unexpected line in unified diff hunk")

        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=tuple(hunk_lines),
            )
        )

    return FileDiff(path=path, hunks=tuple(hunks))