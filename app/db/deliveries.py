"""SQLite-backed webhook delivery and review-job outbox."""

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DeliveryConflictError(ValueError):
    """Raised when one delivery ID is reused with a different payload."""


class DeliveryRecordResult(StrEnum):
    QUEUED = "queued"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    DUPLICATE_HEAD = "duplicate_head"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"


class InvalidJobTransitionError(ValueError):
    """Raised when a job transition is not allowed by the state machine."""


class JobNotFoundError(LookupError):
    """Raised when a job ID does not exist in the outbox."""


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    delivery_id: str
    event_name: str
    repository_id: int
    installation_id: int
    pull_number: int
    base_sha: str
    head_sha: str
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewJob:
    id: int
    repository_id: int
    pull_number: int
    head_sha: str
    base_sha: str
    state: JobState
    attempts: int


_ALLOWED_TRANSITIONS = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.VALIDATING, JobState.FAILED, JobState.STALE, JobState.CANCELLED}
    ),
    JobState.VALIDATING: frozenset(
        {
            JobState.PUBLISHING,
            JobState.COMPLETED,
            JobState.PARTIAL,
            JobState.FAILED,
            JobState.STALE,
            JobState.CANCELLED,
        }
    ),
    JobState.PUBLISHING: frozenset(
        {JobState.COMPLETED, JobState.PARTIAL, JobState.FAILED, JobState.STALE, JobState.CANCELLED}
    ),
    JobState.COMPLETED: frozenset(),
    JobState.PARTIAL: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.STALE: frozenset(),
    JobState.CANCELLED: frozenset(),
}
_FAILURE_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


