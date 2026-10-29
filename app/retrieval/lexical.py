"""Bounded lexical retrieval for symbols referenced by changed Python lines."""

import io
import keyword
import tokenize
from collections.abc import Mapping
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from app.github.diff import DiffLineKind, FileDiff, parse_unified_diff
from app.retrieval.symbols import PythonSymbol, extract_python_symbols


class RetrievalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_file_bytes: int = Field(default=250_000, ge=1, le=10_000_000)
    max_total_bytes: int = Field(default=30_000, ge=1, le=1_000_000)
    max_results: int = Field(default=8, ge=1, le=100)


class RetrievedSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    content: str
    provenance: str


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identifiers: list[str]
    symbols: list[RetrievedSymbol]
    skipped_paths: list[str]
    total_bytes: int


def retrieve_python_symbols(
    changed_diff: FileDiff,
    repository_files: Mapping[str, str],
    policy: RetrievalPolicy | None = None,
) -> RetrievalResult:
    """Find definitions referenced by added lines, with bounded output."""
    selected_policy = policy or RetrievalPolicy()
    identifiers = _added_line_identifiers(changed_diff)
    candidates: list[PythonSymbol] = []
    skipped_paths: list[str] = []

    for path, source in repository_files.items():
        if path == changed_diff.path or not _is_safe_python_path(path):
            if not _is_safe_python_path(path):
                skipped_paths.append(path)
            continue
        if len(source.encode("utf-8")) > selected_policy.max_file_bytes:
            skipped_paths.append(path)
            continue
        candidates.extend(
            symbol
            for symbol in extract_python_symbols(path, source)
            if symbol.name in identifiers
        )

    candidates.sort(key=lambda symbol: (symbol.path, symbol.start_line, symbol.qualified_name))
    retrieved: list[RetrievedSymbol] = []
    total_bytes = 0
    for symbol in candidates:
        content_bytes = len(symbol.source.encode("utf-8"))
        if len(retrieved) >= selected_policy.max_results:
            skipped_paths.append(symbol.path)
            continue
        if total_bytes + content_bytes > selected_policy.max_total_bytes:
            skipped_paths.append(symbol.path)
            continue
        retrieved.append(
            RetrievedSymbol(
                path=symbol.path,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind.value,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                content=symbol.source,
                provenance=f"{symbol.path}:{symbol.start_line}-{symbol.end_line}",
            )
        )
        total_bytes += content_bytes

    return RetrievalResult(
        identifiers=sorted(identifiers),
        symbols=retrieved,
        skipped_paths=sorted(set(skipped_paths)),
        total_bytes=total_bytes,
    )


def _added_line_identifiers(changed_diff: FileDiff) -> set[str]:
    identifiers: set[str] = set()
    for hunk in changed_diff.hunks:
        for line in hunk.lines:
            if line.kind is not DiffLineKind.ADDITION:
                continue
            try:
                tokens = tokenize.generate_tokens(io.StringIO(line.content).readline)
                identifiers.update(
                    token.string
                    for token in tokens
                    if token.type == tokenize.NAME and not keyword.iskeyword(token.string)
                )
            except (tokenize.TokenError, IndentationError):
                continue
    return identifiers


def _is_safe_python_path(path: str) -> bool:
    posix_path = PurePosixPath(path)
    return (
        bool(path)
        and path == path.strip()
        and "\\" not in path
        and not posix_path.is_absolute()
        and ".." not in posix_path.parts
        and posix_path.suffix.lower() == ".py"
    )


def parse_changed_python_diff(path: str, patch: str) -> FileDiff:
    """Convenience entry point for callers that have a raw patch."""
    return parse_unified_diff(path, patch)