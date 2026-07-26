"""Tests for the optional memory webhook."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from perfect_choice.brain import (
    _format_decision,
    _post_to_brain,
    store_decision_in_brain,
    update_brain_context,
)
from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    RankingResult,
    ScoreMethod,
    Tier,
)


@pytest.fixture
def sample_decision() -> Decision:
    """A fully populated decision for testing."""
    return Decision(
        id="abcdef1234567890abcdef1234567890",
        title="Pick a database",
        description="Choose the best DB for our project",
        tier=Tier.STANDARD,
        criteria=(
            Criterion(name="Speed", weight=0.6),
            Criterion(name="Cost", weight=0.4, is_cost=True),
        ),
        alternatives=(
            Alternative(name="PostgreSQL"),
            Alternative(name="SQLite"),
        ),
        rankings={
            "wsm": (
                RankingResult(
                    alternative_name="PostgreSQL",
                    score=0.750,
                    rank=1,
                    method=ScoreMethod.WSM,
                ),
                RankingResult(
                    alternative_name="SQLite",
                    score=0.600,
                    rank=2,
                    method=ScoreMethod.WSM,
                ),
            ),
        },
        consistency_ratio=0.045,
        llm_summary="PostgreSQL wins on speed; SQLite is cheaper.",
        created_at="2026-03-23T12:00:00+00:00",
        status=DecisionStatus.COMPLETED,
    )


@pytest.fixture
def minimal_decision() -> Decision:
    """A decision with no rankings, no CR, no LLM summary."""
    return Decision(
        id="00000000111111112222222233333333",
        title="Minimal test",
        description="",
        tier=Tier.QUICK,
        criteria=(Criterion(name="Quality", weight=1.0),),
        alternatives=(
            Alternative(name="A"),
            Alternative(name="B"),
        ),
        created_at="2026-01-01T00:00:00+00:00",
        status=DecisionStatus.IN_PROGRESS,
    )


@pytest.fixture
def brain_enabled(monkeypatch):
    """Opt in to brain sync, which is disabled unless the env var is set."""
    monkeypatch.setenv(
        "PERFECT_CHOICE_BRAIN_URL", "http://localhost:9000/remember"
    )


def _mock_urlopen_ok(monkeypatch):
    """Patch urllib.request.urlopen to return {"ok": true}."""
    body = json.dumps({"ok": True}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **kw: mock_resp
    )
    return mock_resp


def _mock_urlopen_fail(monkeypatch):
    """Patch urllib.request.urlopen to raise ConnectionError."""
    def _raise(*args, **kwargs):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)


# -------------------------------------------------------------------
# _format_decision
# -------------------------------------------------------------------


class TestFormatDecision:
    def test_includes_title_alternatives_criteria_rankings(
        self, sample_decision: Decision
    ):
        text = _format_decision(sample_decision)
        assert "Pick a database" in text
        assert "PostgreSQL" in text
        assert "SQLite" in text
        assert "Speed (60%)" in text
        assert "Cost (40%)" in text
        assert "WSM ranking:" in text

    def test_handles_empty_rankings(self, minimal_decision: Decision):
        text = _format_decision(minimal_decision)
        assert "Minimal test" in text
        assert "Quality" in text
        # No rankings section
        assert "ranking:" not in text

    def test_includes_consistency_ratio(self, sample_decision: Decision):
        text = _format_decision(sample_decision)
        assert "Consistency Ratio: 0.045" in text

    def test_excludes_consistency_ratio_when_none(
        self, minimal_decision: Decision
    ):
        text = _format_decision(minimal_decision)
        assert "Consistency Ratio" not in text


# -------------------------------------------------------------------
# store_decision_in_brain
# -------------------------------------------------------------------


class TestStoreDecisionInBrain:
    def test_returns_false_on_connection_error(
        self, monkeypatch, brain_enabled, sample_decision: Decision
    ):
        _mock_urlopen_fail(monkeypatch)
        assert store_decision_in_brain(sample_decision) is False


class TestBrainIsOptIn:
    """Brain sync is off unless configured -- it must not touch the network."""

    def test_no_request_when_unconfigured(
        self, monkeypatch, sample_decision: Decision
    ):
        def _boom(*args, **kwargs):
            raise AssertionError(
                "brain sync attempted a request while unconfigured"
            )

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        assert store_decision_in_brain(sample_decision) is False

    def test_blank_url_counts_as_unconfigured(
        self, monkeypatch, sample_decision: Decision
    ):
        monkeypatch.setenv("PERFECT_CHOICE_BRAIN_URL", "   ")

        def _boom(*args, **kwargs):
            raise AssertionError(
                "brain sync attempted a request for a blank URL"
            )

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        assert store_decision_in_brain(sample_decision) is False

    def test_configured_url_is_used(
        self, monkeypatch, brain_enabled, sample_decision: Decision
    ):
        seen: list[str] = []
        body = json.dumps({"ok": True}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        def _capture(req, *args, **kwargs):
            seen.append(req.full_url)
            return mock_resp

        monkeypatch.setattr("urllib.request.urlopen", _capture)
        assert store_decision_in_brain(sample_decision) is True
        assert seen == ["http://localhost:9000/remember"]


# -------------------------------------------------------------------
# update_brain_context
# -------------------------------------------------------------------


class TestUpdateBrainContext:
    def test_formats_last_10_decisions(
        self, monkeypatch, brain_enabled, sample_decision
    ):
        _mock_urlopen_ok(monkeypatch)
        decisions = [sample_decision] * 12
        result = update_brain_context(decisions)
        # Should succeed (mocked ok)
        assert result is True

    def test_returns_false_for_empty_list(self):
        assert update_brain_context([]) is False


# -------------------------------------------------------------------
# _post_to_brain
# -------------------------------------------------------------------


class TestPostToBrain:
    def test_returns_true_on_ok_response(self, monkeypatch, brain_enabled):
        _mock_urlopen_ok(monkeypatch)
        payload = {"content": "test", "memory_type": "decision"}
        assert _post_to_brain(payload) is True

    def test_returns_false_on_exception(self, monkeypatch, brain_enabled):
        _mock_urlopen_fail(monkeypatch)
        payload = {"content": "test", "memory_type": "decision"}
        assert _post_to_brain(payload) is False
