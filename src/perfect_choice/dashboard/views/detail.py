"""Detail view — full decision analysis display."""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from perfect_choice.config import Config
from perfect_choice.db import Database
from perfect_choice.dashboard.theme import COLORS, PLOTLY_LAYOUT


def render() -> None:
    st.header("Decision Detail")

    decision_id = st.session_state.get("selected_decision_id")
    if not decision_id:
        st.warning("No decision selected. Go to History to select one.")
        return

    config = Config()
    with Database(config.db_path) as db:
        decision = db.get_decision(decision_id)

    if not decision:
        st.error(f"Decision '{decision_id}' not found.")
        return

    # Title bar
    st.subheader(decision.title)
    if decision.description:
        st.caption(decision.description)

    # Metrics row
    cols = st.columns(4)
    cols[0].metric("Tier", decision.tier.value.upper())
    cols[1].metric("Status", decision.status.value.replace("_", " ").title())
    cols[2].metric("Alternatives", str(len(decision.alternatives)))
    cr_display = (
        f"{decision.consistency_ratio:.3f}"
        if decision.consistency_ratio is not None
        else "N/A"
    )
    cols[3].metric("Consistency Ratio", cr_display)

    st.divider()

    # Two-column layout: criteria weights + rankings
    left, right = st.columns(2)

    with left:
        st.subheader("Criteria Weights")
        if decision.criteria:
            criteria_sorted = sorted(
                decision.criteria, key=lambda c: c.weight, reverse=True
            )
            fig_weights = go.Figure()
            fig_weights.add_trace(
                go.Bar(
                    y=[c.name for c in criteria_sorted],
                    x=[c.weight * 100 for c in criteria_sorted],
                    orientation="h",
                    marker_color=[
                        COLORS["danger"] if c.is_cost else COLORS["primary"]
                        for c in criteria_sorted
                    ],
                    text=[f"{c.weight:.1%}" for c in criteria_sorted],
                    textposition="auto",
                )
            )
            fig_weights.update_layout(
                **PLOTLY_LAYOUT,
                xaxis_title="Weight (%)",
                yaxis=dict(autorange="reversed"),
                height=max(250, len(decision.criteria) * 45),
            )
            st.plotly_chart(fig_weights, use_container_width=True)
        else:
            st.info("No criteria defined.")

    with right:
        st.subheader("Rankings")
        if decision.rankings:
            fig_rank = go.Figure()
            for method, results in decision.rankings.items():
                sorted_results = sorted(results, key=lambda r: r.rank)
                fig_rank.add_trace(
                    go.Bar(
                        name=method.upper(),
                        x=[r.alternative_name for r in sorted_results],
                        y=[r.score for r in sorted_results],
                        marker_color=COLORS.get(method, COLORS["primary"]),
                        text=[f"#{r.rank}" for r in sorted_results],
                        textposition="auto",
                    )
                )
            fig_rank.update_layout(
                **PLOTLY_LAYOUT,
                barmode="group",
                yaxis_title="Score",
                height=350,
            )
            st.plotly_chart(fig_rank, use_container_width=True)
        else:
            st.info("No rankings computed.")

    # Decision matrix
    st.subheader("Decision Matrix")
    if decision.scores:
        import pandas as pd

        # Build matrix as dict of dicts
        matrix_data: dict[str, dict[str, float]] = {}
        for s in decision.scores:
            if s.alternative_name not in matrix_data:
                matrix_data[s.alternative_name] = {}
            matrix_data[s.alternative_name][s.criterion_name] = s.value

        df = pd.DataFrame(matrix_data).T
        # Reorder columns by criteria order
        col_order = [c.name for c in decision.criteria if c.name in df.columns]
        df = df[col_order]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No scores recorded.")

    # Sensitivity analysis
    if decision.sensitivity:
        st.subheader("Sensitivity Analysis")
        _render_sensitivity_chart(decision)

    # LLM insights
    if decision.llm_summary or decision.llm_bias_notes or decision.llm_devils_advocate:
        st.subheader("AI Insights")
        if decision.llm_summary:
            with st.expander("Summary", expanded=True):
                st.write(decision.llm_summary)
        if decision.llm_bias_notes:
            with st.expander("Bias Analysis"):
                st.write(decision.llm_bias_notes)
        if decision.llm_devils_advocate:
            with st.expander("Devil's Advocate"):
                st.write(decision.llm_devils_advocate)

    # Actions
    st.divider()
    col_a, col_b, col_c = st.columns(3)

    # Export JSON
    with col_a:
        from perfect_choice.cli import _export_json

        json_str = _export_json(decision)
        st.download_button(
            "Download JSON",
            data=json_str,
            file_name=f"decision_{decision.id[:8]}.json",
            mime="application/json",
        )

    # Export Markdown
    with col_b:
        from perfect_choice.cli import _export_markdown

        md_str = _export_markdown(decision)
        st.download_button(
            "Download Markdown",
            data=md_str,
            file_name=f"decision_{decision.id[:8]}.md",
            mime="text/markdown",
        )

    # Replay button
    with col_c:
        if st.button("Replay with New Weights"):
            st.session_state["replay_decision_id"] = decision.id
            st.session_state["nav_page"] = "Replay"
            st.rerun()


def _render_sensitivity_chart(decision) -> None:
    """Render sensitivity analysis as a bar chart."""
    names: list[str] = []
    thresholds: list[float] = []
    colors: list[str] = []
    labels: list[str] = []

    for s in decision.sensitivity:
        names.append(s.criterion_name)
        if s.threshold_pct is None:
            thresholds.append(50)  # Cap at max for display
            colors.append(COLORS["success"])
            labels.append("Stable (>50%)")
        else:
            thresholds.append(s.threshold_pct)
            if s.threshold_pct < 15:
                colors.append(COLORS["danger"])
            elif s.threshold_pct < 30:
                colors.append(COLORS["warning"])
            else:
                colors.append(COLORS["success"])
            labels.append(f"Flips at +/-{s.threshold_pct:.0f}% -> {s.flip_to}")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=names,
            x=thresholds,
            orientation="h",
            marker_color=colors,
            text=labels,
            textposition="outside",
        )
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        xaxis_title="Weight Change Threshold (%)",
        yaxis=dict(autorange="reversed"),
        height=max(250, len(names) * 45),
    )
    st.plotly_chart(fig, use_container_width=True)
