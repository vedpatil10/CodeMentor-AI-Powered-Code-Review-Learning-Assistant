"""Evaluate deterministic finding validation against labeled offline fixtures."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.cli.review_fixture import review_fixture_file
from app.domain.models import FindingCategory


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_path: str
    line: int = Field(ge=1)
    category: FindingCategory


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    fixture: str
    expected_findings: list[ExpectedFinding] = Field(max_length=100)


class CaseEvaluation(BaseModel):
    case_id: str
    expected_count: int
    accepted_count: int
    rejected_count: int
    true_positives: int


class EvaluationReport(BaseModel):
    cases: list[CaseEvaluation]
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    rejected_by_reason: dict[str, int]


def evaluate_dataset(dataset_path: Path) -> EvaluationReport:
    dataset_root = dataset_path.resolve().parent.parent
    case_rows = [
        EvaluationCase.model_validate_json(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not case_rows:
        raise ValueError("evaluation dataset must contain at least one case")
    case_ids = [case.case_id for case in case_rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case_id values must be unique")

    case_results: list[CaseEvaluation] = []
    rejection_counts: Counter[str] = Counter()
    total_expected = 0
    total_accepted = 0
    true_positives = 0

    for case in case_rows:
        fixture_path = (dataset_root / case.fixture).resolve()
        if dataset_root not in fixture_path.parents:
            raise ValueError("fixture path must remain inside the tests directory")
        report = review_fixture_file(fixture_path)
        expected = Counter(
            (finding.file_path, finding.line, finding.category.value)
            for finding in case.expected_findings
        )
        accepted = Counter(
            (finding.file_path, finding.start_line, finding.category.value)
            for finding in report.findings
        )
        matched = sum((expected & accepted).values())
        total_expected += sum(expected.values())
        total_accepted += sum(accepted.values())
        true_positives += matched
        rejection_counts.update(rejected.reason.value for rejected in report.rejected)
        case_results.append(
            CaseEvaluation(
                case_id=case.case_id,
                expected_count=sum(expected.values()),
                accepted_count=sum(accepted.values()),
                rejected_count=len(report.rejected),
                true_positives=matched,
            )
        )

    false_positives = total_accepted - true_positives
    false_negatives = total_expected - true_positives
    precision = (
        true_positives / total_accepted
        if total_accepted
        else float(total_expected == 0)
    )
    recall = (
        true_positives / total_expected
        if total_expected
        else float(total_accepted == 0)
    )
    return EvaluationReport(
        cases=case_results,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        rejected_by_reason=dict(sorted(rejection_counts.items())),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path("tests/evaluation/cases.jsonl"),
        help="path to the labeled JSONL dataset",
    )
    arguments = parser.parse_args(argv)

    try:
        report = evaluate_dataset(arguments.dataset)
    except (OSError, ValueError):
        print("error: unable to load or evaluate dataset", file=sys.stderr)
        return 2

    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=True))
    return 0