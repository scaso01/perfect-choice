"""Tests for outcome tracking (model, DB persistence, round-trips)."""

from __future__ import annotations

import pytest

from perfect_choice.db import Database
from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    Outcome,
    Score,
    Tier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(
    *,
    id: str = "dec-001",
    title: str = "Pick a laptop",
    tier: Tier = Tier.STANDARD,
    status: DecisionStatus = DecisionStatus.COMPLETED,
    created_at: str = "2026-03-23T10:00:00",
    alternatives: tuple[Alternative, ...] | None = None,
    criteria: tuple[Criterion, ...] | None = None,
    scores: tuple[Score, ...] = (),
) -> Decision:
    """Build a minimal Decision for outcome testing."""
    if alternatives is None:
        alternatives = (
            Alternative(name="Option A", description="Budget pick"),
            Alternative(name="Option B", description="Premium pick"),
        )
    if criteria is None:
        criteria = (
            Criterion(name="Price", weight=0.5),
            Criterion(name="Quality", weight=0.5),
        )
    return Decision(
        id=id,
        title=title,
        description="",
        tier=tier,
        criteria=criteria,
        alternatives=alternatives,
        scores=scores,
        status=status,
        created_at=created_at,
    )


def _make_outcome(
    *,
    decision_id: str = "dec-001",
    rating: int = 7,
    actual_choice: str = "Option A",
    notes: str = "Solid pick",
    recorded_at: str = "2026-03-23T12:00:00Z",
) -> Outcome:
    """Build an Outcome with sensible defaults."""
    return Outcome(
        decision_id=decision_id,
        rating=rating,
        actual_choice=actual_choice,
        notes=notes,
        recorded_at=recorded_at,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestOutcomeModel:
    """Tests for the Outcome dataclass itself."""

    def test_create_outcome_with_all_fields(self) -> None:
        o = Outcome(
            decision_id="d1",
            rating=8,
            actual_choice="Option B",
            notes="Great result",
            recorded_at="2026-03-23T12:00:00Z",
        )
        assert o.decision_id == "d1"
        assert o.rating == 8
        assert o.actual_choice == "Option B"
        assert o.notes == "Great result"
        assert o.recorded_at == "2026-03-23T12:00:00Z"

    def test_outcome_defaults(self) -> None:
        o = Outcome(decision_id="d1", rating=5, actual_choice="X")
        assert o.notes == ""
        assert o.recorded_at == ""

    def test_outcome_is_frozen(self) -> None:
        o = _make_outcome()
        with pytest.raises(AttributeError):
            o.rating = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Save / Get round-trip
# ---------------------------------------------------------------------------

class TestSaveAndGetOutcome:
    """Tests for save_outcome and get_outcome."""

    def test_save_and_retrieve(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision())
            outcome = _make_outcome()
            db.save_outcome(outcome)
            loaded = db.get_outcome("dec-001")

        assert loaded is not None
        assert loaded.decision_id == "dec-001"
        assert loaded.rating == 7
        assert loaded.actual_choice == "Option A"
        assert loaded.notes == "Solid pick"
        assert loaded.recorded_at == "2026-03-23T12:00:00Z"

    def test_get_nonexistent_returns_none(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            result = db.get_outcome("no-such-decision")
        assert result is None

    def test_save_overwrites_existing(self, tmp_db: str) -> None:
        """UNIQUE(decision_id) means second save replaces first."""
        with Database(tmp_db) as db:
            db.save_decision(_make_decision())
            db.save_outcome(_make_outcome(rating=3, notes="meh"))
            db.save_outcome(_make_outcome(rating=9, notes="great"))
            loaded = db.get_outcome("dec-001")

        assert loaded is not None
        assert loaded.rating == 9
        assert loaded.notes == "great"

    def test_all_fields_round_trip(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision())
            original = Outcome(
                decision_id="dec-001",
                rating=10,
                actual_choice="Option B",
                notes="Couldn't be happier",
                recorded_at="2026-03-23T18:30:00+00:00",
            )
            db.save_outcome(original)
            loaded = db.get_outcome("dec-001")

        assert loaded is not None
        assert loaded.decision_id == original.decision_id
        assert loaded.rating == original.rating
        assert loaded.actual_choice == original.actual_choice
        assert loaded.notes == original.notes
        assert loaded.recorded_at == original.recorded_at

    def test_empty_notes_and_actual_choice(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision())
            outcome = Outcome(
                decision_id="dec-001",
                rating=5,
                actual_choice="",
                notes="",
                recorded_at="2026-03-23T12:00:00Z",
            )
            db.save_outcome(outcome)
            loaded = db.get_outcome("dec-001")

        assert loaded is not None
        assert loaded.actual_choice == ""
        assert loaded.notes == ""


# ---------------------------------------------------------------------------
# List outcomes
# ---------------------------------------------------------------------------

class TestListOutcomes:
    """Tests for list_outcomes."""

    def test_list_returns_newest_first(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="d1"))
            db.save_decision(_make_decision(id="d2"))
            db.save_decision(_make_decision(id="d3"))
            db.save_outcome(_make_outcome(decision_id="d1", recorded_at="2026-03-21T10:00:00Z"))
            db.save_outcome(_make_outcome(decision_id="d2", recorded_at="2026-03-23T10:00:00Z"))
            db.save_outcome(_make_outcome(decision_id="d3", recorded_at="2026-03-22T10:00:00Z"))
            results = db.list_outcomes()

        assert len(results) == 3
        assert results[0].decision_id == "d2"
        assert results[1].decision_id == "d3"
        assert results[2].decision_id == "d1"

    def test_list_respects_limit(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            for i in range(5):
                db.save_decision(_make_decision(id=f"d{i}"))
                db.save_outcome(
                    _make_outcome(
                        decision_id=f"d{i}",
                        recorded_at=f"2026-03-23T10:0{i}:00Z",
                    )
                )
            results = db.list_outcomes(limit=3)

        assert len(results) == 3

    def test_list_empty_when_no_outcomes(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            results = db.list_outcomes()
        assert results == []


# ---------------------------------------------------------------------------
# Multiple decisions with outcomes coexist
# ---------------------------------------------------------------------------

class TestMultipleOutcomes:
    """Outcomes for different decisions stored independently."""

    def test_multiple_decisions_have_separate_outcomes(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="aaa"))
            db.save_decision(_make_decision(id="bbb"))
            db.save_outcome(_make_outcome(decision_id="aaa", rating=3, actual_choice="Option A"))
            db.save_outcome(_make_outcome(decision_id="bbb", rating=9, actual_choice="Option B"))

            out_a = db.get_outcome("aaa")
            out_b = db.get_outcome("bbb")

        assert out_a is not None
        assert out_b is not None
        assert out_a.rating == 3
        assert out_a.actual_choice == "Option A"
        assert out_b.rating == 9
        assert out_b.actual_choice == "Option B"
