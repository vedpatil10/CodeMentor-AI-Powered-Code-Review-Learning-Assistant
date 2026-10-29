import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.deliveries import (
    DeliveryRecord,
    DeliveryRecordResult,
    DeliveryStore,
    InvalidJobTransitionError,
    JobState,
)


def record_job(
    store: DeliveryStore,
    *,
    delivery_id: str = "delivery-1",
    pull_number: int = 17,
    head_sha: str = "a" * 40,
) -> DeliveryRecordResult:
    return store.record(
        DeliveryRecord(
            delivery_id=delivery_id,
            event_name="pull_request",
            repository_id=123,
            installation_id=456,
            pull_number=pull_number,
            base_sha="b" * 40,
            head_sha=head_sha,
            payload_sha256=delivery_id,
        )
    )


def test_workers_atomically_claim_one_queued_job(tmp_path) -> None:
    store = DeliveryStore(tmp_path / "jobs.sqlite3")
    record_job(store)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: store.claim_next_job(), range(2)))

    claimed_jobs = [claim for claim in claims if claim is not None]
    assert len(claimed_jobs) == 1
    assert claimed_jobs[0].state is JobState.RUNNING
    assert claimed_jobs[0].attempts == 1


def test_job_state_transitions_are_guarded_and_audited(tmp_path) -> None:
    database_path = tmp_path / "jobs.sqlite3"
    store = DeliveryStore(database_path)
    record_job(store)
    job = store.claim_next_job()
    assert job is not None

    store.transition_job(job.id, JobState.VALIDATING)
    store.transition_job(job.id, JobState.PUBLISHING)
    store.transition_job(job.id, JobState.COMPLETED)

    with sqlite3.connect(database_path) as connection:
        states = connection.execute(
            "SELECT previous_state, next_state FROM review_job_events ORDER BY id"
        ).fetchall()

    assert states == [
        (None, "queued"),
        ("queued", "running"),
        ("running", "validating"),
        ("validating", "publishing"),
        ("publishing", "completed"),
    ]


def test_job_state_machine_rejects_skipped_stages(tmp_path) -> None:
    store = DeliveryStore(tmp_path / "jobs.sqlite3")
    record_job(store)
    job = store.claim_next_job()
    assert job is not None

    with pytest.raises(InvalidJobTransitionError):
        store.transition_job(job.id, JobState.PUBLISHING)


def test_failure_codes_must_be_sanitized(tmp_path) -> None:
    store = DeliveryStore(tmp_path / "jobs.sqlite3")
    record_job(store)
    job = store.claim_next_job()
    assert job is not None

    with pytest.raises(ValueError, match="sanitized identifier"):
        store.transition_job(job.id, JobState.FAILED, "token=secret value")

    assert store.transition_job(job.id, JobState.FAILED, "model_timeout") is JobState.FAILED
    assert store.transition_job(job.id, JobState.QUEUED) is JobState.QUEUED
    retried = store.claim_next_job()
    assert retried is not None
    assert retried.attempts == 2


def test_legacy_job_schema_migrates_without_losing_queued_work(tmp_path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE review_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                pull_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                base_sha TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('queued', 'running', 'completed', 'failed')
                ),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (repository_id, pull_number, head_sha)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO review_jobs (
                id, repository_id, pull_number, head_sha, base_sha, status
            ) VALUES (41, 123, 17, ?, ?, 'queued')
            """,
            ("a" * 40, "b" * 40),
        )

    store = DeliveryStore(database_path)
    record_job(store, delivery_id="new-delivery", pull_number=18, head_sha="c" * 40)

    legacy_job = store.claim_next_job()
    assert legacy_job is not None
    assert legacy_job.id == 41
    assert legacy_job.state is JobState.RUNNING
    assert store.transition_job(legacy_job.id, JobState.VALIDATING) is JobState.VALIDATING