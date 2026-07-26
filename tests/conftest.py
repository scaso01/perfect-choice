"""Test fixtures and guards for Perfect Choice."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all PERFECT_CHOICE_* env vars to isolate tests."""
    import os

    for key in list(os.environ):
        if key.startswith("PERFECT_CHOICE_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real HTTP requests in tests."""
    import httpx
    import urllib.request

    def _blocked(*args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "Real HTTP requests are blocked in tests. "
            "Use respx or mock the client."
        )

    monkeypatch.setattr(httpx.Client, "send", _blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary database path for tests."""
    return str(tmp_path / "test_decisions.db")


@pytest.fixture
def sample_config(tmp_path):
    """Config pointing at temp DB with LLM disabled."""
    from perfect_choice.config import Config

    return Config(
        db_path=str(tmp_path / "test.db"),
        no_llm=True,
    )
