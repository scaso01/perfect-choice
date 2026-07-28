"""Tests for result display.

Regression guard: the plotext charts used to be drawn *instead of* the Rich
tables whenever the optional `charts` extra was installed. The charts carry no
value labels, so installing the extra hid every number, and the output stopped
matching the screenshots in the README.
"""
from __future__ import annotations

import pytest

from perfect_choice.interactive import display_results
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
def ranked_decision() -> Decision:
    return Decision(
        id="abcdef1234567890abcdef1234567890",
        title="Pick a database",
        description="",
        tier=Tier.QUICK,
        criteria=(
            Criterion(name="Speed", weight=0.6),
            Criterion(name="Price", weight=0.4, is_cost=True),
        ),
        alternatives=(Alternative(name="SQLite"), Alternative(name="Postgres")),
        rankings={
            "wsm": (
                RankingResult(
                    alternative_name="SQLite",
                    score=0.9333,
                    rank=1,
                    method=ScoreMethod.WSM,
                ),
                RankingResult(
                    alternative_name="Postgres",
                    score=0.7143,
                    rank=2,
                    method=ScoreMethod.WSM,
                ),
            ),
        },
        created_at="2026-07-28T12:00:00+00:00",
        status=DecisionStatus.COMPLETED,
    )


def _render(decision: Decision, capsys) -> str:
    display_results(decision)
    return capsys.readouterr().out


def test_scores_are_shown_when_plotext_is_installed(ranked_decision, capsys):
    """The numbers must survive the charts extra being present."""
    pytest.importorskip("plotext")

    out = _render(ranked_decision, capsys)

    assert "0.9333" in out, "winning score missing from output"
    assert "0.7143" in out, "runner-up score missing from output"
    assert "60.0%" in out, "criterion weight missing from output"


def test_scores_are_shown_when_plotext_is_missing(ranked_decision, monkeypatch, capsys):
    """Same output guarantee on a core-only install."""
    import builtins

    real_import = builtins.__import__

    def _no_plotext(name, *args, **kwargs):
        if name == "plotext":
            raise ImportError("plotext is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_plotext)

    out = _render(ranked_decision, capsys)

    assert "0.9333" in out
    assert "0.7143" in out
