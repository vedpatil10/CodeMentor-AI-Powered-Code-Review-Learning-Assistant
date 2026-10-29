"""Deterministic validation gate for model-proposed review findings."""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import EvidenceSource, Finding, ReviewResult, Severity
from app.domain.policies import ReviewMode, ReviewPolicy
from app.review.packet import ReviewFilePacket, ReviewPacket


class RejectionReason(StrEnum):
    FILE_NOT_REVIEWED = "file_not_reviewed"
    LOCATION_NOT_CHANGED = "location_not_changed"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    BELOW_CONFIDENCE = "below_confidence"
    BELOW_SEVERITY = "below_severity"
    DUPLICATE = "duplicate"
    COMMENT_LIMIT = "comment_limit"


@dataclass(frozen=True, slots=True)
class RejectedFinding:
    finding: Finding
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class ValidatedReview:
    summary: str
    findings: tuple[Finding, ...]
    rejected: tuple[RejectedFinding, ...]


_SEVERITY_RANK = {
    Severity.INFORMATIONAL: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def validate_review_result(
    result: ReviewResult,
    packet: ReviewPacket,
    policy: ReviewPolicy,
) -> ValidatedReview:
    """Keep only findings supported by the exact packet and configured policy."""
    files_by_path = {file_packet.path: file_packet for file_packet in packet.files}
    accepted: list[Finding] = []
    rejected: list[RejectedFinding] = []
    fingerprints: set[tuple[str, int, str, str]] = set()

    for finding in result.findings:
        reason = _rejection_reason(finding, files_by_path, packet, policy)
        if reason is None:
            fingerprint = _fingerprint(finding)
            if fingerprint in fingerprints:
                reason = RejectionReason.DUPLICATE
            else:
                fingerprints.add(fingerprint)

        if reason is None and policy.mode is ReviewMode.INLINE:
            if len(accepted) >= policy.max_comments_per_pr:
                reason = RejectionReason.COMMENT_LIMIT

        if reason is None:
            accepted.append(finding)
        else:
            rejected.append(RejectedFinding(finding=finding, reason=reason))

    return ValidatedReview(
        summary=result.summary,
        findings=tuple(accepted),
        rejected=tuple(rejected),
    )


def _rejection_reason(
    finding: Finding,
    files_by_path: dict[str, ReviewFilePacket],
    packet: ReviewPacket,
    policy: ReviewPolicy,
) -> RejectionReason | None:
    file_packet = files_by_path.get(finding.file_path)
    if file_packet is None:
        return RejectionReason.FILE_NOT_REVIEWED
    if (finding.file_path, finding.start_line) not in packet.changed_lines:
        return RejectionReason.LOCATION_NOT_CHANGED
    if not _has_evidence(finding, file_packet):
        return RejectionReason.EVIDENCE_NOT_FOUND
    if finding.confidence < policy.min_confidence:
        return RejectionReason.BELOW_CONFIDENCE
    if _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[policy.min_severity]:
        return RejectionReason.BELOW_SEVERITY
    return None


def _has_evidence(finding: Finding, file_packet: ReviewFilePacket) -> bool:
    evidence = finding.evidence.strip()
    if not evidence:
        return False

    if finding.evidence_source is EvidenceSource.DIFF:
        diff = file_packet.diff
        supplied_lines = (
            line.content
            for hunk in diff.hunks
            for line in hunk.lines
            if line.new_line is not None
        )
    elif finding.evidence_source is EvidenceSource.RETRIEVED_CODE:
        supplied_lines = (line.content for line in file_packet.source_context)
    else:
        return False
    return evidence in "\n".join(supplied_lines)


def _fingerprint(finding: Finding) -> tuple[str, int, str, str]:
    normalized_title = " ".join(finding.title.casefold().split())
    return finding.file_path, finding.start_line, finding.category.value, normalized_title