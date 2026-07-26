"""Tests for WSM and TOPSIS scoring algorithms."""

from __future__ import annotations

import pytest

from perfect_choice.models import Criterion, Score, ScoreMethod
from perfect_choice.scoring import _build_matrix, topsis_rank, wsm_rank


# ---------------------------------------------------------------------------
# _build_matrix
# ---------------------------------------------------------------------------


class TestBuildMatrix:
    def test_correct_mapping(self) -> None:
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [
            Score("A", "C1", 8.0),
            Score("A", "C2", 6.0),
            Score("B", "C1", 4.0),
            Score("B", "C2", 9.0),
        ]
        mat = _build_matrix(alts, crits, scores)
        assert mat[0][0] == 8.0  # A, C1
        assert mat[0][1] == 6.0  # A, C2
        assert mat[1][0] == 4.0  # B, C1
        assert mat[1][1] == 9.0  # B, C2

    def test_missing_score_defaults_zero(self) -> None:
        alts = ["A"]
        crits = [Criterion("C1", 1.0)]
        mat = _build_matrix(alts, crits, [])
        assert mat[0][0] == 0.0


# ---------------------------------------------------------------------------
# wsm_rank
# ---------------------------------------------------------------------------


class TestWsmRank:
    def test_simple_2x2(self) -> None:
        """Hand-calculable example.

        Alt A: C1=8, C2=6.  Alt B: C1=4, C2=9.
        Weights: C1=0.6, C2=0.4.  Both benefit.
        Normalized: A_C1=8/8=1, A_C2=6/9=0.667, B_C1=4/8=0.5, B_C2=9/9=1.
        WSM_A = 0.6*1 + 0.4*0.667 = 0.867
        WSM_B = 0.6*0.5 + 0.4*1 = 0.700
        A wins.
        """
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.6), Criterion("C2", 0.4)]
        scores = [
            Score("A", "C1", 8.0),
            Score("A", "C2", 6.0),
            Score("B", "C1", 4.0),
            Score("B", "C2", 9.0),
        ]
        result = wsm_rank(alts, crits, scores)
        assert result[0].alternative_name == "A"
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[0].score == pytest.approx(0.867, abs=0.01)
        assert result[1].score == pytest.approx(0.700, abs=0.01)

    def test_cost_criterion(self) -> None:
        """Lower cost is better.

        Alt A: cost=2, Alt B: cost=8.
        Normalized: A_cost = 2/2 = 1, B_cost = 2/8 = 0.25.
        A should rank #1.
        """
        alts = ["A", "B"]
        crits = [Criterion("Cost", 1.0, is_cost=True)]
        scores = [Score("A", "Cost", 2.0), Score("B", "Cost", 8.0)]
        result = wsm_rank(alts, crits, scores)
        assert result[0].alternative_name == "A"
        assert result[0].score > result[1].score

    def test_all_equal_scores(self) -> None:
        """All alternatives score identically => same WSM score."""
        alts = ["A", "B", "C"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [
            Score(alt, crit.name, 5.0) for alt in alts for crit in crits
        ]
        result = wsm_rank(alts, crits, scores)
        scores_only = [r.score for r in result]
        assert all(s == pytest.approx(scores_only[0], abs=1e-9) for s in scores_only)

    def test_single_criterion(self) -> None:
        alts = ["X", "Y"]
        crits = [Criterion("Only", 1.0)]
        scores = [Score("X", "Only", 10.0), Score("Y", "Only", 3.0)]
        result = wsm_rank(alts, crits, scores)
        assert result[0].alternative_name == "X"
        assert result[0].score == pytest.approx(1.0, abs=0.01)

    def test_ranking_order_descending(self) -> None:
        alts = ["A", "B", "C"]
        crits = [Criterion("Q", 1.0)]
        scores = [Score("A", "Q", 3.0), Score("B", "Q", 9.0), Score("C", "Q", 6.0)]
        result = wsm_rank(alts, crits, scores)
        assert result[0].alternative_name == "B"
        assert result[1].alternative_name == "C"
        assert result[2].alternative_name == "A"
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[2].rank == 3

    def test_breakdown_keys(self) -> None:
        alts = ["A"]
        crits = [Criterion("C1", 0.6), Criterion("C2", 0.4)]
        scores = [Score("A", "C1", 5.0), Score("A", "C2", 5.0)]
        result = wsm_rank(alts, crits, scores)
        assert "C1" in result[0].breakdown
        assert "C2" in result[0].breakdown

    def test_method_is_wsm(self) -> None:
        alts = ["A"]
        crits = [Criterion("C1", 1.0)]
        scores = [Score("A", "C1", 5.0)]
        result = wsm_rank(alts, crits, scores)
        assert result[0].method == ScoreMethod.WSM

    def test_three_alternatives_three_criteria(self) -> None:
        """Larger example -- verify relative ordering is sensible."""
        alts = ["A", "B", "C"]
        crits = [
            Criterion("Speed", 0.4),
            Criterion("Quality", 0.35),
            Criterion("Price", 0.25, is_cost=True),
        ]
        scores = [
            Score("A", "Speed", 9.0), Score("A", "Quality", 7.0), Score("A", "Price", 5.0),
            Score("B", "Speed", 6.0), Score("B", "Quality", 9.0), Score("B", "Price", 3.0),
            Score("C", "Speed", 7.0), Score("C", "Quality", 5.0), Score("C", "Price", 8.0),
        ]
        result = wsm_rank(alts, crits, scores)
        # Just verify structural integrity
        assert len(result) == 3
        assert result[0].rank == 1
        assert result[0].score >= result[1].score >= result[2].score


# ---------------------------------------------------------------------------
# topsis_rank
# ---------------------------------------------------------------------------


class TestTopsisRank:
    def test_simple_2x2(self) -> None:
        """Basic 2-alt, 2-crit TOPSIS."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [
            Score("A", "C1", 9.0),
            Score("A", "C2", 1.0),
            Score("B", "C1", 1.0),
            Score("B", "C2", 9.0),
        ]
        result = topsis_rank(alts, crits, scores)
        # Symmetric input with equal weights => tied
        assert result[0].score == pytest.approx(result[1].score, abs=0.01)

    def test_clear_winner(self) -> None:
        """One alternative dominates on all criteria."""
        alts = ["A", "B"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [
            Score("A", "C1", 9.0), Score("A", "C2", 9.0),
            Score("B", "C1", 1.0), Score("B", "C2", 1.0),
        ]
        result = topsis_rank(alts, crits, scores)
        assert result[0].alternative_name == "A"
        assert result[0].score == pytest.approx(1.0, abs=0.01)
        assert result[1].score == pytest.approx(0.0, abs=0.01)

    def test_cost_criterion(self) -> None:
        """Cost criterion: lower is better."""
        alts = ["Cheap", "Expensive"]
        crits = [Criterion("Price", 1.0, is_cost=True)]
        scores = [Score("Cheap", "Price", 2.0), Score("Expensive", "Price", 10.0)]
        result = topsis_rank(alts, crits, scores)
        assert result[0].alternative_name == "Cheap"

    def test_all_identical_alternatives(self) -> None:
        """All alternatives identical => all have same closeness."""
        alts = ["A", "B", "C"]
        crits = [Criterion("C1", 0.5), Criterion("C2", 0.5)]
        scores = [Score(a, c.name, 5.0) for a in alts for c in crits]
        result = topsis_rank(alts, crits, scores)
        scores_only = [r.score for r in result]
        # All closeness values should be equal (0.0 since d_plus == d_minus == 0)
        for s in scores_only:
            assert s == pytest.approx(scores_only[0], abs=1e-9)

    def test_ranking_consistency(self) -> None:
        """Rank 1 has highest score, rank N has lowest."""
        alts = ["A", "B", "C"]
        crits = [Criterion("Q", 1.0)]
        scores = [Score("A", "Q", 3.0), Score("B", "Q", 9.0), Score("C", "Q", 6.0)]
        result = topsis_rank(alts, crits, scores)
        assert result[0].rank == 1
        assert result[0].score >= result[1].score
        assert result[1].score >= result[2].score
        assert result[0].alternative_name == "B"

    def test_method_is_topsis(self) -> None:
        alts = ["A"]
        crits = [Criterion("C1", 1.0)]
        scores = [Score("A", "C1", 5.0)]
        result = topsis_rank(alts, crits, scores)
        assert result[0].method == ScoreMethod.TOPSIS

    def test_breakdown_has_weighted_values(self) -> None:
        alts = ["A"]
        crits = [Criterion("C1", 0.7), Criterion("C2", 0.3)]
        scores = [Score("A", "C1", 8.0), Score("A", "C2", 4.0)]
        result = topsis_rank(alts, crits, scores)
        assert "C1" in result[0].breakdown
        assert "C2" in result[0].breakdown

    def test_textbook_3x4(self) -> None:
        """3 alternatives, 4 criteria -- verify structural correctness."""
        alts = ["A", "B", "C"]
        crits = [
            Criterion("C1", 0.4),
            Criterion("C2", 0.3),
            Criterion("C3", 0.2),
            Criterion("C4", 0.1, is_cost=True),
        ]
        scores = [
            Score("A", "C1", 8.0), Score("A", "C2", 7.0), Score("A", "C3", 9.0), Score("A", "C4", 5.0),
            Score("B", "C1", 7.0), Score("B", "C2", 9.0), Score("B", "C3", 6.0), Score("B", "C4", 2.0),
            Score("C", "C1", 9.0), Score("C", "C2", 5.0), Score("C", "C3", 7.0), Score("C", "C4", 8.0),
        ]
        result = topsis_rank(alts, crits, scores)
        assert len(result) == 3
        assert result[0].rank == 1
        assert result[2].rank == 3
        # All closeness between 0 and 1
        for r in result:
            assert 0.0 <= r.score <= 1.0

    def test_mixed_cost_benefit(self) -> None:
        """Mixing cost and benefit criteria."""
        alts = ["A", "B"]
        crits = [
            Criterion("Performance", 0.6),
            Criterion("Price", 0.4, is_cost=True),
        ]
        scores = [
            Score("A", "Performance", 9.0), Score("A", "Price", 8.0),
            Score("B", "Performance", 7.0), Score("B", "Price", 3.0),
        ]
        result = topsis_rank(alts, crits, scores)
        # B has lower price (better for cost) but lower performance
        # A has higher performance but higher price
        assert len(result) == 2
        assert result[0].score > result[1].score
