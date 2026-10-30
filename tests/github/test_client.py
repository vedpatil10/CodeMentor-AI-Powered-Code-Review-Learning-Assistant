import base64

import httpx
import pytest

from app.github.client import (
    GitHubAPIError,
    GitHubPullRequestClient,
    PullRequestSnapshot,
    StalePullRequestError,
)

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


def metadata(head_sha: str = HEAD_SHA) -> dict[str, object]:
    return {
        "head": {"sha": head_sha},
        "base": {"sha": BASE_SHA},
        "title": "Review this change",
        "body": "A test pull request.",
    }


def changed_file(path: str) -> dict[str, object]:
    return {
        "filename": path,
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "patch": "@@ -1 +1 @@\n-a\n+b",
    }


def make_client(handler, *, max_files: int = 40) -> GitHubPullRequestClient:
    http_client = httpx.Client(
        base_url="https://api.github.com/",
        transport=httpx.MockTransport(handler),
    )
    return GitHubPullRequestClient(
        "installation-token",
        max_files=max_files,
        http_client=http_client,
    )


def test_fetch_pr_returns_bounded_patch_snapshot_and_rechecks_head() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[changed_file("app/main.py")])
        return httpx.Response(200, json=metadata())

    client = make_client(handler)
    try:
        snapshot = client.fetch_pull_request("owner/repository", 12)
    finally:
        client.close()

    assert snapshot.repository == "owner/repository"
    assert snapshot.number == 12
    assert snapshot.base_sha == BASE_SHA
    assert snapshot.head_sha == HEAD_SHA
    assert snapshot.files[0].path == "app/main.py"
    assert snapshot.files[0].additions == 1
    assert snapshot.files[0].deletions == 1
    assert snapshot.files[0].changes == 2
    assert snapshot.files[0].patch is not None
    assert snapshot.files_truncated is False
    assert len(requests) == 3
    assert all(request.method == "GET" for request in requests)
    assert all(
        request.headers["Authorization"] == "Bearer installation-token"
        for request in requests
    )
    assert all(request.headers["X-GitHub-Api-Version"] == "2022-11-28" for request in requests)


def test_fetch_pr_marks_snapshot_truncated_at_file_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(
                200,
                json=[changed_file("one.py"), changed_file("two.py"), changed_file("three.py")],
            )
        return httpx.Response(200, json=metadata())

    client = make_client(handler, max_files=2)
    try:
        snapshot = client.fetch_pull_request("owner/repository", 1)
    finally:
        client.close()

    assert [file.path for file in snapshot.files] == ["one.py", "two.py"]
    assert snapshot.files_truncated is True


def test_fetch_pr_paginates_until_the_last_file_page() -> None:
    page_requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            page = int(request.url.params["page"])
            page_requests.append(page)
            if page == 1:
                paths = [f"src/module_{index}.py" for index in range(100)]
            else:
                paths = ["src/final.py"]
            return httpx.Response(200, json=[changed_file(path) for path in paths])
        return httpx.Response(200, json=metadata())

    client = make_client(handler, max_files=150)
    try:
        snapshot = client.fetch_pull_request("owner/repository", 1)
    finally:
        client.close()

    assert page_requests == [1, 2]
    assert len(snapshot.files) == 101
    assert snapshot.files[-1].path == "src/final.py"
    assert snapshot.files_truncated is False


def test_fetch_pr_rejects_head_changed_during_file_fetch() -> None:
    metadata_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_calls
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[changed_file("app/main.py")])
        metadata_calls += 1
        sha = HEAD_SHA if metadata_calls == 1 else "c" * 40
        return httpx.Response(200, json=metadata(sha))

    client = make_client(handler)
    try:
        with pytest.raises(StalePullRequestError):
            client.fetch_pull_request("owner/repository", 1)
    finally:
        client.close()


def test_api_errors_are_sanitized_and_do_not_include_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "secret-token=do-not-leak"})

    client = make_client(handler)
    try:
        with pytest.raises(GitHubAPIError, match="forbidden") as error:
            client.fetch_pull_request("owner/repository", 1)
    finally:
        client.close()

    assert "do-not-leak" not in str(error.value)
    assert error.value.status_code == 403


def test_fetch_file_uses_snapshot_head_and_decodes_utf8() -> None:
    content = b"def load():\n    return 7\n"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
            },
        )

    client = make_client(handler)
    pr_snapshot = PullRequestSnapshot(
        repository="owner/repository",
        number=1,
        title="title",
        description="",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        files=(),
        files_truncated=False,
    )
    try:
        fetched = client.fetch_file_text(pr_snapshot, "app/main.py")
    finally:
        client.close()

    assert fetched == content.decode("utf-8")
    assert requests[0].url.params["ref"] == HEAD_SHA


def test_fetch_file_rejects_oversized_and_unsafe_paths() -> None:
    content = b"x" * 8

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode(),
            },
        )

    client = make_client(handler)
    from app.github.client import PullRequestSnapshot

    snapshot = PullRequestSnapshot(
        repository="owner/repository",
        number=1,
        title="title",
        description="",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        files=(),
        files_truncated=False,
    )
    try:
        with pytest.raises(GitHubAPIError, match="file_too_large"):
            client.fetch_file_text(snapshot, "app/main.py", max_bytes=4)
        with pytest.raises(ValueError, match="relative repository path"):
            client.fetch_file_text(snapshot, "../secret.py")
    finally:
        client.close()


@pytest.mark.parametrize(
    "api_base_url",
    [
        "http://api.github.com",
        "file:///tmp/api",
        "https://token@api.github.com",
        "https://api.github.com?token=secret",
    ],
)
def test_client_requires_https_api_url(api_base_url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        GitHubPullRequestClient("installation-token", api_base_url=api_base_url)