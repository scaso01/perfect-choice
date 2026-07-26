"""Tests for AHP engine -- pairwise comparison, eigenvector, consistency."""

from __future__ import annotations

import pytest

from perfect_choice.ahp import (
    RANDOM_INDEX,
    build_comparison_matrix,
    compute_consistency_ratio,
    compute_priority_vector,
    required_comparisons,
)
from perfect_choice.models import PairwiseComparison


# ---------------------------------------------------------------------------
# required_comparisons
# ---------------------------------------------------------------------------


class TestRequiredComparisons:
    def test_n1(self) -> None:
        assert required_comparisons(1) == 0

    def test_n2(self) -> None:
        assert required_comparisons(2) == 1

    def test_n3(self) -> None:
        assert required_comparisons(3) == 3

    def test_n5(self) -> None:
        assert required_comparisons(5) == 10

    def test_n7(self) -> None:
        assert required_comparisons(7) == 21

    def test_n10(self) -> None:
        assert required_comparisons(10) == 45


# ---------------------------------------------------------------------------
# build_comparison_matrix
# ---------------------------------------------------------------------------


class TestBuildComparisonMatrix:
    def test_basic_3x3(self) -> None:
        criteria = ["A", "B", "C"]
        comps = [
            PairwiseComparison("A", "B", 3.0),
            PairwiseComparison("A", "C", 5.0),
            PairwiseComparison("B", "C", 2.0),
        ]
        mat = build_comparison_matrix(criteria, comps)
        assert mat[0][1] == 3.0
        assert mat[1][0] == pytest.approx(1.0 / 3.0, abs=1e-9)
        assert mat[0][2] == 5.0
        assert mat[2][0] == pytest.approx(1.0 / 5.0, abs=1e-9)
        assert mat[1][2] == 2.0
        assert mat[2][1] == pytest.approx(0.5, abs=1e-9)

    def test_diagonal_is_one(self) -> None:
        criteria = ["X", "Y", "Z"]
        comps = [
            PairwiseComparison("X", "Y", 2.0),
            PairwiseComparison("X", "Z", 4.0),
            PairwiseComparison("Y", "Z", 3.0),
        ]
        mat = build_comparison_matrix(criteria, comps)
        for i in range(3):
            assert mat[i][i] == 1.0

    def test_reciprocal_property(self) -> None:
        """mat[i][j] * mat[j][i] == 1.0 for all i, j."""
        criteria = ["A", "B", "C", "D"]
        comps = [
            PairwiseComparison("A", "B", 7.0),
            PairwiseComparison("A", "C", 3.0),
            PairwiseComparison("A", "D", 5.0),
            PairwiseComparison("B", "C", 1.0 / 3.0),
            PairwiseComparison("B", "D", 1.0 / 5.0),
            PairwiseComparison("C", "D", 2.0),
        ]
        mat = build_comparison_matrix(criteria, comps)
        n = len(criteria)
        for i in range(n):
            for j in range(n):
                assert mat[i][j] * mat[j][i] == pytest.approx(1.0, abs=1e-9)

    def test_2x2(self) -> None:
        criteria = ["P", "Q"]
        comps = [PairwiseComparison("P", "Q", 5.0)]
        mat = build_comparison_matrix(criteria, comps)
        assert mat[0][0] == 1.0
        assert mat[0][1] == 5.0
        assert mat[1][0] == pytest.approx(0.2, abs=1e-9)
        assert mat[1][1] == 1.0

    def test_empty_comparisons(self) -> None:
        """No comparisons => identity matrix."""
        criteria = ["A", "B"]
        mat = build_comparison_matrix(criteria, [])
        assert mat == [[1.0, 1.0], [1.0, 1.0]]


# ---------------------------------------------------------------------------
# compute_priority_vector
# ---------------------------------------------------------------------------


