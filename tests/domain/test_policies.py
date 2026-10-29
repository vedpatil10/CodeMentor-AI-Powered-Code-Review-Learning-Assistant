import pytest
from pydantic import ValidationError

from app.domain.models import Finding, Severity
from app.domain.policies import (
    RejectionReason,
    ReviewMode,
    ReviewPolicy,
    evaluate_inline_finding,
)


def make_finding(**overrides: object) -> Finding:
    data: dict[str, object] = {
        "file_path": "src/handler.py",
        "start_line": 10,
        "end_line": 10,
        "category": "correctness",
        "severity": "medium",
        "confidence": 0.9,
        "title": "Handle empty results",
        "problem": "The first element is accessed without checking the list.",
        "why_it_matters": "An empty result raises an exception.",
        "trigger_scenario": "The query returns no rows.",
        "suggested_action": "Handle an empty list before indexing.",
        "evidence": "item = results[0]",
        "evidence_source": "diff",
    }
    data.update(overrides)
    return Finding.model_validate(data)


def test_inline_policy_accepts_evidence_at_a_changed_line() -> None:
    decision = evaluate_inline_finding(
        make_finding(),
        ReviewPolicy(mode=ReviewMode.INLINE),
        {("src/handler.py", 10)},
    )

    assert decision.publish is True
    assert decision.reason is RejectionReason.ACCEPTED


@pytest.mark.parametrize(
    ("finding", "policy", "changed_lines", "reason"),
    [
        (
            make_finding(confidence=0.79),
            ReviewPolicy(mode=ReviewMode.INLINE),
            {("src/handler.py", 10)},
            RejectionReason.BELOW_CONFIDENCE,
        ),
        (
            make_finding(severity=Severity.LOW),
            ReviewPolicy(mode=ReviewMode.INLINE, min_severity=Severity.MEDIUM),
            {("src/handler.py", 10)},
            RejectionReason.BELOW_SEVERITY,
        ),
        (
            make_finding(),
            ReviewPolicy(mode=ReviewMode.INLINE),
            {("src/handler.py", 11)},
            RejectionReason.LOCATION_NOT_CHANGED,
        ),
        (
            make_finding(),
            ReviewPolicy(mode=ReviewMode.SUMMARY_ONLY),
            {("src/handler.py", 10)},
            RejectionReason.INLINE_DISABLED,
        ),
    ],
)
def test_inline_policy_rejects_findings_outside_policy(
    finding: Finding,
    policy: ReviewPolicy,
    changed_lines: set[tuple[str, int]],
    reason: RejectionReason,
) -> None:
    decision = evaluate_inline_finding(finding, policy, changed_lines)

    assert decision.publish is False
    assert decision.reason is reason


def test_review_policy_rejects_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        ReviewPolicy(max_files_per_pr=10_000)