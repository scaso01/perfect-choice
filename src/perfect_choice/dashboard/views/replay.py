"""Replay view — re-weight and compare decision rankings."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from perfect_choice.config import Config
from perfect_choice.db import Database
from perfect_choice.models import Criterion, PairwiseComparison, Tier
from perfect_choice.scoring import wsm_rank, topsis_rank
from perfect_choice.ahp import (
    build_comparison_matrix,
    compute_priority_vector,
    compute_consistency_ratio,
    required_comparisons,
)
from perfect_choice.dashboard.theme import COLORS, PLOTLY_LAYOUT

# Saaty scale labels for select_slider
SAATY_OPTIONS = [
    "B overwhelmingly >",
    "B strongly >",
    "B moderately >",
    "B slightly >",
    "Equal",
    "A slightly >",
    "A moderately >",
    "A strongly >",
    "A overwhelmingly >",
]
SAATY_VALUES = [1 / 9, 1 / 7, 1 / 5, 1 / 3, 1, 3, 5, 7, 9]


def render() -> None:
    """Render the replay view for re-weighting a saved decision."""
    st.header("Replay Decision")

    decision_id = st.session_state.get("replay_decision_id")
    if not decision_id:
        st.warning("No decision selected for replay. Go to History to select one.")
        return

    config = Config()
    with Database(config.db_path) as db:
        decision = db.get_decision(decision_id)

    if not decision:
        st.error("Decision not found.")
        return

    st.subheader(decision.title)
    st.caption(
        f"Tier: {decision.tier.value.upper()} | "
        f"{len(decision.alternatives)} alternatives, "
        f"{len(decision.criteria)} criteria"
    )

    # Show original weights
    st.markdown("**Original Weights:**")
    orig_cols = st.columns(len(decision.criteria))
    for i, c in enumerate(decision.criteria):
        orig_cols[i].metric(c.name, f"{c.weight:.1%}")

    st.divider()
    st.subheader("New Weights")

    # Weight input depends on tier
    new_criteria = _collect_new_weights(decision)

    # Compare button
    if st.button("Compare Rankings", type="primary"):
        _run_comparison(decision, new_criteria)


def _collect_new_weights(decision):
    """Collect new criterion weights from user input widgets."""
    if decision.tier == Tier.QUICK:
        return _collect_slider_weights(decision)
    return _collect_pairwise_weights(decision)


def _collect_slider_weights(decision):
    """Collect weights via direct percentage sliders (quick tier)."""
    weights = []
    for i, c in enumerate(decision.criteria):
        w = st.slider(
            c.name,
            min_value=0,
            max_value=100,
            value=int(c.weight * 100),
            key=f"replay_w_{i}",
        )
        weights.append(w)

    total = sum(weights)
    if total != 100:
        st.warning(f"Weights sum to {total}%, must be 100%.")

    return [
        Criterion(c.name, w / 100.0, c.description, c.is_cost)
        for c, w in zip(decision.criteria, weights)
    ]


def _collect_pairwise_weights(decision):
    """Collect weights via AHP pairwise comparisons (standard/deep tier)."""
    criteria_names = [c.name for c in decision.criteria]
    n = len(criteria_names)
    total_comps = required_comparisons(n)

    st.caption(f"{total_comps} pairwise comparisons")

    comparisons = []
    for i in range(n):
        for j in range(i + 1, n):
            a_name, b_name = criteria_names[i], criteria_names[j]

            selected = st.select_slider(
                f"{a_name} vs {b_name}",
                options=SAATY_OPTIONS,
                value="Equal",
                key=f"replay_pair_{i}_{j}",
            )
            idx = SAATY_OPTIONS.index(selected)
            saaty_val = SAATY_VALUES[idx]
            comparisons.append(PairwiseComparison(a_name, b_name, saaty_val))

    # Compute weights from pairwise matrix
    matrix = build_comparison_matrix(criteria_names, comparisons)
    weights = compute_priority_vector(matrix)
    cr = compute_consistency_ratio(matrix, weights)

    # Show consistency ratio
    cr_color = "normal" if cr < 0.10 else "inverse"
    st.metric(
        "Consistency Ratio",
        f"{cr:.3f}",
        delta="OK" if cr < 0.10 else "Inconsistent!",
        delta_color=cr_color,
    )

    return [
        Criterion(c.name, w, c.description, c.is_cost)
        for c, w in zip(decision.criteria, weights)
    ]


def _run_comparison(decision, new_criteria):
    """Compute new rankings and render side-by-side comparison."""
    alt_names = [a.name for a in decision.alternatives]
    scores_list = list(decision.scores)

    # New rankings
    new_rankings = {"wsm": wsm_rank(alt_names, new_criteria, scores_list)}
    if decision.tier in (Tier.STANDARD, Tier.DEEP):
        new_rankings["topsis"] = topsis_rank(alt_names, new_criteria, scores_list)

    # Side-by-side comparison
    st.subheader("Comparison: Original vs New")

    col_orig, col_new = st.columns(2)

    with col_orig:
        st.markdown("**Original Rankings**")
        _render_ranking_chart(decision.rankings, "Original")

    with col_new:
        st.markdown("**New Rankings**")
        _render_ranking_chart(
            {m: tuple(r) for m, r in new_rankings.items()}, "New"
        )

    # Weight comparison chart
    st.subheader("Weight Comparison")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Original",
            x=[c.name for c in decision.criteria],
            y=[c.weight * 100 for c in decision.criteria],
            marker_color=COLORS["muted"],
        )
    )
    fig.add_trace(
        go.Bar(
            name="New",
            x=[c.name for c in new_criteria],
            y=[c.weight * 100 for c in new_criteria],
            marker_color=COLORS["primary"],
        )
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        barmode="group",
        yaxis_title="Weight (%)",
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_ranking_chart(rankings, label):
    """Render a ranking bar chart for one set of results."""
    if not rankings:
        st.info("No rankings available.")
        return

    fig = go.Figure()
    for method, results in rankings.items():
        sorted_results = sorted(results, key=lambda r: r.rank)
        fig.add_trace(
            go.Bar(
                name=method.upper(),
                x=[r.alternative_name for r in sorted_results],
                y=[r.score for r in sorted_results],
                marker_color=COLORS.get(method, COLORS["primary"]),
                text=[f"#{r.rank}" for r in sorted_results],
                textposition="auto",
            )
        )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        barmode="group",
        yaxis_title="Score",
        height=300,
    )
    st.plotly_chart(fig, use_container_width=True)
