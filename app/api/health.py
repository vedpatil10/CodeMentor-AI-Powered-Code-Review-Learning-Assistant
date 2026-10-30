"""Process health endpoints for local development and deployment probes."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, Literal["ready"]]


@router.get("/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse)
def ready(request: Request) -> ReadinessResponse:
    try:
        request.app.state.delivery_store.check_ready()
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(status_code=503, detail="delivery store unavailable") from error
    return ReadinessResponse(checks={"application": "ready", "delivery_store": "ready"})