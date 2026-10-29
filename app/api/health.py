"""Process health endpoints for local development and deployment probes."""

from typing import Literal

from fastapi import APIRouter
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
def ready() -> ReadinessResponse:
    return ReadinessResponse(checks={"application": "ready"})