import asyncio
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.config import Settings
from app.db.deliveries import DeliveryRecord, DeliveryRecordResult, DeliveryStore
from app.main import create_app

SECRET = "test-webhook-secret"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": "opened",
        "number": 17,
        "repository": {"id": 123, "full_name": "owner/project"},
        "installation": {"id": 456},
        "pull_request": {"head": {"sha": HEAD_SHA}, "base": {"sha": BASE_SHA}},
    }
    payload.update(overrides)
    return payload


def post_webhook(
    database_path,
    payload: object,
    *,
    event: str = "pull_request",
    delivery_id: str = "delivery-1",
    secret: str = SECRET,
    signature_body: bytes | None = None,
) -> Response:
    app = create_app(
        Settings(github_webhook_secret=secret, database_path=database_path),
        DeliveryStore(database_path),
    )
    body = json.dumps(payload, separators=(",", ":")).encode()
    signed_body = body if signature_body is None else signature_body
    signature = hmac.new(secret.encode(), signed_body, hashlib.sha256).hexdigest()

    async def send() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "X-GitHub-Event": event,
                    "X-GitHub-Delivery": delivery_id,
                    "X-Hub-Signature-256": f"sha256={signature}",
                },
            )

    return asyncio.run(send())


def test_signed_webhook_is_persisted_and_queued(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    response = post_webhook(database_path, make_payload())

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "reason": None}
    assert DeliveryStore(database_path).counts() == (1, 1)


def test_invalid_signature_is_rejected_without_persistence(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    response = post_webhook(
        database_path,
        make_payload(),
        signature_body=b"different body",
    )

    assert response.status_code == 401
    assert DeliveryStore(database_path).counts() == (0, 0)


def test_missing_secret_disables_webhook_endpoint(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    response = post_webhook(database_path, make_payload(), secret="")

    assert response.status_code == 503
    assert DeliveryStore(database_path).counts() == (0, 0)


def test_duplicate_delivery_does_not_create_another_job(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"
    payload = make_payload()

    first = post_webhook(database_path, payload)
    second = post_webhook(database_path, payload)

    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "duplicate"
    assert DeliveryStore(database_path).counts() == (1, 1)


def test_reused_delivery_id_with_different_payload_is_conflict(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    first = post_webhook(database_path, make_payload())
    second = post_webhook(
        database_path,
        make_payload(pull_request={"head": {"sha": "c" * 40}, "base": {"sha": BASE_SHA}}),
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert DeliveryStore(database_path).counts() == (1, 1)


def test_new_delivery_for_same_head_does_not_create_another_job(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    first = post_webhook(database_path, make_payload(), delivery_id="delivery-1")
    second = post_webhook(database_path, make_payload(), delivery_id="delivery-2")

    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "deduplicated"
    assert DeliveryStore(database_path).counts() == (2, 1)


def test_concurrent_deliveries_for_same_head_create_one_job(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"
    store = DeliveryStore(database_path)
    seed = DeliveryRecord(
        delivery_id="seed",
        event_name="pull_request",
        repository_id=123,
        installation_id=456,
        pull_number=1,
        base_sha=BASE_SHA,
        head_sha="c" * 40,
        payload_sha256="seed",
    )
    store.record(seed)
    deliveries = [
        replace(
            seed,
            delivery_id=f"parallel-{index}",
            pull_number=17,
            head_sha=HEAD_SHA,
            payload_sha256=f"payload-{index}",
        )
        for index in range(8)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(store.record, deliveries))

    assert results.count(DeliveryRecordResult.QUEUED) == 1
    assert results.count(DeliveryRecordResult.DUPLICATE_HEAD) == 7
    assert store.counts() == (9, 2)


def test_unrelated_event_is_acknowledged_without_queueing(tmp_path) -> None:
    database_path = tmp_path / "deliveries.sqlite3"

    response = post_webhook(database_path, make_payload(), event="issues")

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert DeliveryStore(database_path).counts() == (0, 0)


@pytest.mark.parametrize("body", [b"{invalid", b"[]"])
def test_malformed_signed_body_is_rejected(tmp_path, body: bytes) -> None:
    database_path = tmp_path / "deliveries.sqlite3"
    app = create_app(
        Settings(github_webhook_secret=SECRET, database_path=database_path),
        DeliveryStore(database_path),
    )
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    async def send() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "delivery-invalid",
                    "X-Hub-Signature-256": f"sha256={signature}",
                },
            )

    response = asyncio.run(send())

    assert response.status_code == 400
    assert DeliveryStore(database_path).counts() == (0, 0)