"""Tests for CSV/JSON import functionality."""
from __future__ import annotations

import json

import pytest

from perfect_choice.importer import _build_decision, import_csv, import_file, import_json
from perfect_choice.models import DecisionStatus, Tier


def _make_json_file(tmp_path, data: dict) -> str:
    """Write a JSON file and return its path."""
    p = tmp_path / "test_decision.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _make_csv_file(tmp_path, content: str, name: str = "test_decision.csv") -> str:
    """Write a CSV file and return its path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


VALID_JSON_DATA = {
    "title": "Laptop Comparison",
    "description": "Choosing a work laptop",
    "alternatives": ["MacBook", "ThinkPad", "XPS"],
    "criteria": [
        {"name": "Price", "is_cost": True, "weight": 0.3},
        {"name": "Performance", "is_cost": False, "weight": 0.4},
        {"name": "Battery", "is_cost": False, "weight": 0.3},
    ],
    "scores": {
        "MacBook": {"Price": 6, "Performance": 9, "Battery": 8},
        "ThinkPad": {"Price": 8, "Performance": 7, "Battery": 9},
        "XPS": {"Price": 7, "Performance": 8, "Battery": 7},
    },
}

VALID_CSV = """,Price (cost),Performance,Battery
weight,0.3,0.4,0.3
MacBook,6,9,8
ThinkPad,8,7,9
XPS,7,8,7
"""


class TestImportJson:
    """Tests for import_json()."""

    def test_valid_json(self, tmp_path):
        path = _make_json_file(tmp_path, VALID_JSON_DATA)
        decision = import_json(path)
        assert decision.title == "Laptop Comparison"
        assert decision.description == "Choosing a work laptop"
        assert len(decision.alternatives) == 3
        assert len(decision.criteria) == 3
        assert decision.status == DecisionStatus.COMPLETED

    def test_alternatives_names(self, tmp_path):
        path = _make_json_file(tmp_path, VALID_JSON_DATA)
        decision = import_json(path)
        names = [a.name for a in decision.alternatives]
        assert names == ["MacBook", "ThinkPad", "XPS"]

    def test_missing_alternatives_raises(self, tmp_path):
        data = {"title": "Bad", "criteria": [], "scores": {}}
        path = _make_json_file(tmp_path, data)
        with pytest.raises(KeyError):
            import_json(path)

    def test_rankings_computed(self, tmp_path):
        path = _make_json_file(tmp_path, VALID_JSON_DATA)
        decision = import_json(path)
        assert "wsm" in decision.rankings
        assert len(decision.rankings["wsm"]) == 3


class TestImportCsv:
    """Tests for import_csv()."""

    def test_valid_csv(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV)
        decision = import_csv(path)
        assert len(decision.alternatives) == 3
        assert len(decision.criteria) == 3

    def test_cost_flag_from_header(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV)
        decision = import_csv(path)
        price_crit = [c for c in decision.criteria if c.name == "Price"][0]
        assert price_crit.is_cost is True

    def test_non_cost_criteria(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV)
        decision = import_csv(path)
        perf_crit = [c for c in decision.criteria if c.name == "Performance"][0]
        assert perf_crit.is_cost is False

    def test_too_few_rows_raises(self, tmp_path):
        content = ",Price\nweight,0.5\n"
        path = _make_csv_file(tmp_path, content)
        with pytest.raises(ValueError, match="at least header"):
            import_csv(path)

    def test_missing_weight_label_raises(self, tmp_path):
        content = ",Price,Performance\nnotweight,0.5,0.5\nA,8,7\n"
        path = _make_csv_file(tmp_path, content)
        with pytest.raises(ValueError, match="weight"):

            import_csv(path)

    def test_title_derived_from_filename(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV, name="my_laptop_choice.csv")
        decision = import_csv(path)
        assert "Laptop" in decision.title

    def test_scores_parsed_correctly(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV)
        decision = import_csv(path)
        macbook_price = [
            s for s in decision.scores
            if s.alternative_name == "MacBook" and s.criterion_name == "Price"
        ]
        assert len(macbook_price) == 1
        assert macbook_price[0].value == 6.0


class TestImportFile:
    """Tests for import_file() auto-detection."""

    def test_autodetect_json(self, tmp_path):
        path = _make_json_file(tmp_path, VALID_JSON_DATA)
        decision = import_file(path)
        assert decision.title == "Laptop Comparison"

    def test_autodetect_csv(self, tmp_path):
        path = _make_csv_file(tmp_path, VALID_CSV)
        decision = import_file(path)
        assert len(decision.alternatives) == 3

    def test_unknown_extension_raises(self, tmp_path):
        p = tmp_path / "data.xlsx"
        p.write_text("stuff")
        with pytest.raises(ValueError, match="Cannot detect format"):
            import_file(str(p))

    def test_explicit_format_overrides(self, tmp_path):
        # Write JSON content but with .txt extension, force json format
        p = tmp_path / "data.txt"
        p.write_text(json.dumps(VALID_JSON_DATA), encoding="utf-8")
        decision = import_file(str(p), fmt="json")
        assert decision.title == "Laptop Comparison"

    def test_unknown_format_string_raises(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps(VALID_JSON_DATA), encoding="utf-8")
        with pytest.raises(ValueError, match="Unknown format"):
            import_file(str(p), fmt="xml")


class TestBuildDecision:
    """Tests for _build_decision() internals."""

    def test_weight_normalization(self):
        data = {
            "title": "Test",
            "alternatives": ["A", "B"],
            "criteria": [
                {"name": "C1", "weight": 2.0},
                {"name": "C2", "weight": 3.0},
            ],
            "scores": {"A": {"C1": 8, "C2": 7}, "B": {"C1": 6, "C2": 9}},
        }
        decision = _build_decision(data)
        total = sum(c.weight for c in decision.criteria)
        assert abs(total - 1.0) < 1e-9

    def test_wsm_always_computed(self):
        data = {
            "title": "Test",
            "alternatives": ["A", "B"],
            "criteria": [{"name": "C1", "weight": 1.0}],
            "scores": {"A": {"C1": 8}, "B": {"C1": 6}},
        }
        decision = _build_decision(data)
        assert "wsm" in decision.rankings

    def test_topsis_for_standard_tier(self):
        """4 alternatives and 4 criteria -> Standard tier -> TOPSIS computed."""
        data = {
            "title": "Test",
            "alternatives": ["A", "B", "C", "D"],
            "criteria": [
                {"name": f"C{i}", "weight": 0.25}
                for i in range(4)
            ],
            "scores": {
                alt: {f"C{i}": 5.0 + i for i in range(4)}
                for alt in ["A", "B", "C", "D"]
            },
        }
        decision = _build_decision(data)
        assert decision.tier == Tier.STANDARD
        assert "topsis" in decision.rankings

    def test_quick_tier_no_topsis(self):
        """2 alternatives and 2 criteria -> Quick tier -> no TOPSIS."""
        data = {
            "title": "Test",
            "alternatives": ["A", "B"],
            "criteria": [
                {"name": "C1", "weight": 0.5},
                {"name": "C2", "weight": 0.5},
            ],
            "scores": {"A": {"C1": 8, "C2": 7}, "B": {"C1": 6, "C2": 9}},
        }
        decision = _build_decision(data)
        assert decision.tier == Tier.QUICK
        assert "topsis" not in decision.rankings

    def test_default_score_for_missing_value(self):
        """Missing scores default to 5.0."""
        data = {
            "title": "Test",
            "alternatives": ["A"],
            "criteria": [{"name": "C1", "weight": 1.0}],
            "scores": {"A": {}},  # No scores provided
        }
        decision = _build_decision(data)
        assert decision.scores[0].value == 5.0
