"""Domain models for Perfect Choice."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(Enum):
    """Decision complexity tier."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class ScoreMethod(Enum):
    """Scoring algorithm identifier."""

    AHP = "ahp"
    WSM = "wsm"
    TOPSIS = "topsis"


class DecisionStatus(Enum):
    """Decision lifecycle status."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Criterion:
    """A weighted evaluation criterion."""

    name: str
    weight: float = 0.0
    description: str = ""
    is_cost: bool = False  # True = lower is better


@dataclass(frozen=True, slots=True)
class Alternative:
    """A decision option."""

    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Score:
    """A single rating: one alternative on one criterion."""

    alternative_name: str
    criterion_name: str
    value: float  # 1-10 scale


@dataclass(frozen=True, slots=True)
class PairwiseComparison:
    """AHP pairwise comparison between two criteria."""

    criterion_a: str
    criterion_b: str
    value: float  # Saaty scale: 1/9 to 9


@dataclass(frozen=True, slots=True)
class RankingResult:
    """Ranked score for one alternative from one method."""

    alternative_name: str
    score: float
    rank: int
    method: ScoreMethod
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    """How sensitive the #1 rank is to a criterion's weight."""

    criterion_name: str
    original_weight: float
    threshold_pct: float | None  # None = fully stable within range
    flip_to: str = ""  # Which alternative would take #1


@dataclass(frozen=True, slots=True)
class Outcome:
    """Post-decision outcome rating."""

    decision_id: str
    rating: int  # 1-10 satisfaction
    actual_choice: str  # Which alternative was actually chosen
    notes: str = ""
    recorded_at: str = ""


@dataclass(frozen=True, slots=True)
class Decision:
    """Complete record of a decision session."""

    id: str
    title: str
    description: str
    tier: Tier
    criteria: tuple[Criterion, ...] = ()
    alternatives: tuple[Alternative, ...] = ()
    scores: tuple[Score, ...] = ()
    pairwise_comparisons: tuple[PairwiseComparison, ...] = ()
    rankings: dict[str, tuple[RankingResult, ...]] = field(default_factory=dict)
    sensitivity: tuple[SensitivityResult, ...] = ()
    consistency_ratio: float | None = None
    llm_summary: str = ""
    llm_devils_advocate: str = ""
    llm_bias_notes: str = ""
    created_at: str = ""
    completed_at: str | None = None
    status: DecisionStatus = DecisionStatus.IN_PROGRESS


def detect_tier(n_alternatives: int, n_criteria: int) -> Tier:
    """Auto-detect complexity tier from option/criteria counts."""
    if n_alternatives <= 3 and n_criteria <= 3:
        return Tier.QUICK
    if n_alternatives <= 8 and n_criteria <= 7:
        return Tier.STANDARD
    return Tier.DEEP
