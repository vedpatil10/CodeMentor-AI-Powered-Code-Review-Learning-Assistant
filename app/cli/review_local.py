"""Review a saved diff with the configured model and deterministic validator."""

import argparse
import json
import sys
from pathlib import Path

from app.cli.review_fixture import (
    FixtureReport,
    build_packet,
    load_review_fixture,
    make_report,
)
from app.config import Settings
from app.review.engine import ReviewModel, run_review
from app.review.openai_model import ModelProviderError, ModelResponseError, OpenAIReviewModel


def review_local_file(
    input_path: Path,
    settings: Settings,
    model: ReviewModel | None = None,
) -> FixtureReport:
    fixture = load_review_fixture(input_path)
    packet = build_packet(fixture)
    review_model = model or OpenAIReviewModel(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.max_output_tokens,
    )
    result = run_review(packet, review_model, fixture.review_policy)
    return make_report(result, packet)


def main(argv: list[str] | None = None, model: ReviewModel | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="path to a review fixture JSON file")
    arguments = parser.parse_args(argv)

    try:
        report = review_local_file(arguments.fixture, Settings.from_env(), model)
    except (OSError, ValueError):
        print("error: unable to load or validate review input", file=sys.stderr)
        return 2
    except (ModelProviderError, ModelResponseError) as error:
        print(f"error: model review failed ({error})", file=sys.stderr)
        return 3

    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=True))
    return 0