class DeliveryStore:
    """Persist accepted webhook deliveries and deduplicated review jobs."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def record(self, delivery: DeliveryRecord) -> DeliveryRecordResult:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._database_path, timeout=10) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            self._create_tables(connection)

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_deliveries (
                    delivery_id, event_name, repository_id, installation_id,
                    pull_number, base_sha, head_sha, payload_sha256, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'received')
                """,
                (
                    delivery.delivery_id,
                    delivery.event_name,
                    delivery.repository_id,
                    delivery.installation_id,
                    delivery.pull_number,
                    delivery.base_sha,
                    delivery.head_sha,
                    delivery.payload_sha256,
                ),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT payload_sha256 FROM webhook_deliveries WHERE delivery_id = ?",
                    (delivery.delivery_id,),
                ).fetchone()
                if existing is not None and existing[0] != delivery.payload_sha256:
                    raise DeliveryConflictError("delivery ID was reused with a different payload")
                return DeliveryRecordResult.DUPLICATE_DELIVERY

            job_cursor = connection.execute(
                """
                INSERT OR IGNORE INTO review_jobs (
                    repository_id, pull_number, head_sha, base_sha, status
                ) VALUES (?, ?, ?, ?, 'queued')
                """,
                (
                    delivery.repository_id,
                    delivery.pull_number,
                    delivery.head_sha,
                    delivery.base_sha,
                ),
            )
            if job_cursor.rowcount == 0:
                connection.execute(
                    "UPDATE webhook_deliveries SET status = 'deduplicated' WHERE delivery_id = ?",
                    (delivery.delivery_id,),
                )
                return DeliveryRecordResult.DUPLICATE_HEAD

            connection.execute(
                "UPDATE webhook_deliveries SET status = 'queued' WHERE delivery_id = ?",
                (delivery.delivery_id,),
            )
            job_id = connection.execute(
                """
                SELECT id FROM review_jobs
                WHERE repository_id = ? AND pull_number = ? AND head_sha = ?
                """,
                (delivery.repository_id, delivery.pull_number, delivery.head_sha),
            ).fetchone()[0]
            self._record_job_event(connection, job_id, None, JobState.QUEUED, None)
            return DeliveryRecordResult.QUEUED

    def claim_next_job(self) -> ReviewJob | None:
        """Atomically claim the oldest queued job for one worker."""
        if not self._database_path.exists():
            return None
        with sqlite3.connect(self._database_path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, repository_id, pull_number, head_sha, base_sha, attempts
                FROM review_jobs
                WHERE status = ?
                ORDER BY id
                LIMIT 1
                """,
                (JobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None

            job_id = row[0]
            connection.execute(
                """
                UPDATE review_jobs
                SET status = ?, attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (JobState.RUNNING.value, job_id, JobState.QUEUED.value),
            )
            self._record_job_event(
                connection, job_id, JobState.QUEUED, JobState.RUNNING, None
            )
            return ReviewJob(
                id=job_id,
                repository_id=row[1],
                pull_number=row[2],
                head_sha=row[3],
                base_sha=row[4],
                state=JobState.RUNNING,
                attempts=row[5] + 1,
            )

    def transition_job(
        self,
        job_id: int,
        new_state: JobState,
        failure_code: str | None = None,
    ) -> JobState:
        """Validate, persist, and audit a review-job state transition."""
        if failure_code is not None and _FAILURE_CODE_PATTERN.fullmatch(failure_code) is None:
            raise ValueError("failure_code must be a short sanitized identifier")

        with sqlite3.connect(self._database_path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM review_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise JobNotFoundError(f"review job {job_id} does not exist")

            current_state = JobState(row[0])
            if new_state not in _ALLOWED_TRANSITIONS[current_state]:
                raise InvalidJobTransitionError(
                    f"cannot transition review job from {current_state} to {new_state}"
                )

            connection.execute(
                """
                UPDATE review_jobs
                SET status = ?, last_error_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_state.value, failure_code, job_id),
            )
            self._record_job_event(connection, job_id, current_state, new_state, failure_code)
            return new_state

    def counts(self) -> tuple[int, int]:
        """Return delivery and queued-job counts for tests and diagnostics."""
        if not self._database_path.exists():
            return 0, 0
        with sqlite3.connect(self._database_path, timeout=10) as connection:
            delivery_count = connection.execute(
                "SELECT COUNT(*) FROM webhook_deliveries"
            ).fetchone()[0]
            job_count = connection.execute("SELECT COUNT(*) FROM review_jobs").fetchone()[0]
        return delivery_count, job_count

    @staticmethod
    def _create_tables(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                delivery_id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                repository_id INTEGER NOT NULL,
                installation_id INTEGER NOT NULL,
                pull_number INTEGER NOT NULL,
                base_sha TEXT NOT NULL,
                head_sha TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('received', 'queued', 'deduplicated')),
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS review_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                pull_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (repository_id, pull_number, head_sha)
            );
            """
        )

        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'review_jobs'"
        ).fetchone()[0]
        normalized_schema = " ".join(schema.lower().split())
        if re.search(r"check\s*\(\s*status\s+in\s*\(", normalized_schema):
            DeliveryStore._migrate_legacy_job_table(connection)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(review_jobs)")}
        for column, definition in (
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error_code", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE review_jobs ADD COLUMN {column} {definition}")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                previous_state TEXT,
                next_state TEXT NOT NULL,
                failure_code TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES review_jobs(id)
            )
            """
        )

    @staticmethod
    def _migrate_legacy_job_table(connection: sqlite3.Connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(review_jobs)")}
        attempts = "attempts" if "attempts" in columns else "0"
        error_code = "last_error_code" if "last_error_code" in columns else "NULL"
        updated_at = "updated_at" if "updated_at" in columns else "created_at"
        connection.execute("ALTER TABLE review_jobs RENAME TO review_jobs_legacy")
        connection.execute(
            """
            CREATE TABLE review_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                pull_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (repository_id, pull_number, head_sha)
            )
            """
        )
        connection.execute(
            f"""
            INSERT INTO review_jobs (
                id, repository_id, pull_number, head_sha, base_sha, status,
                attempts, last_error_code, created_at, updated_at
            )
            SELECT id, repository_id, pull_number, head_sha, base_sha, status,
                   {attempts}, {error_code}, created_at, {updated_at}
            FROM review_jobs_legacy
            """
        )
        connection.execute("DROP TABLE review_jobs_legacy")

    @staticmethod
    def _record_job_event(
        connection: sqlite3.Connection,
        job_id: int,
        previous_state: JobState | None,
        next_state: JobState,
        failure_code: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO review_job_events (job_id, previous_state, next_state, failure_code)
            VALUES (?, ?, ?, ?)
            """,
            (
                job_id,
                previous_state.value if previous_state is not None else None,
                next_state.value,
                failure_code,
            ),
        )