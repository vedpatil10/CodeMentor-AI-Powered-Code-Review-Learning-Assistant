# CodeMentor Build Progress

This log records each completed implementation checkpoint, its verification,
and the commit created for that checkpoint. Work is built in small vertical
slices; a checkpoint is not marked complete until its focused tests pass.

## Milestone 1: Domain foundation

- **Built:** Python package configuration, safe local-development ignores,
  validated finding/result contracts, bounded review policy, and an inline
  publication gate requiring an eligible finding on a changed line.
- **Tests:** `uv run --extra dev pytest` (14 passed); `uv run --extra dev ruff check .` (passed).
- **Commit:** `feat: add domain foundation` (created after final verification).
- **Next:** Milestone 2 (completed).

## Milestone 2: Unified diff mapping

- **Built:** A per-file unified-diff parser with immutable hunk/line records,
    old/new line mapping, changed-line extraction, and explicit rejection of
    malformed or overlong hunks. Handles empty patches and no-newline markers.
- **Tests:** `uv run --locked --extra dev pytest` (22 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: parse review diff line mappings` (created after final verification).
- **Next:** Add webhook event validation and raw-body signature verification.