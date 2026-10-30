"""Build bounded review packets from local or GitHub-provided file patches."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from app.github.diff import DiffParseError, FileDiff, parse_unified_diff
from app.retrieval.lexical import RetrievalPolicy, RetrievedSymbol, retrieve_python_symbols


class FileSkipReason(StrEnum):
    DELETED = "deleted"
    BINARY = "binary"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    INVALID_PATH = "invalid_path"
    MISSING_PATCH = "missing_patch"
    INVALID_PATCH = "invalid_patch"
    FILE_TOO_LARGE = "file_too_large"
    FILE_LIMIT = "file_limit"
    TOTAL_BYTE_LIMIT = "total_byte_limit"


@dataclass(frozen=True, slots=True)
class FilePatchInput:
    path: str
    patch: str | None
    source: str | None = None
    status: str = "modified"
    binary: bool = False


@dataclass(frozen=True, slots=True)
class SourceLine:
    line_number: int
    content: str
    provenance: str


@dataclass(frozen=True, slots=True)
class ReviewFilePacket:
    path: str
    patch: str
    diff: FileDiff
    source_context: tuple[SourceLine, ...]
    input_bytes: int


@dataclass(frozen=True, slots=True)
class SkippedFile:
    path: str
    reason: FileSkipReason


@dataclass(frozen=True, slots=True)
class ReviewPacket:
    files: tuple[ReviewFilePacket, ...]
    retrieved_symbols: tuple[RetrievedSymbol, ...]
    retrieval_skipped_paths: tuple[str, ...]
    skipped_files: tuple[SkippedFile, ...]
    changed_lines: frozenset[tuple[str, int]]
    input_bytes: int
    estimated_tokens: int


class PacketPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_files: int = Field(default=40, ge=1, le=500)
    max_file_bytes: int = Field(default=150_000, ge=1, le=10_000_000)
    max_total_bytes: int = Field(default=1_000_000, ge=1, le=50_000_000)
    context_radius: int = Field(default=8, ge=0, le=100)
    max_context_lines_per_file: int = Field(default=200, ge=0, le=2000)


def build_review_packet(
    files: Iterable[FilePatchInput],
    policy: PacketPolicy | None = None,
    repository_files: Mapping[str, str] | None = None,
    retrieval_policy: RetrievalPolicy | None = None,
) -> ReviewPacket:
    """Filter files and collect bounded diff/context with explicit provenance."""
    selected_policy = policy or PacketPolicy()
    included: list[ReviewFilePacket] = []
    skipped: list[SkippedFile] = []
    total_bytes = 0
    retrieved_symbols: list[RetrievedSymbol] = []
    retrieval_skipped_paths: set[str] = set()
    selected_retrieval_policy = retrieval_policy or RetrievalPolicy()

    for file_input in files:
        skip_reason = _skip_reason(file_input)
        if skip_reason is not None:
            skipped.append(SkippedFile(file_input.path, skip_reason))
            continue
        if len(included) >= selected_policy.max_files:
            skipped.append(SkippedFile(file_input.path, FileSkipReason.FILE_LIMIT))
            continue

        patch = file_input.patch
        if patch is None:
            skipped.append(SkippedFile(file_input.path, FileSkipReason.MISSING_PATCH))
            continue
        input_bytes = len(patch.encode("utf-8")) + len((file_input.source or "").encode("utf-8"))
        if input_bytes > selected_policy.max_file_bytes:
            skipped.append(SkippedFile(file_input.path, FileSkipReason.FILE_TOO_LARGE))
            continue
        if total_bytes + input_bytes > selected_policy.max_total_bytes:
            skipped.append(SkippedFile(file_input.path, FileSkipReason.TOTAL_BYTE_LIMIT))
            continue

        try:
            diff = parse_unified_diff(file_input.path, patch)
        except DiffParseError:
            skipped.append(SkippedFile(file_input.path, FileSkipReason.INVALID_PATCH))
            continue

        if repository_files is not None and file_input.path.lower().endswith(".py"):
            remaining_results = selected_retrieval_policy.max_results - len(retrieved_symbols)
            retrieved_bytes = sum(
                len(symbol.content.encode("utf-8")) for symbol in retrieved_symbols
            )
            packet_remaining_bytes = (
                selected_policy.max_total_bytes - total_bytes - input_bytes
            )
            retrieval_remaining_bytes = (
                selected_retrieval_policy.max_total_bytes - retrieved_bytes
            )
            remaining_bytes = min(packet_remaining_bytes, retrieval_remaining_bytes)
            if remaining_results > 0 and remaining_bytes > 0:
                current_retrieval_policy = selected_retrieval_policy.model_copy(
                    update={"max_results": remaining_results, "max_total_bytes": remaining_bytes}
                )
                retrieved = retrieve_python_symbols(
                    diff, repository_files, current_retrieval_policy
                )
                known_symbols = {
                    (symbol.path, symbol.qualified_name, symbol.start_line)
                    for symbol in retrieved_symbols
                }
                new_symbols = [
                    symbol
                    for symbol in retrieved.symbols
                    if (symbol.path, symbol.qualified_name, symbol.start_line) not in known_symbols
                ]
                retrieved_symbols.extend(new_symbols)
                total_bytes += sum(
                    len(symbol.content.encode("utf-8")) for symbol in new_symbols
                )
                retrieval_skipped_paths.update(retrieved.skipped_paths)

        included.append(
            ReviewFilePacket(
                path=file_input.path,
                patch=patch,
                diff=diff,
                source_context=_select_source_context(
                    file_input.path,
                    file_input.source,
                    diff,
                    selected_policy.context_radius,
                    selected_policy.max_context_lines_per_file,
                ),
                input_bytes=input_bytes,
            )
        )
        total_bytes += input_bytes

    changed_lines = frozenset(
        changed_line
        for file_packet in included
        for changed_line in file_packet.diff.changed_lines
    )
    return ReviewPacket(
        files=tuple(included),
        retrieved_symbols=tuple(retrieved_symbols),
        retrieval_skipped_paths=tuple(sorted(retrieval_skipped_paths)),
        skipped_files=tuple(skipped),
        changed_lines=changed_lines,
        input_bytes=total_bytes,
        estimated_tokens=(total_bytes + 3) // 4,
    )


def _skip_reason(file_input: FilePatchInput) -> FileSkipReason | None:
    path = PurePosixPath(file_input.path)
    if (
        not file_input.path
        or file_input.path != file_input.path.strip()
        or "\\" in file_input.path
        or path.is_absolute()
        or ".." in path.parts
    ):
        return FileSkipReason.INVALID_PATH
    if file_input.status == "removed":
        return FileSkipReason.DELETED
    if file_input.binary:
        return FileSkipReason.BINARY
    if path.suffix.lower() != ".py":
        return FileSkipReason.UNSUPPORTED_LANGUAGE
    return None


def _select_source_context(
    path: str,
    source: str | None,
    diff: FileDiff,
    radius: int,
    max_lines: int,
) -> tuple[SourceLine, ...]:
    if not source or max_lines == 0:
        return ()

    source_lines = source.splitlines()
    changed_line_numbers = sorted(
        line
        for changed_path, line in diff.changed_lines
        if changed_path == path and line <= len(source_lines)
    )
    candidate_lines: set[int] = set()
    for changed_line in changed_line_numbers:
        start = max(1, changed_line - radius)
        end = min(len(source_lines), changed_line + radius)
        candidate_lines.update(range(start, end + 1))

    prioritized = sorted(
        candidate_lines,
        key=lambda line: (
            min(abs(line - changed_line) for changed_line in changed_line_numbers),
            line,
        ),
    )[:max_lines]
    return tuple(
        SourceLine(
            line_number=line,
            content=source_lines[line - 1],
            provenance=f"{path}:{line}",
        )
        for line in sorted(prioritized)
    )