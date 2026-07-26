"""Configuration via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _default_db_path() -> str:
    """Where decisions live unless PERFECT_CHOICE_DB_PATH says otherwise.

    Under the user's home, not the package tree: a plain `pip install .`
    resolves the package into site-packages, and a repo-relative default
    would put the database inside the virtualenv where nobody would find
    it (and where it may not be writable).
    """
    return os.environ.get(
        "PERFECT_CHOICE_DB_PATH",
        str(Path.home() / ".perfect-choice" / "decisions.db"),
    )


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable application configuration."""

    db_path: str = field(default_factory=_default_db_path)
    llm_url: str = field(
        default_factory=lambda: os.environ.get(
            "PERFECT_CHOICE_LLM_URL", "http://localhost:8080"
        )
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("PERFECT_CHOICE_LLM_MODEL", "")
    )
    llm_timeout: int = field(
        default_factory=lambda: int(
            os.environ.get("PERFECT_CHOICE_LLM_TIMEOUT", "300")
        )
    )
    no_llm: bool = field(
        default_factory=lambda: os.environ.get(
            "PERFECT_CHOICE_NO_LLM", ""
        ).lower()
        in ("1", "true", "yes")
    )
