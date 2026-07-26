"""AHP engine -- pairwise comparison, eigenvector, consistency ratio."""

from __future__ import annotations

from collections.abc import Sequence

from perfect_choice.models import PairwiseComparison

# Saaty Random Index table for n=1..15
RANDOM_INDEX: dict[int, float] = {
    1: 0.0,
    2: 0.0,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.48,
    13: 1.56,
    14: 1.57,
    15: 1.59,
}


def required_comparisons(n: int) -> int:
    """Number of pairwise comparisons needed: n*(n-1)/2."""
    return n * (n - 1) // 2


def build_comparison_matrix(
    criteria: Sequence[str],
    comparisons: Sequence[PairwiseComparison],
) -> list[list[float]]:
    """Build n x n reciprocal matrix from pairwise comparisons.

    Matrix[i][j] = value means criterion i is ``value`` times more important
    than j.  Matrix[j][i] = 1/value (reciprocal).  Diagonal = 1.0.
    """
    n = len(criteria)
    idx = {name: i for i, name in enumerate(criteria)}
    matrix = [[1.0] * n for _ in range(n)]
    for comp in comparisons:
        i, j = idx[comp.criterion_a], idx[comp.criterion_b]
        matrix[i][j] = comp.value
        matrix[j][i] = 1.0 / comp.value
    return matrix


def compute_priority_vector(
    matrix: list[list[float]],
    max_iter: int = 100,
    tol: float = 1e-8,
) -> list[float]:
    """Compute principal eigenvector via power iteration.

    Returns normalized priority weights (sum to 1.0).
    """
    n = len(matrix)
    v = [1.0 / n] * n
    for _ in range(max_iter):
        v_new = [0.0] * n
        for i in range(n):
            for j in range(n):
                v_new[i] += matrix[i][j] * v[j]
        total = sum(v_new)
        if total == 0:
            return [1.0 / n] * n
        v_new = [x / total for x in v_new]
        if max(abs(a - b) for a, b in zip(v_new, v)) < tol:
            return v_new
        v = v_new
    return v


def compute_consistency_ratio(
    matrix: list[list[float]],
    weights: list[float],
) -> float:
    """Compute Saaty's Consistency Ratio.

    CR = CI / RI where CI = (lambda_max - n) / (n - 1).
    CR < 0.10 means acceptable consistency.
    Returns 0.0 for n <= 2 (always consistent).
    """
    n = len(matrix)
    if n <= 2:
        return 0.0
    # Compute lambda_max: for each row, (A*w)[i] / w[i], then average
    aw = [0.0] * n
    for i in range(n):
        for j in range(n):
            aw[i] += matrix[i][j] * weights[j]
    lambdas = [
        aw[i] / weights[i] if weights[i] > 0 else 0.0 for i in range(n)
    ]
    lambda_max = sum(lambdas) / n
    ci = (lambda_max - n) / (n - 1)
    ri = RANDOM_INDEX.get(n, 1.59)
    if ri == 0:
        return 0.0
    return ci / ri
