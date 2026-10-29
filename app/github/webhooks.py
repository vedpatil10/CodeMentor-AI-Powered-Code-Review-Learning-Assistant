"""GitHub webhook signature verification and pull-request event validation."""

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

_SIGNATURE_PATTERN = re.compile(r"^sha256=([0-9a-fA-F]{64})$")
_SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
_SUPPORTED_ACTIONS = frozenset({"opened", "reopened", "synchronize", "ready_for_review"})


class WebhookPayloadError(ValueError):
    """Raised when a supported event omits or corrupts required fields."""


class WebhookDisposition(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class WebhookIgnoreReason(StrEnum):
    UNSUPPORTED_EVENT = "unsupported_event"
    UNSUPPORTED_ACTION = "unsupported_action"


@dataclass(frozen=True, slots=True)
class PullRequestWebhook:
    delivery_id: str
    action: str
    repository_id: int
    repository_full_name: str
    installation_id: int
    pull_number: int
    base_sha: str
    head_sha: str


@dataclass(frozen=True, slots=True)
class WebhookDecision:
    disposition: WebhookDisposition
    request: PullRequestWebhook | None = None
    ignore_reason: WebhookIgnoreReason | None = None


def verify_webhook_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against the exact raw request body."""
    if not secret or not signature_header:
        return False

    match = _SIGNATURE_PATTERN.fullmatch(signature_header)
    if match is None:
        return False

    expected_digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_digest, match.group(1).lower())


def parse_pull_request_webhook(
    event_name: str | None,
    delivery_id: str | None,
    payload: Mapping[str, object],
) -> WebhookDecision:
    """Validate supported GitHub PR events without trusting payload contents."""
    if not isinstance(payload, Mapping):
        raise WebhookPayloadError("webhook payload must be a JSON object")
    if not isinstance(event_name, str) or not event_name.strip():
        raise WebhookPayloadError("missing GitHub event name")
    if not isinstance(delivery_id, str) or not delivery_id.strip() or len(delivery_id) > 128:
        raise WebhookPayloadError("invalid GitHub delivery ID")
    if event_name != "pull_request":
        return WebhookDecision(
            disposition=WebhookDisposition.IGNORED,
            ignore_reason=WebhookIgnoreReason.UNSUPPORTED_EVENT,
        )

    action = payload.get("action")
    if not isinstance(action, str) or action not in _SUPPORTED_ACTIONS:
        return WebhookDecision(
            disposition=WebhookDisposition.IGNORED,
            ignore_reason=WebhookIgnoreReason.UNSUPPORTED_ACTION,
        )

    repository = _require_mapping(payload, "repository")
    installation = _require_mapping(payload, "installation")
    pull_request = _require_mapping(payload, "pull_request")
    repository_id = _require_positive_int(repository, "id", "repository")
    installation_id = _require_positive_int(installation, "id", "installation")
    pull_number = _require_positive_int(payload, "number", "payload")
    repository_full_name = repository.get("full_name")
    if (
        not isinstance(repository_full_name, str)
        or repository_full_name.count("/") != 1
        or any(not part for part in repository_full_name.split("/"))
    ):
        raise WebhookPayloadError("invalid repository full_name")

    head = _require_mapping(pull_request, "head")
    base = _require_mapping(pull_request, "base")
    head_sha = _require_sha(head, "sha", "pull_request.head")
    base_sha = _require_sha(base, "sha", "pull_request.base")

    return WebhookDecision(
        disposition=WebhookDisposition.ACCEPTED,
        request=PullRequestWebhook(
            delivery_id=delivery_id,
            action=action,
            repository_id=repository_id,
            repository_full_name=repository_full_name,
            installation_id=installation_id,
            pull_number=pull_number,
            base_sha=base_sha,
            head_sha=head_sha,
        ),
    )


def _require_mapping(parent: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise WebhookPayloadError(f"missing or invalid {key}")
    return value


def _require_positive_int(parent: Mapping[str, object], key: str, context: str) -> int:
    value = parent.get(key)
    if type(value) is not int or value <= 0:
        raise WebhookPayloadError(f"invalid {context} {key}")
    return value


def _require_sha(parent: Mapping[str, object], key: str, context: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or _SHA_PATTERN.fullmatch(value) is None:
        raise WebhookPayloadError(f"invalid {context} SHA")
    return value