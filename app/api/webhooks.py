"""Authenticated GitHub webhook endpoint."""

import hashlib
import json
from collections.abc import Mapping

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.db.deliveries import (
    DeliveryConflictError,
    DeliveryRecord,
    DeliveryRecordResult,
)
from app.github.webhooks import (
    WebhookDisposition,
    WebhookPayloadError,
    parse_pull_request_webhook,
    verify_webhook_signature,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookResponse(BaseModel):
    status: str
    reason: str | None = None


@router.post("/github", response_model=WebhookResponse, status_code=202)
async def receive_github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> WebhookResponse:
    settings = request.app.state.settings
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=503, detail="webhook verification is not configured")

    body = await request.body()
    if not verify_webhook_signature(
        settings.github_webhook_secret, body, x_hub_signature_256
    ):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        payload = json.loads(body)
        if not isinstance(payload, Mapping):
            raise WebhookPayloadError("webhook payload must be a JSON object")
        decision = parse_pull_request_webhook(x_github_event, x_github_delivery, payload)
    except (json.JSONDecodeError, UnicodeDecodeError, WebhookPayloadError) as error:
        raise HTTPException(status_code=400, detail="invalid webhook payload") from error

    if decision.disposition is WebhookDisposition.IGNORED:
        return WebhookResponse(status="ignored", reason=decision.ignore_reason.value)

    pull_request = decision.request
    if pull_request is None:
        raise HTTPException(status_code=400, detail="invalid webhook payload")

    try:
        result = request.app.state.delivery_store.record(
            DeliveryRecord(
                delivery_id=pull_request.delivery_id,
                event_name=x_github_event or "",
                repository_id=pull_request.repository_id,
                installation_id=pull_request.installation_id,
                pull_number=pull_request.pull_number,
                base_sha=pull_request.base_sha,
                head_sha=pull_request.head_sha,
                payload_sha256=hashlib.sha256(body).hexdigest(),
            )
        )
    except DeliveryConflictError as error:
        raise HTTPException(status_code=409, detail="delivery ID payload conflict") from error
    if result is DeliveryRecordResult.DUPLICATE_DELIVERY:
        return WebhookResponse(status="duplicate")
    if result is DeliveryRecordResult.DUPLICATE_HEAD:
        return WebhookResponse(status="deduplicated")
    return WebhookResponse(status="queued")