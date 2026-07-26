"""End-to-end journey tests for the Streamlit dashboard.

The dashboard is a second, independent implementation of the decision wizard
(`views/new_decision.py` shares no code with `interactive.py`), and nothing
exercised it before. These drive the real app through `AppTest`, so a broken
import, a renamed widget, or a Streamlit API change fails here instead of in
front of a user.
"""

from __future__ import annotations

import pytest

from perfect_choice.db import Database

AppTest = pytest.importorskip(
    "streamlit.testing.v1", reason="streamlit is required for dashboard tests"
).AppTest

APP = "src/perfect_choice/dashboard/app.py"
PAGES = ["New Decision", "History", "Decision Detail", "Replay"]

# Every wizard stage transition ends in st.rerun(). AppTest accumulates elements
# from both the interrupted and the resumed pass, so a *second* transition in the
# same instance trips over stage-1 widget nodes whose state Streamlit has already
# reclaimed. Carrying state into a fresh instance per transition avoids that
# without weakening what is asserted -- real widgets, real math, real save.
WIZ_KEYS = (
    "wiz_stage",
    "wiz_title",
    "wiz_description",
    "wiz_alternatives",
    "wiz_criteria",
    "wiz_tier",
    "wiz_weights",
    "wiz_comparisons",
    "wiz_cr",
    "wiz_scores",
    "wiz_results",
)


def _carry_forward(app):
    """A fresh dashboard holding the current wizard state."""
    carried = {}
    for key in WIZ_KEYS:
        try:
            carried[key] = app.session_state[key]
        except KeyError:
            pass
    nxt = AppTest.from_file(APP, default_timeout=60)
    nxt.run()
    for key, value in carried.items():
        nxt.session_state[key] = value
    nxt.run()
    nxt.db_path = app.db_path
    return nxt


@pytest.fixture
def app(monkeypatch, tmp_path):
    """A dashboard pointed at a throwaway DB, with the LLM switched off."""
    db_path = tmp_path / "dashboard.db"
    monkeypatch.setenv("PERFECT_CHOICE_DB_PATH", str(db_path))
    monkeypatch.setenv("PERFECT_CHOICE_NO_LLM", "1")
    at = AppTest.from_file(APP, default_timeout=60)
    at.db_path = str(db_path)  # handy for assertions
    return at


def test_dashboard_loads_without_error(app):
    app.run()
    assert not app.exception
    assert app.sidebar.radio[0].options == PAGES


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(app, page):
    """Each nav destination must render on an empty database."""
    app.run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, f"{page} raised: {app.exception}"


def test_stage_one_requires_a_title(app):
    app.run()
    app.text_input(key="wiz_alt_0").set_value("Alpha")
    app.text_input(key="wiz_alt_1").set_value("Beta")
    app.text_input(key="wiz_crit_name_0").set_value("Taste")
    app.run()
    app.button(key="wiz_to_stage2").click().run()

    assert not app.exception
    assert app.session_state["wiz_stage"] == 1, "advanced without a title"
    assert any("title is required" in e.value.lower() for e in app.error)


def test_stage_one_requires_two_alternatives(app):
    app.run()
    app.text_input(key="wiz_title_input").set_value("Lunch spot")
    app.text_input(key="wiz_alt_0").set_value("Alpha")
    app.text_input(key="wiz_crit_name_0").set_value("Taste")
    app.run()
    app.button(key="wiz_to_stage2").click().run()

    assert app.session_state["wiz_stage"] == 1, "advanced with one alternative"
    assert any("2 alternatives" in e.value for e in app.error)


def test_add_buttons_grow_the_lists(app):
    """"Add alternative" / "Add criterion" extend the wizard's inputs."""
    app.run()
    assert len(app.session_state["wiz_alternatives"]) == 2
    assert len(app.session_state["wiz_criteria"]) == 1

    app.button(key="wiz_add_alt").click().run()
    assert len(app.session_state["wiz_alternatives"]) == 3

    app.button(key="wiz_add_crit").click().run()
    assert len(app.session_state["wiz_criteria"]) == 2
    assert not app.exception


