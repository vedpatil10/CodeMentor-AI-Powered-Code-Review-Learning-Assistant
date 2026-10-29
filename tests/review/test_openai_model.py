from types import SimpleNamespace

import pytest

from app.domain.models import ReviewResult
from app.review.openai_model import (
    ModelProviderError,
    ModelResponseError,
    OpenAIReviewModel,
)
from app.review.packet import FilePatchInput, ReviewPacket, build_review_packet


class FakeResponses:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.request: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> object:
        self.request = kwargs
        if self.error is not None:
            raise self.error
        return self.response


def make_packet(repository_files: dict[str, str] | None = None) -> ReviewPacket:
    patch = "@@ -1 +1 @@\n-old_value = 1\n+new_value = 1"
    source = "new_value = 1"
    if repository_files is not None:
        patch = "@@ -1 +1 @@\n-old_value = 1\n+new_value = fetch_records()"
        source = "new_value = fetch_records()"
    return build_review_packet(
        [
            FilePatchInput(
                path="src/handler.py",
                patch=patch,
                source=source,
            )
        ],
        repository_files=repository_files,
    )


def test_model_uses_structured_schema_and_serializes_packet_as_data() -> None:
    expected = ReviewResult(summary="No actionable issues.", findings=[])
    responses = FakeResponses(SimpleNamespace(status="completed", output_parsed=expected))
    model = OpenAIReviewModel("test-key", "test-model", client=SimpleNamespace(responses=responses))

    result = model.generate_findings(make_packet())

    assert result == expected
    assert responses.request is not None
    assert responses.request["model"] == "test-model"
    assert responses.request["text_format"] is ReviewResult
    input_messages = responses.request["input"]
    assert isinstance(input_messages, list)
    assert "untrusted data" in input_messages[0]["content"]
    assert '"path":"src/handler.py"' in input_messages[1]["content"]
    assert '"retrieved_symbols":[]' in input_messages[1]["content"]


def test_model_serializes_retrieved_symbols_with_provenance() -> None:
    responses = FakeResponses(
        SimpleNamespace(
            status="completed",
            output_parsed=ReviewResult(summary="No findings.", findings=[]),
        )
    )
    model = OpenAIReviewModel("test-key", "test-model", client=SimpleNamespace(responses=responses))

    model.generate_findings(
        make_packet({"app/store.py": "def fetch_records():\n    return []"})
    )

    assert responses.request is not None
    input_messages = responses.request["input"]
    assert isinstance(input_messages, list)
    assert '"provenance":"app/store.py:1-2"' in input_messages[1]["content"]


def test_model_rejects_missing_api_key_without_injected_client() -> None:
    with pytest.raises(ModelProviderError, match="missing_api_key"):
        OpenAIReviewModel("", "test-model")


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_model_rejects_incomplete_or_unparsed_responses(status: str) -> None:
    responses = FakeResponses(SimpleNamespace(status=status, output_parsed=None))
    model = OpenAIReviewModel("test-key", "test-model", client=SimpleNamespace(responses=responses))

    with pytest.raises(ModelResponseError):
        model.generate_findings(make_packet())


def test_model_surfaces_refusal_as_a_safe_error_code() -> None:
    response = SimpleNamespace(
        status="completed",
        output_parsed=None,
        output=[
            {"type": "message", "content": [{"type": "refusal", "refusal": "private"}]}
        ],
    )
    model = OpenAIReviewModel(
        "test-key", "test-model", client=SimpleNamespace(responses=FakeResponses(response))
    )

    with pytest.raises(ModelResponseError, match="model_refusal") as error:
        model.generate_findings(make_packet())

    assert "private" not in str(error.value)


def test_model_wraps_provider_errors_without_copying_provider_message() -> None:
    model = OpenAIReviewModel(
        "test-key",
        "test-model",
        client=SimpleNamespace(responses=FakeResponses(error=RuntimeError("token=private"))),
    )

    with pytest.raises(ModelProviderError, match="provider_request_failed") as error:
        model.generate_findings(make_packet())

    assert "private" not in str(error.value)