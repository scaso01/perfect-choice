"""WSM and TOPSIS scoring algorithms."""

from __future__ import annotations

import math
from collections.abc import Sequence

from perfect_choice.models import Criterion, RankingResult, Score, ScoreMethod


def _build_matrix(
    alternatives: Sequence[str],
    criteria: Sequence[Criterion],
    scores: Sequence[Score],
) -> list[list[float]]:
    """Build alternatives x criteria matrix from flat score list."""
    alt_idx = {a: i for i, a in enumerate(alternatives)}
    crit_idx = {c.name: i for i, c in enumerate(criteria)}
    n_alt, n_crit = len(alternatives), len(criteria)
    matrix = [[0.0] * n_crit for _ in range(n_alt)]
    for s in scores:
        matrix[alt_idx[s.alternative_name]][crit_idx[s.criterion_name]] = s.value
    return matrix


def wsm_rank(
    alternatives: Sequence[str],
    criteria: Sequence[Criterion],
    scores: Sequence[Score],
) -> list[RankingResult]:
    """Weighted Sum Model ranking.

    Normalization: benefit = value/max, cost = min/value.
    Score = sum(weight * normalized).
    """
    matrix = _build_matrix(alternatives, criteria, scores)
    n_alt, n_crit = len(alternatives), len(criteria)

    # Normalize per column
    norm = [[0.0] * n_crit for _ in range(n_alt)]
    for j in range(n_crit):
        col = [matrix[i][j] for i in range(n_alt)]
        col_max = max(col) if col else 1.0
        col_min = min(col) if col else 1.0
        for i in range(n_alt):
            val = matrix[i][j]
            if criteria[j].is_cost:
                norm[i][j] = col_min / val if val != 0 else 0.0
            else:
                norm[i][j] = val / col_max if col_max != 0 else 0.0

    # Weighted sum
    raw_scores: list[tuple[str, float, dict[str, float]]] = []
    for i in range(n_alt):
        total = sum(
            criteria[j].weight * norm[i][j] for j in range(n_crit)
        )
        breakdown = {
            criteria[j].name: criteria[j].weight * norm[i][j]
            for j in range(n_crit)
        }
        raw_scores.append((alternatives[i], total, breakdown))

    raw_scores.sort(key=lambda x: x[1], reverse=True)
    return [
        RankingResult(
            alternative_name=name,
            score=score,
            rank=rank + 1,
            method=ScoreMethod.WSM,
            breakdown=bd,
        )
        for rank, (name, score, bd) in enumerate(raw_scores)
    ]


def topsis_rank(
    alternatives: Sequence[str],
    criteria: Sequence[Criterion],
    scores: Sequence[Score],
) -> list[RankingResult]:
    """TOPSIS ranking.

    1. Vector normalization: r_ij = x_ij / sqrt(sum(x_ij^2))
    2. Weighted: v_ij = w_j * r_ij
    3. Ideal A+ and anti-ideal A-
    4. Distance to each
    5. Relative closeness C = D- / (D+ + D-)
    """
    matrix = _build_matrix(alternatives, criteria, scores)
    n_alt, n_crit = len(alternatives), len(criteria)

    # Step 1: Vector normalization
    norm = [[0.0] * n_crit for _ in range(n_alt)]
    for j in range(n_crit):
        col_norm = math.sqrt(sum(matrix[i][j] ** 2 for i in range(n_alt)))
        if col_norm == 0:
            col_norm = 1.0
        for i in range(n_alt):
            norm[i][j] = matrix[i][j] / col_norm

    # Step 2: Weighted normalization
    weighted = [[0.0] * n_crit for _ in range(n_alt)]
    for i in range(n_alt):
        for j in range(n_crit):
            weighted[i][j] = criteria[j].weight * norm[i][j]

    # Step 3: Ideal and anti-ideal
    ideal = [0.0] * n_crit
    anti_ideal = [0.0] * n_crit
    for j in range(n_crit):
        col = [weighted[i][j] for i in range(n_alt)]
        if criteria[j].is_cost:
            ideal[j] = min(col)
            anti_ideal[j] = max(col)
        else:
            ideal[j] = max(col)
            anti_ideal[j] = min(col)

    # Steps 4-5: Distances and closeness
    raw_scores: list[tuple[str, float, dict[str, float]]] = []
    for i in range(n_alt):
        d_plus = math.sqrt(
            sum((weighted[i][j] - ideal[j]) ** 2 for j in range(n_crit))
        )
        d_minus = math.sqrt(
            sum(
                (weighted[i][j] - anti_ideal[j]) ** 2 for j in range(n_crit)
            )
        )
        denom = d_plus + d_minus
        closeness = d_minus / denom if denom != 0 else 0.0
        breakdown = {
            criteria[j].name: weighted[i][j] for j in range(n_crit)
        }
        raw_scores.append((alternatives[i], closeness, breakdown))

    raw_scores.sort(key=lambda x: x[1], reverse=True)
    return [
        RankingResult(
            alternative_name=name,
            score=score,
            rank=rank + 1,
            method=ScoreMethod.TOPSIS,
            breakdown=bd,
        )
        for rank, (name, score, bd) in enumerate(raw_scores)
    ]
