"""Run the review packet and validation path against an offline JSON fixture."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Finding, ReviewResult
from app.domain.policies import ReviewPolicy
from app.review.engine import run_review
from app.review.packet import (
    FilePatchInput,
    PacketPolicy,
    SkippedFile,
    build_review_packet,
)
from app.review.validation import RejectedFinding


class FilePatchFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    patch: str | None = None
    source: str | None = None
    status: str = "modified"
    binary: bool = False


class ReviewFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    files: list[FilePatchFixture] = Field(max_length=500)
    review: ReviewResult
    packet_policy: PacketPolicy = Field(default_factory=PacketPolicy)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)


class FixtureReport(BaseModel):
    summary: str
    findings: list[Finding]
    rejected: list[RejectedFinding]
    skipped_files: list[SkippedFile]
    input_bytes: int
    estimated_tokens: int


class _FixtureModel:
    def __init__(self, result: ReviewResult) -> None:
        self._result = result

    def generate_findings(self, packet: object) -> ReviewResult:
        return self._result


def review_fixture_file(input_path: Path) -> FixtureReport:
    fixture = ReviewFixture.model_validate_json(input_path.read_text(encoding="utf-8"))
    packet = build_review_packet(
        (
            FilePatchInput(
                path=file_patch.path,
                patch=file_patch.patch,
                source=file_patch.source,
                status=file_patch.status,
                binary=file_patch.binary,
            )
            for file_patch in fixture.files
        ),
        fixture.packet_policy,
    )
    review = run_review(packet, _FixtureModel(fixture.review), fixture.review_policy)
    return FixtureReport(
        summary=review.summary,
        findings=list(review.findings),
        rejected=list(review.rejected),
        skipped_files=list(packet.skipped_files),
        input_bytes=packet.input_bytes,
        estimated_tokens=packet.estimated_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="path to an offline review fixture JSON file")
    arguments = parser.parse_args(argv)

    try:
        report = review_fixture_file(arguments.fixture)
    except (OSError, ValueError):
        print("error: unable to load or validate review fixture", file=sys.stderr)
        return 2

    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=True))
    return 0