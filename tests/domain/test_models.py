import pytest
from pydantic import ValidationError

from app.domain.models import Finding, ReviewResult


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


def test_finding_accepts_valid_review_contract() -> None:
    finding = make_finding()
    result = ReviewResult(summary="One potential issue.", findings=[finding])

    assert result.findings == [finding]


@pytest.mark.parametrize("file_path", ["../secret.py", "/etc/passwd", "src\\module.py"])
def test_finding_rejects_unsafe_repository_paths(file_path: str) -> None:
    with pytest.raises(ValidationError):
        make_finding(file_path=file_path)


def test_finding_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError, match="end_line"):
        make_finding(start_line=12, end_line=10)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_confidence_outside_unit_interval(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_finding(confidence=confidence)


def test_review_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({"summary": "Done", "findings": [], "extra": True})


def test_review_result_schema_requires_all_structured_output_fields() -> None:
    schema = ReviewResult.model_json_schema()

    assert set(schema["required"]) == {"summary", "findings"}
    assert set(schema["$defs"]["Finding"]["required"]) == {
        "file_path",
        "start_line",
        "end_line",
        "category",
        "severity",
        "confidence",
        "title",
        "problem",
        "why_it_matters",
        "trigger_scenario",
        "suggested_action",
        "evidence",
        "evidence_source",
    }