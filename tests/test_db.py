"""Tests for the SQLite persistence layer."""

from __future__ import annotations

import pytest

from perfect_choice.db import Database
from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    PairwiseComparison,
    RankingResult,
    Score,
    ScoreMethod,
    SensitivityResult,
    Tier,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_decision(
    *,
    id: str = "dec-001",
    title: str = "Pick a laptop",
    description: str = "Choosing the best laptop for work",
    tier: Tier = Tier.STANDARD,
    criteria: tuple[Criterion, ...] | None = None,
    alternatives: tuple[Alternative, ...] | None = None,
    scores: tuple[Score, ...] | None = None,
    pairwise_comparisons: tuple[PairwiseComparison, ...] = (),
    rankings: dict[str, tuple[RankingResult, ...]] | None = None,
    sensitivity: tuple[SensitivityResult, ...] = (),
    consistency_ratio: float | None = 0.05,
    llm_summary: str = "Option A is best overall.",
    llm_devils_advocate: str = "But Option B has better longevity.",
    llm_bias_notes: str = "Anchoring on price.",
    created_at: str = "2026-03-23T10:00:00",
    completed_at: str | None = None,
    status: DecisionStatus = DecisionStatus.IN_PROGRESS,
) -> Decision:
    """Build a Decision with sensible defaults for testing."""
    if criteria is None:
        criteria = (
            Criterion(name="Price", weight=0.4, description="Total cost", is_cost=True),
            Criterion(name="Performance", weight=0.6, description="Speed"),
        )
    if alternatives is None:
        alternatives = (
            Alternative(name="Option A", description="Budget pick"),
            Alternative(name="Option B", description="Premium pick"),
        )
    if scores is None:
        scores = (
            Score(alternative_name="Option A", criterion_name="Price", value=8.0),
            Score(alternative_name="Option A", criterion_name="Performance", value=5.0),
            Score(alternative_name="Option B", criterion_name="Price", value=4.0),
            Score(alternative_name="Option B", criterion_name="Performance", value=9.0),
        )
    if rankings is None:
        rankings = {
            "wsm": (
                RankingResult(
                    alternative_name="Option A",
                    score=0.62,
                    rank=2,
                    method=ScoreMethod.WSM,
                    breakdown={"Price": 0.32, "Performance": 0.30},
                ),
                RankingResult(
                    alternative_name="Option B",
                    score=0.70,
                    rank=1,
                    method=ScoreMethod.WSM,
                    breakdown={"Price": 0.16, "Performance": 0.54},
                ),
            ),
        }
    return Decision(
        id=id,
        title=title,
        description=description,
        tier=tier,
        criteria=criteria,
        alternatives=alternatives,
        scores=scores,
        pairwise_comparisons=pairwise_comparisons,
        rankings=rankings,
        sensitivity=sensitivity,
        consistency_ratio=consistency_ratio,
        llm_summary=llm_summary,
        llm_devils_advocate=llm_devils_advocate,
        llm_bias_notes=llm_bias_notes,
        created_at=created_at,
        completed_at=completed_at,
        status=status,
    )


# ---------------------------------------------------------------------------
# Schema / Init
# ---------------------------------------------------------------------------

