"""SQLite-backed webhook delivery and review-job outbox."""

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
            return DeliveryRecordResult.QUEUED

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
                status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (repository_id, pull_number, head_sha)
            );
            """
        )