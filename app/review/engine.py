"""Provider-independent review runner with a mandatory deterministic gate."""

from typing import Protocol

from app.domain.models import ReviewResult
from app.domain.policies import ReviewPolicy
from app.review.packet import ReviewPacket
from app.review.validation import ValidatedReview, validate_review_result


class ReviewModel(Protocol):
    """Minimal interface implemented by an LLM provider or a test double."""

    def generate_findings(self, packet: ReviewPacket) -> ReviewResult:
        """Return schema-validated candidate findings for the packet."""


def run_review(
    packet: ReviewPacket,
    model: ReviewModel,
    policy: ReviewPolicy | None = None,
) -> ValidatedReview:
    """Generate and validate findings; callers receive only gated candidates."""
    selected_policy = policy or ReviewPolicy()
    candidate_result = model.generate_findings(packet)
    return validate_review_result(candidate_result, packet, selected_policy)