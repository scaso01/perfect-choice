"""Tests for decision templates."""
from __future__ import annotations

import pytest

from perfect_choice.templates import get_template, list_templates, match_template


class TestListTemplates:
    """Tests for list_templates()."""

    def test_returns_all_six(self):
        names = list_templates()
        assert len(names) == 6

    def test_expected_names(self):
        names = set(list_templates())
        expected = {"job_offer", "apartment", "car", "laptop", "vacation", "college"}
        assert names == expected


class TestGetTemplate:
    """Tests for get_template()."""

    def test_valid_template(self):
        tmpl = get_template("job_offer")
        assert tmpl is not None
        assert "criteria" in tmpl
        assert "description" in tmpl

    def test_unknown_template_returns_none(self):
        assert get_template("nonexistent") is None

    def test_all_templates_have_six_criteria(self):
        for name in list_templates():
            tmpl = get_template(name)
            assert len(tmpl["criteria"]) == 6, f"{name} has {len(tmpl['criteria'])} criteria"

    def test_criteria_have_required_keys(self):
        required_keys = {"name", "description", "is_cost"}
        for name in list_templates():
            tmpl = get_template(name)
            for crit in tmpl["criteria"]:
                assert required_keys.issubset(crit.keys()), (
                    f"{name} criterion {crit.get('name', '?')} missing keys"
                )


class TestMatchTemplate:
    """Tests for match_template()."""

    @pytest.mark.parametrize(
        "title, expected",
        [
            ("Which job offer should I take?", "job_offer"),
            ("Best career move", "job_offer"),
            ("Apartment hunting", "apartment"),
            ("Buying a car", "car"),
            ("New laptop for work", "laptop"),
            ("Summer vacation planning", "vacation"),
            ("College decision", "college"),
            ("University comparison", "college"),
        ],
    )
    def test_keyword_matching(self, title: str, expected: str):
        assert match_template(title) == expected

    def test_no_match_returns_none(self):
        assert match_template("Which paint color for the kitchen?") is None

    def test_case_insensitive(self):
        assert match_template("JOB OFFER comparison") == "job_offer"
