import json
from pathlib import Path

import pytest

from app.cli.review_local import main, review_local_file
from app.config import Settings
from app.domain.models import ReviewResult
from app.review.openai_model import ModelProviderError
from app.review.packet import ReviewPacket
from app.review.validation import RejectionReason

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "pull_requests"


class FakeModel:
    def __init__(self, result: ReviewResult) -> None:
        self.result = result
        self.packet: ReviewPacket | None = None

    def generate_findings(self, packet: ReviewPacket) -> ReviewResult:
        self.packet = packet
        return self.result


def test_local_review_runs_provider_through_deterministic_gate() -> None:
    expected = json.loads(
        (FIXTURE_DIRECTORY / "empty_input.json").read_text(encoding="utf-8")
    )["review"]
    model = FakeModel(ReviewResult.model_validate(expected))

    report = review_local_file(
        FIXTURE_DIRECTORY / "empty_input.json",
        Settings(openai_api_key="not-used-by-fake"),
        model,
    )

    assert model.packet is not None
    assert len(report.findings) == 1
    assert report.rejected == []


def test_local_review_rejects_provider_candidate_with_unsupported_evidence() -> None:
    finding_fixture = json.loads(
        (FIXTURE_DIRECTORY / "empty_input.json").read_text(encoding="utf-8")
    )["review"]
    finding_fixture["findings"][0]["evidence"] = "absent from supplied diff"
    model = FakeModel(ReviewResult.model_validate(finding_fixture))

    report = review_local_file(
        FIXTURE_DIRECTORY / "empty_input.json",
        Settings(openai_api_key="not-used-by-fake"),
        model,
    )

    assert report.findings == []
    assert report.rejected[0].reason is RejectionReason.EVIDENCE_NOT_FOUND


def test_local_review_requires_api_key_without_provider_injection() -> None:
    with pytest.raises(ModelProviderError, match="missing_api_key"):
        review_local_file(
            FIXTURE_DIRECTORY / "empty_input.json",
            Settings(openai_api_key=""),
        )


def test_local_cli_outputs_validated_report(monkeypatch, capsys) -> None:
    finding_fixture = json.loads(
        (FIXTURE_DIRECTORY / "empty_input.json").read_text(encoding="utf-8")
    )["review"]
    model = FakeModel(ReviewResult.model_validate(finding_fixture))
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings()))

    exit_code = main([str(FIXTURE_DIRECTORY / "empty_input.json")], model=model)
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert exit_code == 0
    assert output["findings"][0]["title"] == "Handle an empty record list"
    assert captured.err == ""