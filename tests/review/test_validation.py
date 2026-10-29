import pytest

from app.domain.models import Finding, ReviewResult
from app.domain.policies import ReviewMode, ReviewPolicy, Severity
from app.review.engine import run_review
from app.review.packet import FilePatchInput, PacketPolicy, ReviewPacket, build_review_packet
from app.review.validation import RejectionReason, validate_review_result


def make_finding(**overrides: object) -> Finding:
    data: dict[str, object] = {
        "file_path": "src/handler.py",
        "start_line": 1,
        "end_line": 1,
        "category": "correctness",
        "severity": "medium",
        "confidence": 0.9,
        "title": "Check the changed value",
        "problem": "The changed value can be invalid.",
        "why_it_matters": "The caller can receive an invalid result.",
        "trigger_scenario": "An input falls outside the expected range.",
        "suggested_action": "Validate the input before using it.",
        "evidence": "new_value = 1",
        "evidence_source": "diff",
    }
    data.update(overrides)
    return Finding.model_validate(data)


def make_packet() -> ReviewPacket:
    return build_review_packet(
        [
            FilePatchInput(
                path="src/handler.py",
                patch="@@ -1 +1 @@\n-old_value = 1\n+new_value = 1",
                source="new_value = 1\nreturn new_value",
            )
        ],
        PacketPolicy(context_radius=1),
    )


def test_validator_accepts_evidence_backed_changed_line() -> None:
    result = validate_review_result(
        ReviewResult(summary="One candidate.", findings=[make_finding()]),
        make_packet(),
        ReviewPolicy(),
    )

    assert result.summary == "One candidate."
    assert result.findings == (make_finding(),)
    assert result.rejected == ()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"file_path": "src/not_reviewed.py"}, RejectionReason.FILE_NOT_REVIEWED),
        ({"start_line": 2, "end_line": 2}, RejectionReason.LOCATION_NOT_CHANGED),
        ({"evidence": "not present"}, RejectionReason.EVIDENCE_NOT_FOUND),
        ({"evidence_source": "analyzer"}, RejectionReason.EVIDENCE_NOT_FOUND),
        ({"confidence": 0.79}, RejectionReason.BELOW_CONFIDENCE),
        ({"severity": Severity.LOW}, RejectionReason.BELOW_SEVERITY),
    ],
)
def test_validator_rejects_unsupported_or_low_policy_findings(
    overrides: dict[str, object], reason: RejectionReason
) -> None:
    result = validate_review_result(
        ReviewResult(summary="No publishable findings.", findings=[make_finding(**overrides)]),
        make_packet(),
        ReviewPolicy(min_severity=Severity.MEDIUM),
    )

    assert result.findings == ()
    assert result.rejected[0].reason is reason


def test_validator_suppresses_duplicate_findings() -> None:
    finding = make_finding()
    duplicate = make_finding(problem="Same location, same title, different wording.")

    result = validate_review_result(
        ReviewResult(summary="Two candidates.", findings=[finding, duplicate]),
        make_packet(),
        ReviewPolicy(),
    )

    assert result.findings == (finding,)
    assert result.rejected[0].reason is RejectionReason.DUPLICATE


def test_inline_policy_enforces_comment_limit() -> None:
    findings = [
        make_finding(title="First issue"),
        make_finding(title="Second issue"),
    ]

    result = validate_review_result(
        ReviewResult(summary="Two candidates.", findings=findings),
        make_packet(),
        ReviewPolicy(mode=ReviewMode.INLINE, max_comments_per_pr=1),
    )

    assert result.findings == (findings[0],)
    assert result.rejected[0].reason is RejectionReason.COMMENT_LIMIT


def test_validator_checks_retrieved_code_evidence_against_context() -> None:
    finding = make_finding(evidence="return new_value", evidence_source="retrieved_code")

    result = validate_review_result(
        ReviewResult(summary="One candidate.", findings=[finding]),
        make_packet(),
        ReviewPolicy(),
    )

    assert result.findings == (finding,)


def test_review_runner_always_applies_the_validation_gate() -> None:
    class FakeModel:
        def generate_findings(self, packet: ReviewPacket) -> ReviewResult:
            return ReviewResult(
                summary="Two model candidates.",
                findings=[make_finding(), make_finding(start_line=2, end_line=2)],
            )

    result = run_review(make_packet(), FakeModel())

    assert len(result.findings) == 1
    assert result.rejected[0].reason is RejectionReason.LOCATION_NOT_CHANGED