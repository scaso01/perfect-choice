"""SQLite persistence layer for Perfect Choice decisions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    Outcome,
    PairwiseComparison,
    RankingResult,
    Score,
    ScoreMethod,
    SensitivityResult,
    Tier,
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    tier            TEXT NOT NULL,
    consistency_ratio REAL,
    llm_summary     TEXT NOT NULL DEFAULT '',
    llm_devils_advocate TEXT NOT NULL DEFAULT '',
    llm_bias_notes  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT '',
    completed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'in_progress'
);

CREATE TABLE IF NOT EXISTS criteria (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id  TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 0.0,
    description  TEXT NOT NULL DEFAULT '',
    is_cost      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(decision_id, name)
);

CREATE TABLE IF NOT EXISTS alternatives (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id  TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    UNIQUE(decision_id, name)
);

CREATE TABLE IF NOT EXISTS scores (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id      TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    alternative_name TEXT NOT NULL,
    criterion_name   TEXT NOT NULL,
    value            REAL NOT NULL,
    UNIQUE(decision_id, alternative_name, criterion_name)
);

CREATE TABLE IF NOT EXISTS pairwise_comparisons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id  TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    criterion_a  TEXT NOT NULL,
    criterion_b  TEXT NOT NULL,
    value        REAL NOT NULL,
    UNIQUE(decision_id, criterion_a, criterion_b)
);

CREATE TABLE IF NOT EXISTS rankings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id      TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    method           TEXT NOT NULL,
    alternative_name TEXT NOT NULL,
    score            REAL NOT NULL,
    rank             INTEGER NOT NULL,
    breakdown        TEXT NOT NULL DEFAULT '{}',
    UNIQUE(decision_id, method, alternative_name)
);

CREATE TABLE IF NOT EXISTS sensitivity_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    criterion_name  TEXT NOT NULL,
    original_weight REAL NOT NULL,
    threshold_pct   REAL,
    flip_to         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    rating INTEGER NOT NULL,
    actual_choice TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    recorded_at TEXT NOT NULL,
    UNIQUE(decision_id)
);

CREATE INDEX IF NOT EXISTS idx_criteria_decision ON criteria(decision_id);
CREATE INDEX IF NOT EXISTS idx_alternatives_decision ON alternatives(decision_id);
CREATE INDEX IF NOT EXISTS idx_scores_decision ON scores(decision_id);
CREATE INDEX IF NOT EXISTS idx_pairwise_decision ON pairwise_comparisons(decision_id);
CREATE INDEX IF NOT EXISTS idx_rankings_decision ON rankings(decision_id);
CREATE INDEX IF NOT EXISTS idx_sensitivity_decision ON sensitivity_results(decision_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON outcomes(decision_id);
"""


