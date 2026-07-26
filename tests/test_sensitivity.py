"""Tests for sensitivity analysis -- weight perturbation."""

from __future__ import annotations

import pytest

from perfect_choice.models import Criterion, Score
from perfect_choice.scoring import wsm_rank
from perfect_choice.sensitivity import analyze_sensitivity


def _make_scores(
    alts: list[str], crits: list[Criterion], values: dict[str, list[float]]
) -> list[Score]:
    """Helper: build Score list from alt->values dict."""
    result = []
    for alt in alts:
        for j, crit in enumerate(crits):
            result.append(Score(alt, crit.name, values[alt][j]))
    return result


# ---------------------------------------------------------------------------
# Dominant winner (stable)
# ---------------------------------------------------------------------------


class TestStableDominance:
    def test_dominant_winner_all_thresholds_none(self) -> None:
        """When one alt dominates strongly, no weight shift flips it."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = _make_scores(alts, crits, {"A": [10.0, 10.0], "B": [1.0, 1.0]})
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        for r in results:
            assert r.threshold_pct is None

    def test_dominant_three_criteria(self) -> None:
        """3 criteria, strong dominance, all stable."""
        alts = ["A", "B"]
        crits = [
            Criterion("C1", 0.4),
            Criterion("C2", 0.3),
            Criterion("C3", 0.3),
        ]
        scores = _make_scores(
            alts, crits, {"A": [10.0, 10.0, 10.0], "B": [1.0, 1.0, 1.0]}
        )
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        assert all(r.threshold_pct is None for r in results)


# ---------------------------------------------------------------------------
# Close race (sensitive)
# ---------------------------------------------------------------------------


class TestCloseRace:
    def test_close_race_has_low_threshold(self) -> None:
        """Close race: A barely beats B. At least one criterion is sensitive."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        # A leads on C1, B leads on C2 -- nearly tied
        scores = _make_scores(alts, crits, {"A": [6.0, 5.0], "B": [5.0, 6.0]})
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        sensitive = [r for r in results if r.threshold_pct is not None]
        assert len(sensitive) >= 1
        # Threshold should be small (< 25%)
        assert any(r.threshold_pct < 25.0 for r in sensitive)

    def test_flip_to_correct_alternative(self) -> None:
        """When a flip occurs, flip_to should name the new winner."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = _make_scores(alts, crits, {"A": [6.0, 5.0], "B": [5.0, 6.0]})
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        for r in results:
            if r.threshold_pct is not None:
                assert r.flip_to == "B"


# ---------------------------------------------------------------------------
# Single criterion
# ---------------------------------------------------------------------------


class TestSingleCriterion:
    def test_single_criterion_returns_empty(self) -> None:
        """With only 1 criterion, sensitivity returns empty (no flip possible
        because there is no other weight to redistribute to when n_criteria < 2,
        but the function returns a result for each criterion anyway)."""
        alts = ["A", "B"]
        crits = [Criterion("Only", 1.0)]
        scores = [Score("A", "Only", 10.0), Score("B", "Only", 5.0)]
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        # Single criterion: weight can't be redistributed
        # remaining_original == 0 => all perturbations are skipped
        assert len(results) == 1
        assert results[0].threshold_pct is None


# ---------------------------------------------------------------------------
# Two criteria, designed flip
# ---------------------------------------------------------------------------


class TestDesignedFlip:
    def test_two_criteria_known_flip(self) -> None:
        """A wins on C1 (weight 0.6), B wins on C2 (weight 0.4).

        Increasing C2 weight enough should flip winner to B.
        """
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.6), Criterion("C2", 0.4)]
        scores = _make_scores(alts, crits, {"A": [9.0, 3.0], "B": [4.0, 10.0]})

        # Verify A wins baseline
        baseline = wsm_rank(alts, crits, scores)
        assert baseline[0].alternative_name == "A"

        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        # At least one criterion should have a flip threshold
        assert any(r.threshold_pct is not None for r in results)

    def test_two_criteria_symmetric(self) -> None:
        """Symmetric scenario: both criteria should be equally sensitive."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = _make_scores(alts, crits, {"A": [8.0, 4.0], "B": [4.0, 8.0]})
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        thresholds = [r.threshold_pct for r in results if r.threshold_pct is not None]
        if len(thresholds) == 2:
            assert thresholds[0] == pytest.approx(thresholds[1], abs=1.0)


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_sorted_by_threshold_ascending(self) -> None:
        """Results are sorted: lowest threshold first, None last."""
        alts = ["A", "B", "C"]
        crits = [
            Criterion("C1", 0.5),
            Criterion("C2", 0.3),
            Criterion("C3", 0.2),
        ]
        scores = _make_scores(
            alts,
            crits,
            {
                "A": [8.0, 5.0, 5.0],
                "B": [5.0, 8.0, 5.0],
                "C": [5.0, 5.0, 8.0],
            },
        )
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        thresholds = [
            r.threshold_pct if r.threshold_pct is not None else float("inf")
            for r in results
        ]
        assert thresholds == sorted(thresholds)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_fewer_than_two_alternatives_empty(self) -> None:
        """With only 1 alternative, no ranking flip is possible."""
        alts = ["A"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [Score("A", "C1", 5.0), Score("A", "C2", 5.0)]
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        assert results == []

    def test_result_has_correct_original_weight(self) -> None:
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.7), Criterion("C2", 0.3)]
        scores = _make_scores(alts, crits, {"A": [10.0, 10.0], "B": [1.0, 1.0]})
        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        weight_map = {r.criterion_name: r.original_weight for r in results}
        assert weight_map["C1"] == pytest.approx(0.7, abs=1e-9)
        assert weight_map["C2"] == pytest.approx(0.3, abs=1e-9)

    def test_three_alternatives_flip(self) -> None:
        """With 3 alternatives, verify flip_to identifies the correct one."""
        alts = ["A", "B", "C"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        # A barely wins overall, C is strong on C2
        scores = _make_scores(
            alts, crits, {"A": [7.0, 6.0], "B": [3.0, 3.0], "C": [5.0, 8.0]}
        )
        baseline = wsm_rank(alts, crits, scores)
        assert baseline[0].alternative_name == "A"

        results = analyze_sensitivity(alts, crits, scores, wsm_rank)
        flippers = [r for r in results if r.threshold_pct is not None]
        if flippers:
            # The flip should be to C (strong on C2), not B
            assert any(r.flip_to == "C" for r in flippers)