class TestComputePriorityVector:
    def test_identity_gives_uniform(self) -> None:
        mat = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        w = compute_priority_vector(mat)
        for wi in w:
            assert wi == pytest.approx(1.0 / 3.0, abs=1e-6)

    def test_weights_sum_to_one(self) -> None:
        mat = [
            [1.0, 3.0, 5.0],
            [1.0 / 3.0, 1.0, 2.0],
            [1.0 / 5.0, 0.5, 1.0],
        ]
        w = compute_priority_vector(mat)
        assert sum(w) == pytest.approx(1.0, abs=1e-6)

    def test_2x2_matrix(self) -> None:
        """If A is 3x more important than B, weights should be ~0.75 and ~0.25."""
        mat = [[1.0, 3.0], [1.0 / 3.0, 1.0]]
        w = compute_priority_vector(mat)
        assert w[0] == pytest.approx(0.75, abs=0.01)
        assert w[1] == pytest.approx(0.25, abs=0.01)

    def test_1x1_matrix(self) -> None:
        mat = [[1.0]]
        w = compute_priority_vector(mat)
        assert w == [pytest.approx(1.0, abs=1e-9)]

    def test_saaty_drink_example(self) -> None:
        """Saaty's classic 3-criteria drink example.

        Criteria: Taste, Nutrition, Cost
        Taste vs Nutrition = 3 (taste moderately preferred)
        Taste vs Cost = 7 (taste very strongly preferred)
        Nutrition vs Cost = 3 (nutrition moderately preferred)

        Power iteration eigenvector: Taste~0.669, Nutrition~0.243, Cost~0.088
        (differs slightly from geometric mean approximation in some textbooks)
        """
        mat = [
            [1.0, 3.0, 7.0],
            [1.0 / 3.0, 1.0, 3.0],
            [1.0 / 7.0, 1.0 / 3.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        assert w[0] == pytest.approx(0.669, abs=0.02)
        assert w[1] == pytest.approx(0.243, abs=0.02)
        assert w[2] == pytest.approx(0.088, abs=0.02)

    def test_strong_dominance(self) -> None:
        """One criterion strongly dominates: 9x each other."""
        mat = [
            [1.0, 9.0, 9.0],
            [1.0 / 9.0, 1.0, 1.0],
            [1.0 / 9.0, 1.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        assert w[0] > 0.8  # dominant
        assert w[1] == pytest.approx(w[2], abs=0.01)

    def test_4x4_consistent(self) -> None:
        """Perfectly consistent 4x4: w = [4, 2, 1, 1] / 8."""
        mat = [
            [1.0, 2.0, 4.0, 4.0],
            [0.5, 1.0, 2.0, 2.0],
            [0.25, 0.5, 1.0, 1.0],
            [0.25, 0.5, 1.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        assert w[0] == pytest.approx(0.5, abs=0.01)
        assert w[1] == pytest.approx(0.25, abs=0.01)
        assert w[2] == pytest.approx(0.125, abs=0.01)
        assert w[3] == pytest.approx(0.125, abs=0.01)


# ---------------------------------------------------------------------------
# compute_consistency_ratio
# ---------------------------------------------------------------------------


class TestComputeConsistencyRatio:
    def test_n1_returns_zero(self) -> None:
        mat = [[1.0]]
        w = [1.0]
        assert compute_consistency_ratio(mat, w) == 0.0

    def test_n2_returns_zero(self) -> None:
        mat = [[1.0, 5.0], [0.2, 1.0]]
        w = [0.833, 0.167]
        assert compute_consistency_ratio(mat, w) == 0.0

    def test_perfectly_consistent_3x3(self) -> None:
        """Consistent matrix => CR approx 0."""
        mat = [
            [1.0, 2.0, 4.0],
            [0.5, 1.0, 2.0],
            [0.25, 0.5, 1.0],
        ]
        w = compute_priority_vector(mat)
        cr = compute_consistency_ratio(mat, w)
        assert cr == pytest.approx(0.0, abs=0.01)

    def test_consistent_under_threshold(self) -> None:
        """Saaty drink example should have CR < 0.10."""
        mat = [
            [1.0, 3.0, 7.0],
            [1.0 / 3.0, 1.0, 3.0],
            [1.0 / 7.0, 1.0 / 3.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        cr = compute_consistency_ratio(mat, w)
        assert cr < 0.10

    def test_very_inconsistent(self) -> None:
        """Highly inconsistent matrix => CR > 0.10."""
        # A >> B, B >> C, but C >> A -- circular preference
        mat = [
            [1.0, 9.0, 1.0 / 9.0],
            [1.0 / 9.0, 1.0, 9.0],
            [9.0, 1.0 / 9.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        cr = compute_consistency_ratio(mat, w)
        assert cr > 0.10

    def test_cr_is_nonnegative(self) -> None:
        mat = [
            [1.0, 3.0, 5.0],
            [1.0 / 3.0, 1.0, 2.0],
            [1.0 / 5.0, 0.5, 1.0],
        ]
        w = compute_priority_vector(mat)
        cr = compute_consistency_ratio(mat, w)
        assert cr >= 0.0

    def test_4x4_consistent(self) -> None:
        mat = [
            [1.0, 2.0, 4.0, 4.0],
            [0.5, 1.0, 2.0, 2.0],
            [0.25, 0.5, 1.0, 1.0],
            [0.25, 0.5, 1.0, 1.0],
        ]
        w = compute_priority_vector(mat)
        cr = compute_consistency_ratio(mat, w)
        assert cr == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# RANDOM_INDEX coverage
# ---------------------------------------------------------------------------


class TestRandomIndex:
    def test_entries_count(self) -> None:
        assert len(RANDOM_INDEX) == 15

    def test_n1_and_n2_are_zero(self) -> None:
        assert RANDOM_INDEX[1] == 0.0
        assert RANDOM_INDEX[2] == 0.0

    def test_values_generally_increase(self) -> None:
        """RI generally increases with n (not strictly monotonic)."""
        assert RANDOM_INDEX[3] < RANDOM_INDEX[10]
        assert RANDOM_INDEX[5] < RANDOM_INDEX[15]
