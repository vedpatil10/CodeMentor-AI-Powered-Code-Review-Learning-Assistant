import json
from pathlib import Path

import pytest

from app.cli.evaluate_fixtures import evaluate_dataset, main

DATASET = "tests/evaluation/cases.jsonl"


def test_labeled_regression_dataset_scores_supported_clean_and_rejected_cases() -> None:
    report = evaluate_dataset(Path(DATASET))

    assert len(report.cases) == 3
    assert report.true_positives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.precision == 1
    assert report.recall == 1
    assert report.rejected_by_reason == {"evidence_not_found": 1}


def test_evaluation_cli_prints_metrics_as_json(capsys) -> None:
    exit_code = main([DATASET])
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert exit_code == 0
    assert report["true_positives"] == 1
    assert captured.err == ""


def test_evaluation_rejects_empty_dataset(tmp_path) -> None:
    dataset = tmp_path / "tests" / "evaluation" / "cases.jsonl"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one case"):
        evaluate_dataset(dataset)


def test_evaluation_rejects_duplicate_case_ids(tmp_path) -> None:
    dataset = tmp_path / "tests" / "evaluation" / "cases.jsonl"
    dataset.parent.mkdir(parents=True)
    row = json.dumps(
        {
            "case_id": "same-id",
            "fixture": "../fixtures/pull_requests/clean_change.json",
            "expected_findings": [],
        }
    )
    dataset.write_text(f"{row}\n{row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="case_id values must be unique"):
        evaluate_dataset(dataset)


def test_evaluation_rejects_fixture_path_escape(tmp_path) -> None:
    dataset = tmp_path / "tests" / "evaluation" / "cases.jsonl"
    dataset.parent.mkdir(parents=True)
    row = json.dumps(
        {
            "case_id": "escape",
            "fixture": "../../outside.json",
            "expected_findings": [],
        }
    )
    dataset.write_text(f"{row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fixture path must remain inside"):
        evaluate_dataset(dataset)