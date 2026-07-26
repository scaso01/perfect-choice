"""End-to-end journey tests for the interactive CLI wizard.

`run_wizard` is what a real user actually runs, and until now nothing exercised
it. These tests answer every Rich prompt from an ordered script, so they fail if
the question order changes -- not only if the math breaks.
"""

from __future__ import annotations

import pytest
from rich.prompt import Confirm, IntPrompt, Prompt

from perfect_choice.db import Database
from perfect_choice.interactive import run_wizard
from perfect_choice.models import Tier


class PromptScript:
    """Answers Rich prompts from an ordered (expected_substring, answer) script."""

    def __init__(self, steps: list[tuple[str, object]]) -> None:
        self._steps = list(steps)
        self.seen: list[str] = []

    def _next(self, prompt: object) -> object:
        text = str(prompt)
        self.seen.append(text)
        if not self._steps:
            raise AssertionError(f"Wizard asked an unscripted question: {text!r}")
        expected, answer = self._steps.pop(0)
        assert expected in text, f"Expected a prompt containing {expected!r}, got {text!r}"
        return answer

    def install(self, monkeypatch: pytest.MonkeyPatch) -> PromptScript:
        for cls in (Prompt, Confirm, IntPrompt):
            monkeypatch.setattr(
                cls, "ask", lambda prompt="", _script=self, **kw: _script._next(prompt)
            )
        return self

    def assert_exhausted(self) -> None:
        assert not self._steps, f"Wizard never asked for: {self._steps}"


# "Lunch spot" deliberately avoids every match_template() keyword, so the wizard
# takes the manual-criteria path instead of offering a template.
QUICK_SCRIPT: list[tuple[str, object]] = [
    ("Decision title", "Lunch spot"),
    ("Brief description", ""),
    ("Option 1", "Alpha"),
    ("Option 2", "Beta"),
    ("Option 3", ""),  # blank ends the list
    ("Criterion 1", "Taste"),
    ("Is 'Taste' a cost", False),
    ("Criterion 2", "Price"),
    ("Is 'Price' a cost", True),
    ("Criterion 3", ""),  # blank ends the list
    ("Taste (%)", 60),
    ("Price (%)", 40),
    ("Taste", 8),  # Alpha
    ("Price", 6),
    ("Taste", 6),  # Beta
    ("Price", 3),
]


def test_quick_wizard_end_to_end(monkeypatch, sample_config):
    """A full Quick-tier decision, asserted against hand-computed WSM values.

    Taste (benefit, w=0.60): Alpha 8, Beta 6 -> normalized 8/8=1.00, 6/8=0.75
    Price (cost,    w=0.40): Alpha 6, Beta 3 -> normalized 3/6=0.50, 3/3=1.00
    Alpha = 0.60(1.00) + 0.40(0.50) = 0.80
    Beta  = 0.60(0.75) + 0.40(1.00) = 0.85  <- wins despite scoring worse on taste
    """
    script = PromptScript(QUICK_SCRIPT).install(monkeypatch)

    decision = run_wizard(sample_config, force_tier="quick")

    script.assert_exhausted()

    assert decision.title == "Lunch spot"
    assert decision.tier is Tier.QUICK
    assert [a.name for a in decision.alternatives] == ["Alpha", "Beta"]

    weights = {c.name: c.weight for c in decision.criteria}
    assert weights["Taste"] == pytest.approx(0.60)
    assert weights["Price"] == pytest.approx(0.40)
    assert {c.name: c.is_cost for c in decision.criteria} == {
        "Taste": False,
        "Price": True,
    }

    wsm = {r.alternative_name: r for r in decision.rankings["wsm"]}
    assert wsm["Beta"].score == pytest.approx(0.85)
    assert wsm["Alpha"].score == pytest.approx(0.80)
    assert wsm["Beta"].rank == 1
    assert wsm["Alpha"].rank == 2

    # Quick tier is WSM-only and skips AHP, so there is no consistency ratio.
    assert "topsis" not in decision.rankings
    assert decision.consistency_ratio is None


