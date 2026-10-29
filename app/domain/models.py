"""Validated data contracts for candidate code-review findings."""

from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FindingCategory(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TESTING = "testing"


class Severity(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceSource(StrEnum):
    DIFF = "diff"
    RETRIEVED_CODE = "retrieved_code"
    TEST = "test"
    ANALYZER = "analyzer"


class Finding(BaseModel):
    """A proposed issue tied to evidence and a source location."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    category: FindingCategory
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    title: str = Field(min_length=1, max_length=120)
    problem: str = Field(min_length=1, max_length=2000)
    why_it_matters: str = Field(min_length=1, max_length=2000)
    trigger_scenario: str = Field(min_length=1, max_length=1000)
    suggested_action: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=1000)
    evidence_source: EvidenceSource

    @field_validator("file_path")
    @classmethod
    def validate_repository_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            value != value.strip()
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise ValueError("file_path must be a relative repository path")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> "Finding":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class ReviewResult(BaseModel):
    """Structured result returned by a review provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=2000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)