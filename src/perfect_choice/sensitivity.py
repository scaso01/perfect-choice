"""Sensitivity analysis -- weight perturbation."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from perfect_choice.models import Criterion, RankingResult, Score, SensitivityResult


def analyze_sensitivity(
    alternatives: Sequence[str],
    criteria: Sequence[Criterion],
    scores: Sequence[Score],
    ranking_fn: Callable[
        [Sequence[str], Sequence[Criterion], Sequence[Score]],
        list[RankingResult],
    ],
    perturbation_range: float = 0.5,
    steps: int = 20,
) -> list[SensitivityResult]:
    """For each criterion, find smallest weight perturbation that flips #1.

    Perturb each weight from -range to +range, renormalize others
    proportionally.
    """
    # Get baseline #1
    baseline = ranking_fn(alternatives, criteria, scores)
    if len(baseline) < 2:
        return []
    winner = baseline[0].alternative_name

    results: list[SensitivityResult] = []
    for k, ck in enumerate(criteria):
        threshold: float | None = None
        flip_to = ""

        for step in range(1, steps + 1):
            for direction in (1.0, -1.0):
                pct = direction * step * perturbation_range / steps
                new_weight = ck.weight * (1.0 + pct)
                if new_weight < 0:
                    continue

                # Renormalize remaining weights
                remaining_original = sum(
                    c.weight for i, c in enumerate(criteria) if i != k
                )
                if remaining_original == 0:
                    continue
                scale = (1.0 - new_weight) / remaining_original
                if scale < 0:
                    continue

                new_criteria: list[Criterion] = []
                for i, c in enumerate(criteria):
                    if i == k:
                        new_criteria.append(
                            Criterion(c.name, new_weight, c.description, c.is_cost)
                        )
                    else:
                        new_criteria.append(
                            Criterion(
                                c.name, c.weight * scale, c.description, c.is_cost
                            )
                        )

                new_ranking = ranking_fn(alternatives, new_criteria, scores)
                if new_ranking[0].alternative_name != winner:
                    pct_abs = abs(pct) * 100
                    if threshold is None or pct_abs < threshold:
                        threshold = pct_abs
                        flip_to = new_ranking[0].alternative_name

        results.append(
            SensitivityResult(
                criterion_name=ck.name,
                original_weight=ck.weight,
                threshold_pct=threshold,
                flip_to=flip_to,
            )
        )

    # Sort: most sensitive first (lowest threshold), stable (None) last
    results.sort(
        key=lambda r: (
            r.threshold_pct if r.threshold_pct is not None else float("inf")
        )
    )
    return results
