"""Environment-backed application settings."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    github_webhook_secret: str = ""
    database_path: Path = Path("data/codementor.sqlite3")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            database_path=Path(
                os.environ.get("CODEMENTOR_DB_PATH", "data/codementor.sqlite3")
            ),
        )