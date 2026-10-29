import json
from pathlib import Path

from app.cli.review_fixture import main, review_fixture_file
from app.review.validation import RejectionReason

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "pull_requests"


def test_offline_fixture_accepts_evidence_backed_finding() -> None:
    report = review_fixture_file(FIXTURE_DIRECTORY / "empty_input.json")

    assert len(report.findings) == 1
    assert report.findings[0].file_path == "app/handler.py"
    assert report.rejected == []


def test_offline_fixture_clean_change_abstains() -> None:
    report = review_fixture_file(FIXTURE_DIRECTORY / "clean_change.json")

    assert report.findings == []
    assert report.rejected == []
    assert report.summary == "No actionable issues found."


def test_cli_outputs_json_and_returns_success(capsys) -> None:
    exit_code = main([str(FIXTURE_DIRECTORY / "empty_input.json")])
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 0
    assert report["findings"][0]["title"] == "Handle an empty record list"


def test_offline_fixture_reports_rejected_finding(tmp_path) -> None:
    fixture_text = (FIXTURE_DIRECTORY / "empty_input.json").read_text(encoding="utf-8")
    fixture_data = json.loads(fixture_text)
    fixture_data["review"]["findings"][0]["evidence"] = "not present in the patch"
    fixture_path = tmp_path / "unsupported.json"
    fixture_path.write_text(json.dumps(fixture_data), encoding="utf-8")

    report = review_fixture_file(fixture_path)

    assert report.findings == []
    assert report.rejected[0].reason is RejectionReason.EVIDENCE_NOT_FOUND


def test_cli_returns_safe_error_for_invalid_fixture(tmp_path, capsys) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")

    exit_code = main([str(invalid_path)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "error: unable to load or validate review fixture\n"