class Database:
    """SQLite database for decision persistence.

    Uses WAL mode for concurrent read access and foreign keys for
    referential integrity.  Intended to be used as a context manager.
    """

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        self.close()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    # -- public API (placeholders) -----------------------------------------

    def save_decision(self, decision: Decision) -> None:
        """Persist a complete Decision (insert or replace).

        Uses a single transaction to write the decision row and all
        related child rows.  Existing rows for the same decision ID
        are replaced via INSERT OR REPLACE (UNIQUE constraints).
        """
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")

            # -- decision row ----------------------------------------------
            cur.execute(
                """INSERT OR REPLACE INTO decisions
                   (id, title, description, tier, consistency_ratio,
                    llm_summary, llm_devils_advocate, llm_bias_notes,
                    created_at, completed_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision.id,
                    decision.title,
                    decision.description,
                    decision.tier.value,
                    decision.consistency_ratio,
                    decision.llm_summary,
                    decision.llm_devils_advocate,
                    decision.llm_bias_notes,
                    decision.created_at,
                    decision.completed_at,
                    decision.status.value,
                ),
            )

            # -- wipe child rows before re-inserting -----------------------
            for table in (
                "criteria",
                "alternatives",
                "scores",
                "pairwise_comparisons",
                "rankings",
                "sensitivity_results",
            ):
                cur.execute(
                    f"DELETE FROM {table} WHERE decision_id = ?",  # noqa: S608
                    (decision.id,),
                )

            # -- criteria --------------------------------------------------
            for c in decision.criteria:
                cur.execute(
                    """INSERT INTO criteria
                       (decision_id, name, weight, description, is_cost)
                       VALUES (?,?,?,?,?)""",
                    (decision.id, c.name, c.weight, c.description, int(c.is_cost)),
                )

            # -- alternatives ----------------------------------------------
            for a in decision.alternatives:
                cur.execute(
                    """INSERT INTO alternatives
                       (decision_id, name, description)
                       VALUES (?,?,?)""",
                    (decision.id, a.name, a.description),
                )

            # -- scores ----------------------------------------------------
            for s in decision.scores:
                cur.execute(
                    """INSERT INTO scores
                       (decision_id, alternative_name, criterion_name, value)
                       VALUES (?,?,?,?)""",
                    (decision.id, s.alternative_name, s.criterion_name, s.value),
                )

            # -- pairwise comparisons --------------------------------------
            for pc in decision.pairwise_comparisons:
                cur.execute(
                    """INSERT INTO pairwise_comparisons
                       (decision_id, criterion_a, criterion_b, value)
                       VALUES (?,?,?,?)""",
                    (decision.id, pc.criterion_a, pc.criterion_b, pc.value),
                )

            # -- rankings --------------------------------------------------
            for method_key, results in decision.rankings.items():
                for r in results:
                    cur.execute(
                        """INSERT INTO rankings
                           (decision_id, method, alternative_name,
                            score, rank, breakdown)
                           VALUES (?,?,?,?,?,?)""",
                        (
                            decision.id,
                            method_key,
                            r.alternative_name,
                            r.score,
                            r.rank,
                            json.dumps(r.breakdown),
                        ),
                    )

            # -- sensitivity results ---------------------------------------
            for sr in decision.sensitivity:
                cur.execute(
                    """INSERT INTO sensitivity_results
                       (decision_id, criterion_name, original_weight,
                        threshold_pct, flip_to)
                       VALUES (?,?,?,?,?)""",
                    (
                        decision.id,
                        sr.criterion_name,
                        sr.original_weight,
                        sr.threshold_pct,
                        sr.flip_to,
                    ),
                )

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_decision(self, decision_id: str) -> Decision | None:
        """Load a full Decision by exact ID, hydrating all child tables."""
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def get_decision_by_prefix(self, prefix: str) -> Decision | None:
        """Load a Decision by ID prefix. Raises ValueError if ambiguous."""
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE id LIKE ?", (prefix + "%",)
        ).fetchall()
        if len(rows) == 0:
            return None
        if len(rows) > 1:
            ids = [r["id"] for r in rows]
            raise ValueError(
                f"Ambiguous prefix '{prefix}' matches {len(rows)} decisions: "
                + ", ".join(ids)
            )
        return self._hydrate(rows[0])

    # -- internal hydration ------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> Decision:
        """Reconstruct a full Decision from a decisions row + child tables."""
        did = row["id"]

        criteria = tuple(
            Criterion(
                name=r["name"],
                weight=r["weight"],
                description=r["description"],
                is_cost=bool(r["is_cost"]),
            )
            for r in self._conn.execute(
                "SELECT * FROM criteria WHERE decision_id = ?", (did,)
            )
        )

        alternatives = tuple(
            Alternative(name=r["name"], description=r["description"])
            for r in self._conn.execute(
                "SELECT * FROM alternatives WHERE decision_id = ?", (did,)
            )
        )

        scores = tuple(
            Score(
                alternative_name=r["alternative_name"],
                criterion_name=r["criterion_name"],
                value=r["value"],
            )
            for r in self._conn.execute(
                "SELECT * FROM scores WHERE decision_id = ?", (did,)
            )
        )

        pairwise_comparisons = tuple(
            PairwiseComparison(
                criterion_a=r["criterion_a"],
                criterion_b=r["criterion_b"],
                value=r["value"],
            )
            for r in self._conn.execute(
                "SELECT * FROM pairwise_comparisons WHERE decision_id = ?", (did,)
            )
        )

        # -- rankings grouped by method ------------------------------------
        rankings: dict[str, tuple[RankingResult, ...]] = {}
        ranking_rows = self._conn.execute(
            "SELECT * FROM rankings WHERE decision_id = ? ORDER BY method, rank",
            (did,),
        ).fetchall()
        for r in ranking_rows:
            method_key = r["method"]
            result = RankingResult(
                alternative_name=r["alternative_name"],
                score=r["score"],
                rank=r["rank"],
                method=ScoreMethod(method_key),
                breakdown=json.loads(r["breakdown"]),
            )
            if method_key not in rankings:
                rankings[method_key] = ()
            rankings[method_key] = rankings[method_key] + (result,)

        sensitivity = tuple(
            SensitivityResult(
                criterion_name=r["criterion_name"],
                original_weight=r["original_weight"],
                threshold_pct=r["threshold_pct"],
                flip_to=r["flip_to"],
            )
            for r in self._conn.execute(
                "SELECT * FROM sensitivity_results WHERE decision_id = ?", (did,)
            )
        )

        return Decision(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            tier=Tier(row["tier"]),
            criteria=criteria,
            alternatives=alternatives,
            scores=scores,
            pairwise_comparisons=pairwise_comparisons,
            rankings=rankings,
            sensitivity=sensitivity,
            consistency_ratio=row["consistency_ratio"],
            llm_summary=row["llm_summary"],
            llm_devils_advocate=row["llm_devils_advocate"],
            llm_bias_notes=row["llm_bias_notes"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            status=DecisionStatus(row["status"]),
        )

    def list_decisions(
        self,
        limit: int = 20,
        status_filter: str | None = None,
    ) -> list[Decision]:
        """Return summary-only Decision objects (no scores/rankings).

        Only the core fields (id, title, tier, status, created_at,
        description) are populated; collection fields are left empty.
        """
        if status_filter is not None:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status_filter, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        results: list[Decision] = []
        for row in rows:
            results.append(
                Decision(
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    tier=Tier(row["tier"]),
                    status=DecisionStatus(row["status"]),
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    consistency_ratio=row["consistency_ratio"],
                    llm_summary=row["llm_summary"],
                    llm_devils_advocate=row["llm_devils_advocate"],
                    llm_bias_notes=row["llm_bias_notes"],
                )
            )
        return results

    def delete_decision(self, decision_id: str) -> bool:
        """Delete a decision and all related rows. Returns True if found.

        Child rows are removed automatically by ON DELETE CASCADE.
        """
        cur = self._conn.execute(
            "DELETE FROM decisions WHERE id = ?", (decision_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_status(self, decision_id: str, status: str) -> None:
        """Update the status field of a decision."""
        self._conn.execute(
            "UPDATE decisions SET status = ? WHERE id = ?",
            (status, decision_id),
        )
        self._conn.commit()

    # -- outcome tracking --------------------------------------------------

    def save_outcome(self, outcome: Outcome) -> None:
        """Save or update an outcome for a decision."""
        self._conn.execute(
            "INSERT OR REPLACE INTO outcomes "
            "(decision_id, rating, actual_choice, notes, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                outcome.decision_id,
                outcome.rating,
                outcome.actual_choice,
                outcome.notes,
                outcome.recorded_at,
            ),
        )
        self._conn.commit()

    def get_outcome(self, decision_id: str) -> Outcome | None:
        """Get the outcome for a decision, if recorded."""
        row = self._conn.execute(
            "SELECT decision_id, rating, actual_choice, notes, recorded_at "
            "FROM outcomes WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        return Outcome(
            decision_id=row["decision_id"],
            rating=row["rating"],
            actual_choice=row["actual_choice"],
            notes=row["notes"],
            recorded_at=row["recorded_at"],
        )

    def list_outcomes(self, limit: int = 20) -> list[Outcome]:
        """List all recorded outcomes, newest first."""
        rows = self._conn.execute(
            "SELECT decision_id, rating, actual_choice, notes, recorded_at "
            "FROM outcomes ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Outcome(
                decision_id=r["decision_id"],
                rating=r["rating"],
                actual_choice=r["actual_choice"],
                notes=r["notes"],
                recorded_at=r["recorded_at"],
            )
            for r in rows
        ]
