"""Read-only GitHub REST client for immutable pull-request snapshots."""

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import httpx

_SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
_REPOSITORY_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_PAGE_SIZE = 100


class GitHubAPIError(RuntimeError):
    """A GitHub request failed; the error code never includes response content."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class StalePullRequestError(RuntimeError):
    """The pull-request head changed while its data was being fetched."""


@dataclass(frozen=True, slots=True)
class ChangedFile:
    path: str
    status: str
    patch: str | None
    additions: int
    deletions: int
    changes: int
    previous_path: str | None = None


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    repository: str
    number: int
    title: str
    description: str
    base_sha: str
    head_sha: str
    files: tuple[ChangedFile, ...]
    files_truncated: bool


class GitHubPullRequestClient:
    """Fetch PR metadata and patches without modifying GitHub state."""

    def __init__(
        self,
        installation_token: str,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 15,
        max_files: int = 40,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not installation_token:
            raise ValueError("installation token is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= max_files <= 500:
            raise ValueError("max_files must be between 1 and 500")
        parsed_url = urlsplit(api_base_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("GitHub API base URL must use HTTPS")

        self._max_files = max_files
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {installation_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CodeMentor",
        }
        self._client = http_client or httpx.Client(
            base_url=api_base_url.rstrip("/") + "/",
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_pull_request(self, repository: str, number: int) -> PullRequestSnapshot:
        """Fetch metadata and changed patches, then verify the head stayed fixed."""
        repository_path = _repository_path(repository)
        if number <= 0:
            raise ValueError("pull request number must be positive")

        initial = self._fetch_metadata(repository_path, repository, number)
        files, files_truncated = self._fetch_changed_files(repository_path, number)
        latest = self._fetch_metadata(repository_path, repository, number)
        if initial.head_sha != latest.head_sha or initial.base_sha != latest.base_sha:
            raise StalePullRequestError("pull request changed during fetch")

        return PullRequestSnapshot(
            repository=repository,
            number=number,
            title=initial.title,
            description=initial.description,
            base_sha=initial.base_sha,
            head_sha=initial.head_sha,
            files=tuple(files),
            files_truncated=files_truncated,
        )

    def fetch_file_text(
        self,
        snapshot: PullRequestSnapshot,
        path: str,
        max_bytes: int = 150_000,
    ) -> str:
        """Fetch one UTF-8 file at the snapshot's immutable head SHA."""
        if not _is_safe_repository_path(path):
            raise ValueError("file path must be a relative repository path")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        repository_path = _repository_path(snapshot.repository)
        encoded_path = quote(path, safe="/")
        payload = self._get_json(
            f"repos/{repository_path}/contents/{encoded_path}",
            params={"ref": snapshot.head_sha},
        )
        if not isinstance(payload, Mapping):
            raise GitHubAPIError("invalid_response")
        size = payload.get("size")
        if type(size) is not int or size < 0:
            raise GitHubAPIError("invalid_response")
        if size > max_bytes:
            raise GitHubAPIError("file_too_large")
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise GitHubAPIError("unsupported_file_encoding")
        try:
            content = base64.b64decode(payload["content"])
            if len(content) > max_bytes:
                raise GitHubAPIError("file_too_large")
            return content.decode("utf-8")
        except GitHubAPIError:
            raise
        except (binascii.Error, UnicodeDecodeError) as error:
            raise GitHubAPIError("invalid_file_content") from error

    def _fetch_metadata(
        self,
        repository_path: str,
        repository: str,
        number: int,
    ) -> PullRequestSnapshot:
        payload = self._get_json(f"repos/{repository_path}/pulls/{number}")
        if not isinstance(payload, Mapping):
            raise GitHubAPIError("invalid_response")
        head = payload.get("head")
        base = payload.get("base")
        if not isinstance(head, Mapping) or not isinstance(base, Mapping):
            raise GitHubAPIError("invalid_response")
        head_sha = head.get("sha")
        base_sha = base.get("sha")
        title = payload.get("title")
        description = payload.get("body")
        if (
            not isinstance(head_sha, str)
            or _SHA_PATTERN.fullmatch(head_sha) is None
            or not isinstance(base_sha, str)
            or _SHA_PATTERN.fullmatch(base_sha) is None
            or not isinstance(title, str)
            or (description is not None and not isinstance(description, str))
        ):
            raise GitHubAPIError("invalid_response")
        return PullRequestSnapshot(
            repository=repository,
            number=number,
            title=title,
            description=description or "",
            base_sha=base_sha,
            head_sha=head_sha,
            files=(),
            files_truncated=False,
        )

    def _fetch_changed_files(
        self,
        repository_path: str,
        number: int,
    ) -> tuple[list[ChangedFile], bool]:
        files: list[ChangedFile] = []
        page = 1
        truncated = False
        while True:
            payload = self._get_json(
                f"repos/{repository_path}/pulls/{number}/files",
                params={"per_page": _MAX_PAGE_SIZE, "page": page},
            )
            if not isinstance(payload, list):
                raise GitHubAPIError("invalid_response")
            for item in payload:
                if len(files) >= self._max_files:
                    truncated = True
                    break
                if not isinstance(item, Mapping):
                    raise GitHubAPIError("invalid_response")
                path = item.get("filename")
                status = item.get("status")
                additions = item.get("additions")
                deletions = item.get("deletions")
                changes = item.get("changes")
                patch = item.get("patch")
                previous_path = item.get("previous_filename")
                if (
                    not isinstance(path, str)
                    or not _is_safe_repository_path(path)
                    or not isinstance(status, str)
                    or type(additions) is not int
                    or additions < 0
                    or type(deletions) is not int
                    or deletions < 0
                    or type(changes) is not int
                    or changes < 0
                    or (patch is not None and not isinstance(patch, str))
                    or (
                        previous_path is not None
                        and (
                            not isinstance(previous_path, str)
                            or not _is_safe_repository_path(previous_path)
                        )
                    )
                ):
                    raise GitHubAPIError("invalid_response")
                files.append(
                    ChangedFile(
                        path=path,
                        status=status,
                        patch=patch,
                        additions=additions,
                        deletions=deletions,
                        changes=changes,
                        previous_path=previous_path,
                    )
                )
            if truncated or len(payload) < _MAX_PAGE_SIZE:
                break
            page += 1
        return files, truncated

    def _get_json(self, path: str, params: Mapping[str, object] | None = None) -> object:
        try:
            response = self._client.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as error:
            raise GitHubAPIError("network_error") from error
        if not response.is_success:
            status_code = response.status_code
            if status_code == 401:
                code = "unauthorized"
            elif status_code == 403:
                code = (
                    "rate_limited"
                    if response.headers.get("X-RateLimit-Remaining") == "0"
                    else "forbidden"
                )
            elif status_code == 404:
                code = "not_found"
            elif status_code == 422:
                code = "invalid_request"
            elif status_code == 429:
                code = "rate_limited"
            elif status_code >= 500:
                code = "upstream_error"
            else:
                code = "http_error"
            raise GitHubAPIError(code, status_code)
        try:
            return response.json()
        except ValueError as error:
            raise GitHubAPIError("invalid_response", response.status_code) from error


def _repository_path(repository: str) -> str:
    parts = repository.split("/")
    if (
        len(parts) != 2
        or any(part in {"", ".", ".."} for part in parts)
        or any(_REPOSITORY_PART_PATTERN.fullmatch(part) is None for part in parts)
    ):
        raise ValueError("repository must be in owner/name format")
    return "/".join(quote(part, safe="") for part in parts)


def _is_safe_repository_path(path: str) -> bool:
    repository_path = PurePosixPath(path)
    return (
        bool(path)
        and path == path.strip()
        and "\\" not in path
        and not repository_path.is_absolute()
        and ".." not in repository_path.parts
    )