def _complete_wizard(app):
    """Build a decision through all four stages and save it.

    Same numbers as the CLI journey test, so the two independent wizard
    implementations are asserted against the identical hand-computed result:
    Alpha = 0.60(8/8) + 0.40(3/6) = 0.80
    Beta  = 0.60(6/8) + 0.40(3/3) = 0.85  <- wins
    """
    app.run()

    # --- Stage 1: setup ---
    # Seed the second criterion slot directly. Clicking "Add criterion" calls
    # st.rerun() mid-script, and AppTest cannot carry widget values across that
    # interrupted run -- the button itself is covered separately below.
    app.session_state["wiz_criteria"] = [
        {"name": "", "is_cost": False},
        {"name": "", "is_cost": False},
    ]
    app.run()

    app.text_input(key="wiz_title_input").set_value("Lunch spot")
    app.text_input(key="wiz_alt_0").set_value("Alpha")
    app.text_input(key="wiz_alt_1").set_value("Beta")
    app.text_input(key="wiz_crit_name_0").set_value("Taste")
    app.text_input(key="wiz_crit_name_1").set_value("Price")
    app.checkbox(key="wiz_crit_cost_1").set_value(True)
    # No bare run() between setting values and clicking: the click submits the
    # pending widget values, and a standalone run after a stage change trips
    # over widget nodes the previous stage left in the tree.
    app.button(key="wiz_to_stage2").click().run()

    assert not app.exception
    assert app.session_state["wiz_stage"] == 2
    # 2 alternatives x 2 criteria stays in the Quick tier (direct weight sliders).
    assert app.session_state["wiz_tier"].value == "quick"

    # --- Stage 2: weights ---
    app = _carry_forward(app)
    app.slider(key="wiz_wslider_0").set_value(60)
    app.slider(key="wiz_wslider_1").set_value(40)
    app.button(key="wiz_to_stage3").click().run()

    assert not app.exception
    assert app.session_state["wiz_stage"] == 3
    assert app.session_state["wiz_weights"] == [
        pytest.approx(0.60),
        pytest.approx(0.40),
    ]

    # --- Stage 3: scoring ---
    app = _carry_forward(app)
    app.slider(key="wiz_score_Alpha_0").set_value(8)
    app.slider(key="wiz_score_Alpha_1").set_value(6)
    app.slider(key="wiz_score_Beta_0").set_value(6)
    app.slider(key="wiz_score_Beta_1").set_value(3)
    app.button(key="wiz_analyze").click().run()

    assert not app.exception
    assert app.session_state["wiz_stage"] == 4

    # --- Stage 4: results ---
    results = app.session_state["wiz_results"]
    wsm = {r.alternative_name: r for r in results["rankings"]["wsm"]}
    assert wsm["Beta"].score == pytest.approx(0.85)
    assert wsm["Alpha"].score == pytest.approx(0.80)
    assert wsm["Beta"].rank == 1

    # --- Save, then prove it actually landed in the database ---
    app = _carry_forward(app)
    app.button(key="wiz_save").click().run()
    assert not app.exception

    with Database(app.db_path) as db:
        saved = db.list_decisions()
    assert len(saved) == 1
    assert saved[0].title == "Lunch spot"
    return app


def test_new_decision_wizard_end_to_end(app):
    """The full four-stage journey, from empty form to a row in SQLite."""
    _complete_wizard(app)


def test_saved_decision_appears_in_history(app):
    """A saved decision is visible on the History page -- the read-back path."""
    app = _carry_forward(_complete_wizard(app))

    app.sidebar.radio[0].set_value("History").run()

    assert not app.exception
    rendered = " ".join(str(m.value) for m in app.markdown)
    assert "Lunch spot" in rendered or any(
        "Lunch spot" in str(df.value.to_string()) for df in app.dataframe
    )
