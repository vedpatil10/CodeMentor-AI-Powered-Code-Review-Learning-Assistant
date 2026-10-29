"""Environment-backed application settings."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    github_webhook_secret: str = ""
    database_path: Path = Path("data/codementor.sqlite3")
    openai_api_key: str = ""
    openai_model: str = "gpt-6-astra"
    llm_timeout_seconds: float = 45
    max_output_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            database_path=Path(
                os.environ.get("CODEMENTOR_DB_PATH", "data/codementor.sqlite3")
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-6-astra"),
            llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "45")),
            max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS", "4096")),
        )