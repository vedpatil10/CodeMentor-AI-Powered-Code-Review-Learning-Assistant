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
- **Next:** Milestone 3 (completed).

## Milestone 3: Webhook security primitives

- **Built:** Constant-time HMAC-SHA256 verification over raw request bytes;
    strict supported pull-request event parsing; validation of delivery IDs,
    repository/installation/PR identifiers, repository names, and immutable SHAs;
    safe ignore decisions for unrelated event types and actions.
- **Tests:** `uv run --locked --extra dev pytest` (44 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: validate signed GitHub webhook events` (created after final verification).
- **Next:** Milestone 4 (completed).

## Milestone 4: FastAPI health shell

- **Built:** Runnable FastAPI app factory, `/health/live` and `/health/ready`
    routes, explicit response contracts, and ASGI-level endpoint tests.
    Webhook acceptance is intentionally not exposed until delivery persistence
    and queueing are implemented.
- **Tests:** `uv run --locked --extra dev pytest` (47 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: add FastAPI health endpoints` (created after final verification).
- **Next:** Milestone 5 (completed).

## Milestone 5: Signed webhook intake and local outbox

- **Built:** Environment-backed webhook settings; signed `/webhooks/github`
    endpoint; SQLite-backed delivery records and durable review-job outbox;
    duplicate delivery, repeated PR-head, and conflicting delivery-ID handling.
    Only authenticated, validated pull-request events can create jobs. SQLite is
    a local adapter; production PostgreSQL/Redis wiring remains future work.
- **Tests:** `uv run --locked --extra dev pytest` (57 passed);
    `uv run --locked --extra dev ruff check .` (passed). Includes concurrent
    multi-connection idempotency coverage.
- **Commit:** `feat: persist and deduplicate GitHub webhook jobs` (created after final verification).
- **Next:** Add a worker that claims persisted jobs safely and tracks explicit
    lifecycle states before any GitHub API calls.