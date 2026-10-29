import hashlib
import hmac

import pytest

from app.github.webhooks import (
    WebhookDisposition,
    WebhookIgnoreReason,
    WebhookPayloadError,
    parse_pull_request_webhook,
    verify_webhook_signature,
)


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": "opened",
        "number": 17,
        "repository": {"id": 123, "full_name": "owner/project"},
        "installation": {"id": 456},
        "pull_request": {
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
        },
    }
    payload.update(overrides)
    return payload


def test_signature_verifies_exact_raw_body() -> None:
    secret = "test-secret"
    body = b'{"action":"opened"}\n'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(secret, body, f"sha256={digest}")
    assert not verify_webhook_signature(secret, body + b" ", f"sha256={digest}")


@pytest.mark.parametrize("signature", [None, "", "sha1=deadbeef", "sha256=xyz"])
def test_signature_rejects_missing_or_malformed_header(signature: str | None) -> None:
    assert not verify_webhook_signature("secret", b"{}", signature)


def test_signature_rejects_empty_secret() -> None:
    assert not verify_webhook_signature("", b"{}", "sha256=" + "0" * 64)


@pytest.mark.parametrize("action", ["opened", "reopened", "synchronize", "ready_for_review"])
def test_parser_accepts_supported_pull_request_actions(action: str) -> None:
    payload = make_payload(action=action)

    decision = parse_pull_request_webhook("pull_request", "delivery-1", payload)

    assert decision.disposition is WebhookDisposition.ACCEPTED
    assert decision.request is not None
    assert decision.request.action == action
    assert decision.request.repository_full_name == "owner/project"
    assert decision.request.pull_number == 17


def test_parser_ignores_unrelated_events_and_actions() -> None:
    unsupported_event = parse_pull_request_webhook("issues", "delivery-1", make_payload())
    unsupported_action = parse_pull_request_webhook(
        "pull_request", "delivery-2", make_payload(action="closed")
    )

    assert unsupported_event.ignore_reason is WebhookIgnoreReason.UNSUPPORTED_EVENT
    assert unsupported_action.ignore_reason is WebhookIgnoreReason.UNSUPPORTED_ACTION


def test_parser_rejects_non_object_payload() -> None:
    with pytest.raises(WebhookPayloadError, match="JSON object"):
        parse_pull_request_webhook("pull_request", "delivery-1", [])


@pytest.mark.parametrize(
    "payload",
    [
        make_payload(number=True),
        make_payload(repository={"id": -1, "full_name": "owner/project"}),
        make_payload(repository={"id": 123, "full_name": "owner"}),
        make_payload(installation={"id": 0}),
        make_payload(pull_request={"head": {"sha": "bad"}, "base": {"sha": "b" * 40}}),
        make_payload(pull_request={"head": {"sha": "a" * 40}}),
    ],
)
def test_parser_rejects_malformed_supported_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(WebhookPayloadError):
        parse_pull_request_webhook("pull_request", "delivery-1", payload)


@pytest.mark.parametrize(
    ("event_name", "delivery_id"),
    [
        (None, "delivery-1"),
        ("pull_request", None),
        ("pull_request", ""),
        ("pull_request", "x" * 129),
    ],
)
def test_parser_rejects_missing_or_invalid_headers(
    event_name: str | None, delivery_id: str | None
) -> None:
    with pytest.raises(WebhookPayloadError):
        parse_pull_request_webhook(event_name, delivery_id, make_payload())