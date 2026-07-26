"""Import decisions from CSV or JSON files."""
from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    Score,
    Tier,
    detect_tier,
)
from perfect_choice.scoring import topsis_rank, wsm_rank


def import_json(file_path: str) -> Decision:
    """Import a decision from a JSON file.

    Expected format:
    {
        "title": "...",
        "description": "...",
        "alternatives": ["A", "B", "C"],
        "criteria": [
            {"name": "Price", "is_cost": true, "weight": 0.3},
            ...
        ],
        "scores": {
            "A": {"Price": 8, "Performance": 9},
            ...
        }
    }
    """
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)
    return _build_decision(data)


def import_csv(file_path: str) -> Decision:
    """Import a decision from a CSV file.

    Expected format:
    ,Price (cost),Performance,Battery
    weight,0.3,0.4,0.3
    MacBook,8,9,7
    ThinkPad,6,7,8
    """
    with open(file_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 3:
        raise ValueError("CSV must have at least header, weight, and one alternative row")

    # Parse header: criterion names, "(cost)" suffix marks cost criteria
    header = rows[0][1:]  # Skip first empty column
    criteria_defs = []
    for h in header:
        h = h.strip()
        is_cost = "(cost)" in h.lower()
        name = h.replace("(cost)", "").replace("(Cost)", "").strip()
        criteria_defs.append({"name": name, "is_cost": is_cost})

    # Parse weights row
    weight_row = rows[1]
    if weight_row[0].strip().lower() != "weight":
        raise ValueError("Second row must start with 'weight'")
    weights = [float(w.strip()) for w in weight_row[1:]]

    for i, w in enumerate(weights):
        criteria_defs[i]["weight"] = w

    # Parse alternative rows
    alternatives = []
    scores_data: dict[str, dict[str, float]] = {}
    for row in rows[2:]:
        if not row or not row[0].strip():
            continue
        alt_name = row[0].strip()
        alternatives.append(alt_name)
        scores_data[alt_name] = {}
        for j, val in enumerate(row[1:]):
            if j < len(criteria_defs):
                scores_data[alt_name][criteria_defs[j]["name"]] = float(val.strip())

    # Build the data dict and delegate
    data = {
        "title": Path(file_path).stem.replace("_", " ").replace("-", " ").title(),
        "description": f"Imported from {Path(file_path).name}",
        "alternatives": alternatives,
        "criteria": criteria_defs,
        "scores": scores_data,
    }
    return _build_decision(data)


def import_file(file_path: str, fmt: str | None = None) -> Decision:
    """Auto-detect format and import."""
    if fmt is None:
        ext = Path(file_path).suffix.lower()
        if ext == ".json":
            fmt = "json"
        elif ext in (".csv", ".tsv"):
            fmt = "csv"
        else:
            raise ValueError(f"Cannot detect format from extension: {ext}")
    if fmt == "json":
        return import_json(file_path)
    if fmt == "csv":
        return import_csv(file_path)
    raise ValueError(f"Unknown format: {fmt}")


def _build_decision(data: dict) -> Decision:
    """Build a scored Decision from parsed data."""
    title = data.get("title", "Imported Decision")
    description = data.get("description", "")

    alt_names = data["alternatives"]
    criteria_defs = data["criteria"]
    scores_data = data["scores"]

    # Build model objects
    alternatives = tuple(Alternative(name=a) for a in alt_names)

    # Normalize weights if they don't sum to 1
    raw_weights = [c.get("weight", 1.0 / len(criteria_defs)) for c in criteria_defs]
    total_w = sum(raw_weights)
    norm_weights = [w / total_w for w in raw_weights] if total_w > 0 else raw_weights

    criteria = tuple(
        Criterion(
            name=cd["name"],
            weight=nw,
            description=cd.get("description", ""),
            is_cost=cd.get("is_cost", False),
        )
        for cd, nw in zip(criteria_defs, norm_weights)
    )

    scores = []
    for alt_name in alt_names:
        alt_scores = scores_data.get(alt_name, {})
        for crit in criteria:
            val = alt_scores.get(crit.name, 5.0)
            scores.append(Score(alt_name, crit.name, float(val)))
    scores_tuple = tuple(scores)

    # Detect tier and run scoring
    tier = detect_tier(len(alt_names), len(criteria))
    rankings: dict[str, tuple] = {}
    rankings["wsm"] = tuple(wsm_rank(alt_names, criteria, scores))
    if tier in (Tier.STANDARD, Tier.DEEP):
        rankings["topsis"] = tuple(topsis_rank(alt_names, criteria, scores))

    now = datetime.now(timezone.utc).isoformat()
    return Decision(
        id=uuid.uuid4().hex,
        title=title,
        description=description,
        tier=tier,
        criteria=criteria,
        alternatives=alternatives,
        scores=scores_tuple,
        rankings=rankings,
        created_at=now,
        completed_at=now,
        status=DecisionStatus.COMPLETED,
    )