def test_quick_wizard_persists_and_reloads(monkeypatch, sample_config):
    """The decision the wizard saved must survive a round-trip through SQLite."""
    PromptScript(QUICK_SCRIPT).install(monkeypatch)

    decision = run_wizard(sample_config, force_tier="quick")

    with Database(sample_config.db_path) as db:
        loaded = db.get_decision(decision.id)

    assert loaded is not None
    assert loaded.title == "Lunch spot"
    assert loaded.tier is Tier.QUICK
    assert [a.name for a in loaded.alternatives] == ["Alpha", "Beta"]
    assert {c.name: c.weight for c in loaded.criteria} == {
        "Taste": pytest.approx(0.60),
        "Price": pytest.approx(0.40),
    }
    reloaded_wsm = {r.alternative_name: r.rank for r in loaded.rankings["wsm"]}
    assert reloaded_wsm == {"Beta": 1, "Alpha": 2}


def test_weights_must_total_100_before_wizard_continues(monkeypatch, sample_config):
    """Quick tier re-asks for weights until they sum to 100."""
    script = PromptScript(
        QUICK_SCRIPT[:10]
        + [
            ("Taste (%)", 10),  # 10 + 20 = 30, rejected
            ("Price (%)", 20),
            ("Taste (%)", 60),  # retry, accepted
            ("Price (%)", 40),
        ]
        + QUICK_SCRIPT[12:]
    ).install(monkeypatch)

    decision = run_wizard(sample_config, force_tier="quick")

    script.assert_exhausted()
    assert {c.name: c.weight for c in decision.criteria} == {
        "Taste": pytest.approx(0.60),
        "Price": pytest.approx(0.40),
    }


def test_results_survive_a_console_that_cannot_draw_charts(monkeypatch, sample_config):
    """A terminal that can't encode plotext's block characters must not lose the run.

    plotext writes straight to sys.stdout, so a Windows console on a legacy
    code page raises UnicodeEncodeError mid-chart -- after the decision has
    already been saved. The wizard has to fall back to the Rich tables.
    """
    import plotext

    from rich.console import Console

    import perfect_choice.interactive as interactive

    def explode(*args, **kwargs):
        raise UnicodeEncodeError("charmap", "█", 0, 1, "character maps to <undefined>")

    monkeypatch.setattr(plotext, "show", explode)
    recorder = Console(record=True, width=100, force_terminal=True)
    monkeypatch.setattr(interactive, "console", recorder)

    PromptScript(QUICK_SCRIPT).install(monkeypatch)

    decision = run_wizard(sample_config, force_tier="quick")

    assert decision.title == "Lunch spot"
    output = recorder.export_text()
    assert "Rankings" in output
    assert "Beta" in output and "Alpha" in output


def test_standard_wizard_uses_pairwise_ahp(monkeypatch, sample_config):
    """Standard tier runs AHP pairwise comparisons and adds a TOPSIS ranking.

    Answering "1" (equal importance) to all three pairs gives a perfectly
    consistent matrix: equal weights and a consistency ratio of 0.
    """
    script = PromptScript(
        [
            ("Decision title", "Lunch spot"),
            ("Brief description", ""),
            ("Option 1", "Alpha"),
            ("Option 2", "Beta"),
            ("Option 3", ""),
            ("Criterion 1", "Taste"),
            ("Is 'Taste' a cost", False),
            ("Criterion 2", "Price"),
            ("Is 'Price' a cost", True),
            ("Criterion 3", "Speed"),
            ("Is 'Speed' a cost", False),
            ("Criterion 4", ""),
            ("Choice", "1"),  # Taste vs Price
            ("Choice", "1"),  # Taste vs Speed
            ("Choice", "1"),  # Price vs Speed
            ("Taste", 8),  # Alpha
            ("Price", 6),
            ("Speed", 7),
            ("Taste", 6),  # Beta
            ("Price", 3),
            ("Speed", 9),
        ]
    ).install(monkeypatch)

    decision = run_wizard(sample_config, force_tier="standard")

    script.assert_exhausted()

    assert decision.tier is Tier.STANDARD
    assert len(decision.pairwise_comparisons) == 3
    assert decision.consistency_ratio == pytest.approx(0.0, abs=1e-9)
    for criterion in decision.criteria:
        assert criterion.weight == pytest.approx(1 / 3)

    # Standard tier computes both methods; every alternative gets a distinct rank.
    assert set(decision.rankings) == {"wsm", "topsis"}
    for results in decision.rankings.values():
        assert sorted(r.rank for r in results) == [1, 2]
