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
- **Next:** Milestone 6 (completed).

## Milestone 6: Atomic worker claims and job lifecycle

- **Built:** Atomic queued-job claims, attempt counting, explicit review states,
    validated transitions, sanitized failure codes, and a durable transition
    audit trail. Added a compatibility migration that preserves queued records
    from the earlier SQLite schema.
- **Tests:** `uv run --locked --extra dev pytest` (62 passed);
    `uv run --locked --extra dev ruff check .` (passed). Includes concurrent
    worker-claim and legacy-schema regression tests.
- **Commit:** `feat: add atomic review job state machine` (created after final verification).
- **Next:** Milestone 7 (completed).

## Milestone 7: Bounded local review packets

- **Built:** A deterministic packet builder for Python patches with path and
    file filtering, parsed changed-line references, source-context provenance,
    per-file/total byte limits, context-line caps, and skipped-file reason codes.
    The token count is an estimate based on input bytes, not provider usage.
- **Tests:** `uv run --locked --extra dev pytest` (68 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: build bounded review packets` (created after final verification).
- **Next:** Milestone 8 (completed).

## Milestone 8: Structured candidate validation

- **Built:** A provider protocol and review runner that always applies a
    deterministic gate. Findings must cite a reviewed file, an added line, and
    evidence present in the packet; severity/confidence thresholds, duplicates,
    and inline comment limits are enforced before returning accepted candidates.
    Rejections retain machine-readable reason codes for evaluation.
- **Tests:** `uv run --locked --extra dev pytest` (79 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: validate structured review findings` (created after final verification).
- **Next:** Milestone 9 (completed).

## Milestone 9: Structured model adapter and offline runner

- **Built:** OpenAI Responses API adapter using strict Pydantic parsing,
    bounded request time/output tokens, prompt-injection framing, and sanitized
    handling for refusal, incomplete, missing-output, and provider-error cases.
    Made all review-result fields required for strict schema compatibility.
    Added `codementor-review-fixture` with one evidence-backed defect fixture,
    one clean-change abstention fixture, and rejected-finding reporting.
- **Tests:** `uv run --locked --extra dev pytest` (91 passed);
    `uv run --locked --extra dev ruff check .` (passed). CLI smoke test accepted
    one finding and returned zero findings for the clean fixture.
- **API verification:** Provider behavior tested with mocks; no live model call
    was made because no API key was configured.
- **Commit:** `feat: add structured model adapter and fixture runner`, followed
    by `fix: require findings in review schema` (both verified and pushed).
- **Next:** Milestone 10 (completed).

## Milestone 10: Local live-review command

- **Built:** `codementor-review-local` loads saved diff inputs, invokes the
    configured provider, runs the same deterministic validation gate, and emits
    a JSON report. Reused the shared fixture packet builder; missing credentials
    fail with a sanitized error before any model request. The offline fixture
    command remains independent of provider credentials.
- **Tests:** `uv run --locked --extra dev pytest -q` (95 passed);
    `uv run --locked --extra dev ruff check .` (passed). CLI missing-key smoke
    test returned `missing_api_key` without making a network request.
- **Commit:** `feat: add local live review command` (created after final verification).
- **Next:** Milestone 11 (completed).

## Milestone 11: Python AST and lexical retrieval

- **Built:** Non-executing AST extraction for nested classes/functions and
    lexical lookup of definitions referenced by identifiers on added diff lines.
    Retrieved snippets carry path/line provenance; unsafe paths, syntax errors,
    oversized files, excessive result counts, and context byte limits are
    handled explicitly.
- **Tests:** `uv run --locked --extra dev pytest -q` (101 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: add Python symbol retrieval` (created after final verification).
- **Next:** Milestone 12 (completed).

## Milestone 12: Retrieval wired into review packets

- **Built:** Optional repository files now flow through packet construction;
    referenced symbols and line provenance are included in the OpenAI request.
    The deterministic validator checks `retrieved_code` evidence against those
    exact snippets. Without repository context, packets remain diff-only.
- **Tests:** `uv run --locked --extra dev pytest -q` (104 passed);
    `uv run --locked --extra dev ruff check .` (passed).
- **Commit:** `feat: include retrieved symbols in review packets` (created after final verification).
- **Next:** Build a labeled evaluation harness for accepted/rejected findings,
    then add read-only GitHub PR fetching against immutable head SHAs.

## Milestone 13: Evaluation harness and audit hardening

- **Built:** A labeled offline regression runner for supported, clean, and
    unsupported-evidence cases. Empty datasets and duplicate case IDs are
    rejected; fixture paths are confined to the tests tree. Packet byte/token
    estimates now include retrieved source, and readiness probes SQLite before
    returning ready.
- **GitHub visibility:** `.gitignore` and `.env.example` are removed from the
    current branch tree but retained locally and excluded through `.git/info/exclude`.
    No actual `.env` is present or tracked. Prior commit history is unchanged;
    these files contain only ignore patterns and blank placeholders.
- **Tests:** `uv run --locked --extra dev pytest -q` (111 passed);
    `uv run --locked --extra dev ruff check .` (passed). Credential-pattern scan
    found no matches outside ignored dependency/build directories.
- **Commit:** `fix: harden evaluation and review budgets` (created after final verification).
- **Next:** Implement read-only GitHub PR fetching, capture immutable base/head
    SHAs, and normalize changed file patches without publishing comments.