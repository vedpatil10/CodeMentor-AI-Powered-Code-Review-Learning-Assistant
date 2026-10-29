"""Deterministic publication policy for candidate findings."""

from collections.abc import Set
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Finding, Severity


class ReviewMode(StrEnum):
    SUMMARY_ONLY = "summary_only"
    INLINE = "inline"
    DRAFT = "draft"


class RejectionReason(StrEnum):
    ACCEPTED = "accepted"
    BELOW_CONFIDENCE = "below_confidence"
    BELOW_SEVERITY = "below_severity"
    LOCATION_NOT_CHANGED = "location_not_changed"
    INLINE_DISABLED = "inline_disabled"


class ReviewPolicy(BaseModel):
    """Bounded review settings with conservative defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ReviewMode = ReviewMode.SUMMARY_ONLY
    min_severity: Severity = Severity.LOW
    min_confidence: float = Field(default=0.8, ge=0, le=1)
    max_comments_per_pr: int = Field(default=12, ge=0, le=100)
    max_files_per_pr: int = Field(default=40, ge=1, le=500)
    max_file_bytes: int = Field(default=150_000, ge=1, le=10_000_000)
    max_review_tokens: int = Field(default=18_000, ge=1, le=200_000)


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    publish: bool
    reason: RejectionReason


_SEVERITY_RANK = {
    Severity.INFORMATIONAL: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def evaluate_inline_finding(
    finding: Finding,
    policy: ReviewPolicy,
    changed_lines: Set[tuple[str, int]],
) -> PublicationDecision:
    """Apply local policy and changed-line checks before inline publication."""
    if policy.mode is not ReviewMode.INLINE:
        return PublicationDecision(False, RejectionReason.INLINE_DISABLED)
    if finding.confidence < policy.min_confidence:
        return PublicationDecision(False, RejectionReason.BELOW_CONFIDENCE)
    if _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[policy.min_severity]:
        return PublicationDecision(False, RejectionReason.BELOW_SEVERITY)
    if (finding.file_path, finding.start_line) not in changed_lines:
        return PublicationDecision(False, RejectionReason.LOCATION_NOT_CHANGED)
    return PublicationDecision(True, RejectionReason.ACCEPTED)