class TestDatabaseCreation:
    """Tests for schema initialization."""

    def test_creates_all_tables(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            conn = db._conn
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        expected = {
            "decisions",
            "criteria",
            "alternatives",
            "scores",
            "pairwise_comparisons",
            "rankings",
            "sensitivity_results",
        }
        assert expected.issubset(tables)

    def test_wal_mode_active(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            fk = db._conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_creates_parent_directory(self, tmp_path) -> None:
        nested = str(tmp_path / "sub" / "dir" / "test.db")
        with Database(nested):
            pass
        assert (tmp_path / "sub" / "dir" / "test.db").exists()


# ---------------------------------------------------------------------------
# Save / Get round-trip
# ---------------------------------------------------------------------------

class TestSaveAndGet:
    """Tests for save_decision and get_decision."""

    def test_save_and_retrieve_full_decision(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.id == dec.id
        assert loaded.title == dec.title
        assert loaded.description == dec.description
        assert loaded.tier == dec.tier
        assert loaded.status == dec.status
        assert loaded.created_at == dec.created_at
        assert loaded.completed_at == dec.completed_at

    def test_round_trip_criteria(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert len(loaded.criteria) == 2
        names = {c.name for c in loaded.criteria}
        assert names == {"Price", "Performance"}
        cost_crit = next(c for c in loaded.criteria if c.name == "Price")
        assert cost_crit.is_cost is True
        assert cost_crit.weight == pytest.approx(0.4)

    def test_round_trip_alternatives(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert len(loaded.alternatives) == 2
        descs = {a.description for a in loaded.alternatives}
        assert "Budget pick" in descs

    def test_round_trip_scores(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert len(loaded.scores) == 4
        perf_b = next(
            s
            for s in loaded.scores
            if s.alternative_name == "Option B" and s.criterion_name == "Performance"
        )
        assert perf_b.value == pytest.approx(9.0)

    def test_round_trip_rankings_and_breakdown_json(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert "wsm" in loaded.rankings
        wsm_results = loaded.rankings["wsm"]
        assert len(wsm_results) == 2
        rank1 = next(r for r in wsm_results if r.rank == 1)
        assert rank1.alternative_name == "Option B"
        assert rank1.score == pytest.approx(0.70)
        # breakdown JSON round-tripped correctly
        assert rank1.breakdown == {"Price": 0.16, "Performance": 0.54}

    def test_consistency_ratio_stored(self, tmp_db: str) -> None:
        dec = _make_decision(consistency_ratio=0.08)
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.consistency_ratio == pytest.approx(0.08)

    def test_consistency_ratio_none(self, tmp_db: str) -> None:
        dec = _make_decision(consistency_ratio=None)
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.consistency_ratio is None

    def test_llm_fields_round_trip(self, tmp_db: str) -> None:
        dec = _make_decision()
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.llm_summary == "Option A is best overall."
        assert loaded.llm_devils_advocate == "But Option B has better longevity."
        assert loaded.llm_bias_notes == "Anchoring on price."

    def test_save_with_empty_optional_fields(self, tmp_db: str) -> None:
        dec = _make_decision(
            criteria=(),
            alternatives=(),
            scores=(),
            rankings={},
            sensitivity=(),
            llm_summary="",
            llm_devils_advocate="",
            llm_bias_notes="",
            consistency_ratio=None,
            completed_at=None,
        )
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.criteria == ()
        assert loaded.alternatives == ()
        assert loaded.scores == ()
        assert loaded.rankings == {}
        assert loaded.sensitivity == ()
        assert loaded.llm_summary == ""
        assert loaded.consistency_ratio is None

    def test_get_nonexistent_returns_none(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            assert db.get_decision("does-not-exist") is None

    def test_save_overwrites_existing(self, tmp_db: str) -> None:
        dec1 = _make_decision(title="Version 1")
        dec2 = _make_decision(title="Version 2")
        with Database(tmp_db) as db:
            db.save_decision(dec1)
            db.save_decision(dec2)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert loaded.title == "Version 2"


# ---------------------------------------------------------------------------
# Prefix matching
# ---------------------------------------------------------------------------

class TestPrefixLookup:
    """Tests for get_decision_by_prefix."""

    def test_full_id_works(self, tmp_db: str) -> None:
        dec = _make_decision(id="abc-123-def")
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision_by_prefix("abc-123-def")
        assert loaded is not None
        assert loaded.id == "abc-123-def"

    def test_partial_prefix_works(self, tmp_db: str) -> None:
        dec = _make_decision(id="abc-123-def")
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision_by_prefix("abc")
        assert loaded is not None
        assert loaded.id == "abc-123-def"

    def test_ambiguous_prefix_raises(self, tmp_db: str) -> None:
        dec1 = _make_decision(id="abc-111")
        dec2 = _make_decision(id="abc-222")
        with Database(tmp_db) as db:
            db.save_decision(dec1)
            db.save_decision(dec2)
            with pytest.raises(ValueError, match="Ambiguous"):
                db.get_decision_by_prefix("abc")

    def test_no_match_returns_none(self, tmp_db: str) -> None:
        dec = _make_decision(id="abc-123")
        with Database(tmp_db) as db:
            db.save_decision(dec)
            assert db.get_decision_by_prefix("xyz") is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListDecisions:
    """Tests for list_decisions."""

    def test_list_returns_saved_decisions(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="d1", title="First"))
            db.save_decision(_make_decision(id="d2", title="Second"))
            results = db.list_decisions()
        assert len(results) == 2
        titles = {d.title for d in results}
        assert titles == {"First", "Second"}

    def test_list_respects_limit(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            for i in range(5):
                db.save_decision(
                    _make_decision(id=f"d{i}", created_at=f"2026-03-23T10:0{i}:00")
                )
            results = db.list_decisions(limit=3)
        assert len(results) == 3

    def test_list_status_filter(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(
                _make_decision(id="d1", status=DecisionStatus.IN_PROGRESS)
            )
            db.save_decision(
                _make_decision(id="d2", status=DecisionStatus.COMPLETED)
            )
            db.save_decision(
                _make_decision(id="d3", status=DecisionStatus.COMPLETED)
            )
            results = db.list_decisions(status_filter="completed")
        assert len(results) == 2
        assert all(d.status == DecisionStatus.COMPLETED for d in results)

    def test_list_summary_only_no_scores(self, tmp_db: str) -> None:
        """Listed decisions have empty collection fields (summary only)."""
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="d1"))
            results = db.list_decisions()
        assert len(results) == 1
        d = results[0]
        assert d.scores == ()
        assert d.rankings == {}
        assert d.criteria == ()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteDecision:
    """Tests for delete_decision."""

    def test_delete_existing(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="d1"))
            assert db.delete_decision("d1") is True
            assert db.get_decision("d1") is None

    def test_delete_nonexistent_returns_false(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            assert db.delete_decision("nope") is False

    def test_delete_removes_child_rows(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(_make_decision(id="d1"))
            db.delete_decision("d1")

            for table in (
                "criteria",
                "alternatives",
                "scores",
                "pairwise_comparisons",
                "rankings",
                "sensitivity_results",
            ):
                count = db._conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE decision_id = ?",
                    ("d1",),
                ).fetchone()[0]
                assert count == 0, f"Orphan rows remain in {table}"


# ---------------------------------------------------------------------------
# Update status
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    """Tests for update_status."""

    def test_update_status(self, tmp_db: str) -> None:
        with Database(tmp_db) as db:
            db.save_decision(
                _make_decision(id="d1", status=DecisionStatus.IN_PROGRESS)
            )
            db.update_status("d1", "completed")
            loaded = db.get_decision("d1")
        assert loaded is not None
        assert loaded.status == DecisionStatus.COMPLETED


# ---------------------------------------------------------------------------
# Multiple decisions coexist
# ---------------------------------------------------------------------------

class TestMultipleDecisions:
    """Multiple decisions stored independently."""

    def test_multiple_decisions_coexist(self, tmp_db: str) -> None:
        dec_a = _make_decision(id="aaa", title="Decision A")
        dec_b = _make_decision(id="bbb", title="Decision B")
        with Database(tmp_db) as db:
            db.save_decision(dec_a)
            db.save_decision(dec_b)
            loaded_a = db.get_decision("aaa")
            loaded_b = db.get_decision("bbb")

        assert loaded_a is not None
        assert loaded_b is not None
        assert loaded_a.title == "Decision A"
        assert loaded_b.title == "Decision B"
        # Each has its own child rows
        assert len(loaded_a.scores) == 4
        assert len(loaded_b.scores) == 4


# ---------------------------------------------------------------------------
# Sensitivity round-trip
# ---------------------------------------------------------------------------

class TestSensitivityRoundTrip:
    """Sensitivity results persist correctly."""

    def test_sensitivity_with_threshold(self, tmp_db: str) -> None:
        dec = _make_decision(
            sensitivity=(
                SensitivityResult(
                    criterion_name="Price",
                    original_weight=0.4,
                    threshold_pct=15.0,
                    flip_to="Option A",
                ),
                SensitivityResult(
                    criterion_name="Performance",
                    original_weight=0.6,
                    threshold_pct=None,
                    flip_to="",
                ),
            ),
        )
        with Database(tmp_db) as db:
            db.save_decision(dec)
            loaded = db.get_decision("dec-001")

        assert loaded is not None
        assert len(loaded.sensitivity) == 2
        price_sr = next(s for s in loaded.sensitivity if s.criterion_name == "Price")
        assert price_sr.threshold_pct == pytest.approx(15.0)
        assert price_sr.flip_to == "Option A"
        perf_sr = next(
            s for s in loaded.sensitivity if s.criterion_name == "Performance"
        )
        assert perf_sr.threshold_pct is None
        assert perf_sr.flip_to == ""
