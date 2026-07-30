"""New Decision wizard -- 4-stage Streamlit workflow."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from itertools import combinations

import plotly.graph_objects as go
import streamlit as st

from perfect_choice.ahp import (
    build_comparison_matrix,
    compute_consistency_ratio,
    compute_priority_vector,
)
from perfect_choice.config import Config
from perfect_choice.db import Database
from perfect_choice.llm import LLMClient
from perfect_choice.models import (
    Alternative,
    Criterion,
    Decision,
    DecisionStatus,
    PairwiseComparison,
    RankingResult,
    Score,
    Tier,
    detect_tier,
)
from perfect_choice.scoring import topsis_rank, wsm_rank
from perfect_choice.sensitivity import analyze_sensitivity

from perfect_choice.dashboard.theme import COLORS, PLOTLY_LAYOUT

# ---------------------------------------------------------------------------
# Saaty pairwise labels (local -- do NOT import from interactive.py)
# ---------------------------------------------------------------------------

PAIRWISE_SLIDER_OPTIONS: list[str] = [
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

PAIRWISE_SAATY_MAP: dict[str, float] = {
    "B overwhelmingly >": 1 / 9,
    "B strongly >": 1 / 7,
    "B moderately >": 1 / 5,
    "B slightly >": 1 / 3,
    "Equal": 1.0,
    "A slightly >": 3.0,
    "A moderately >": 5.0,
    "A strongly >": 7.0,
    "A overwhelmingly >": 9.0,
}

# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------


def _init_state() -> None:
    """Ensure all wizard keys exist in session_state."""
    defaults: dict[str, object] = {
        "wiz_stage": 1,
        "wiz_title": "",
        "wiz_description": "",
        "wiz_alternatives": ["", ""],
        "wiz_criteria": [{"name": "", "is_cost": False}],
        "wiz_tier": Tier.QUICK,
        "wiz_weights": [],
        "wiz_comparisons": [],
        "wiz_cr": None,
        "wiz_scores": {},
        "wiz_results": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _clear_state() -> None:
    """Remove all wiz_ keys so the wizard restarts cleanly."""
    keys = [k for k in st.session_state if k.startswith("wiz_")]
    for k in keys:
        del st.session_state[k]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render() -> None:
    """Render the New Decision wizard."""
    _init_state()

    stage: int = st.session_state["wiz_stage"]

    # Progress indicator
    st.progress(stage / 4, text=f"Stage {stage} of 4")

    if stage == 1:
        _stage_setup()
    elif stage == 2:
        _stage_weights()
    elif stage == 3:
        _stage_scoring()
    elif stage == 4:
        _stage_results()


# ---------------------------------------------------------------------------
# Stage 1 -- Setup
# ---------------------------------------------------------------------------


def _stage_setup() -> None:
    st.header("New Decision")
    st.subheader("Stage 1: Setup")

    # Title and description
    st.session_state["wiz_title"] = st.text_input(
        "Decision title",
        value=st.session_state["wiz_title"],
        key="wiz_title_input",
    )
    st.session_state["wiz_description"] = st.text_input(
        "Brief description (optional)",
        value=st.session_state["wiz_description"],
        key="wiz_description_input",
    )

    # --- Alternatives ---
    st.markdown("**Alternatives** (minimum 2)")
    alts: list[str] = st.session_state["wiz_alternatives"]
    new_alts: list[str] = []
    for idx, alt_val in enumerate(alts):
        new_alts.append(
            st.text_input(
                f"Option {idx + 1}",
                value=alt_val,
                key=f"wiz_alt_{idx}",
            )
        )
    st.session_state["wiz_alternatives"] = new_alts

    if st.button("Add alternative", key="wiz_add_alt"):
        st.session_state["wiz_alternatives"].append("")
        st.rerun()

    # --- Criteria ---
    st.markdown("**Criteria** (minimum 1)")
    crits: list[dict] = st.session_state["wiz_criteria"]
    new_crits: list[dict] = []
    for idx, crit_val in enumerate(crits):
        col_name, col_cost = st.columns([3, 1])
        with col_name:
            name = st.text_input(
                f"Criterion {idx + 1}",
                value=crit_val.get("name", ""),
                key=f"wiz_crit_name_{idx}",
            )
        with col_cost:
            is_cost = st.checkbox(
                "Cost?",
                value=crit_val.get("is_cost", False),
                key=f"wiz_crit_cost_{idx}",
                help="Check if lower is better (e.g. price, commute time)",
            )
        new_crits.append({"name": name, "is_cost": is_cost})
    st.session_state["wiz_criteria"] = new_crits

    col_add, col_suggest = st.columns(2)
    with col_add:
        if st.button("Add criterion", key="wiz_add_crit"):
            st.session_state["wiz_criteria"].append({"name": "", "is_cost": False})
            st.rerun()

    with col_suggest:
        if st.button("Suggest criteria (LLM)", key="wiz_suggest_crit"):
            _suggest_criteria()

    # Auto-detect tier
    filled_alts = [a for a in st.session_state["wiz_alternatives"] if a.strip()]
    filled_crits = [c for c in st.session_state["wiz_criteria"] if c["name"].strip()]
    tier = detect_tier(len(filled_alts), len(filled_crits))
    st.session_state["wiz_tier"] = tier
    st.info(f"Auto-detected tier: **{tier.value.upper()}**")

    # Validation and advance
    if st.button("Next: Set Weights", key="wiz_to_stage2", type="primary"):
        title = st.session_state["wiz_title"].strip()
        if not title:
            st.error("Decision title is required.")
            return
        if len(filled_alts) < 2:
            st.error("At least 2 alternatives are required.")
            return
        if len(filled_crits) < 1:
            st.error("At least 1 criterion is required.")
            return
        # Clean up empty entries
        st.session_state["wiz_alternatives"] = [a for a in st.session_state["wiz_alternatives"] if a.strip()]
        st.session_state["wiz_criteria"] = [c for c in st.session_state["wiz_criteria"] if c["name"].strip()]
        st.session_state["wiz_stage"] = 2
        st.rerun()


def _suggest_criteria() -> None:
    """Call LLM to suggest criteria and populate the list."""
    config = Config()
    if config.no_llm or not st.session_state.get("llm_enabled", True):
        st.warning("LLM is disabled.")
        return
    thinking = st.session_state.get("llm_thinking", False)
    llm = LLMClient(config, thinking=thinking)
    if not llm.is_available():
        st.warning("LLM is not available. Check that llama-server is running.")
        return

    title = st.session_state["wiz_title"].strip()
    desc = st.session_state["wiz_description"].strip()
    context = f"{title}: {desc}" if desc else title
    alts = [a for a in st.session_state["wiz_alternatives"] if a.strip()]
    if not context or not alts:
        st.warning("Enter a title and at least one alternative before suggesting criteria.")
        return

    with st.spinner("Asking LLM for criteria suggestions..."):
        suggestions = llm.suggest_criteria(context, alts)

    if not suggestions:
        st.warning("LLM returned no suggestions.")
        return

    # Replace criteria list with suggestions
    st.session_state["wiz_criteria"] = [
        {"name": s["name"], "is_cost": s.get("is_cost", False)}
        for s in suggestions
    ]
    st.rerun()


# ---------------------------------------------------------------------------
# Stage 2 -- Weights
# ---------------------------------------------------------------------------


def _stage_weights() -> None:
    st.header("New Decision")
    st.subheader("Stage 2: Set Weights")

    tier: Tier = st.session_state["wiz_tier"]
    criteria: list[dict] = st.session_state["wiz_criteria"]

    if tier == Tier.QUICK:
        _weights_slider(criteria)
    else:
        _weights_pairwise(criteria)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Back to Setup", key="wiz_back_to_1"):
            st.session_state["wiz_stage"] = 1
            st.rerun()
    with col_next:
        if st.button("Next: Score Options", key="wiz_to_stage3", type="primary"):
            weights = st.session_state["wiz_weights"]
            if not weights:
                st.error("Weights have not been computed yet.")
                return
            st.session_state["wiz_stage"] = 3
            st.rerun()


def _weights_slider(criteria: list[dict]) -> None:
    """Quick tier: direct percentage sliders."""
    st.markdown("Assign percentage weights to each criterion (must total 100).")

    weights: list[float] = []
    default_w = 100 // len(criteria)
    for idx, crit in enumerate(criteria):
        # Use stored weight if available, otherwise default
        existing = st.session_state.get("wiz_weights", [])
        init_val = int(existing[idx] * 100) if idx < len(existing) else default_w
        w = st.slider(
            crit["name"],
            min_value=0,
            max_value=100,
            value=init_val,
            step=1,
            key=f"wiz_wslider_{idx}",
        )
        weights.append(w)

    total = sum(weights)
    if total != 100:
        st.warning(f"Weights sum to **{total}%**, not 100%. Adjust before proceeding.")
    else:
        st.success("Weights sum to 100%.")

    # Store normalized weights
    st.session_state["wiz_weights"] = [w / 100.0 for w in weights]
    st.session_state["wiz_comparisons"] = []
    st.session_state["wiz_cr"] = None


def _weights_pairwise(criteria: list[dict]) -> None:
    """Standard/Deep tier: AHP pairwise comparisons."""
    names = [c["name"] for c in criteria]
    pairs = list(combinations(range(len(names)), 2))
    st.markdown(
        f"Compare each pair of criteria ({len(pairs)} comparisons). "
        f"**A** is the first criterion, **B** is the second."
    )

    comparisons: list[PairwiseComparison] = []
    for pair_idx, (i, j) in enumerate(pairs):
        a_name, b_name = names[i], names[j]
        label = f"**{a_name}** vs **{b_name}**"
        selected = st.select_slider(
            label,
            options=PAIRWISE_SLIDER_OPTIONS,
            value="Equal",
            key=f"wiz_pw_{pair_idx}",
        )
        saaty_val = PAIRWISE_SAATY_MAP[selected]
        comparisons.append(PairwiseComparison(a_name, b_name, saaty_val))

    st.session_state["wiz_comparisons"] = comparisons

    # Compute AHP weights and CR
    matrix = build_comparison_matrix(names, comparisons)
    weights = compute_priority_vector(matrix)
    cr = compute_consistency_ratio(matrix, weights)

    st.session_state["wiz_weights"] = weights
    st.session_state["wiz_cr"] = cr

    # Display CR metric
    col_cr, col_chart = st.columns([1, 2])
    with col_cr:
        cr_delta_color = "normal" if cr <= 0.10 else "inverse"
        st.metric(
            "Consistency Ratio",
            f"{cr:.4f}",
            delta="OK" if cr <= 0.10 else "Inconsistent",
            delta_color=cr_delta_color,
        )
        if cr > 0.10:
            st.error(
                "CR > 0.10 indicates contradictions in your comparisons. "
                "Adjust the sliders above to improve consistency."
            )

    # Display weights as bar chart
    with col_chart:
        import pandas as pd  # noqa: PLC0415 (local import for optional dep)

        weight_df = pd.DataFrame(
            {"Criterion": names, "Weight": weights}
        ).sort_values("Weight", ascending=True)
        st.bar_chart(weight_df, x="Criterion", y="Weight", horizontal=True)


# ---------------------------------------------------------------------------
# Stage 3 -- Scoring
# ---------------------------------------------------------------------------


def _stage_scoring() -> None:
    st.header("New Decision")
    st.subheader("Stage 3: Score Options")
    st.markdown("Rate each alternative on each criterion (1 = worst, 10 = best).")

    alternatives: list[str] = st.session_state["wiz_alternatives"]
    criteria: list[dict] = st.session_state["wiz_criteria"]
    scores: dict[tuple[str, str], float] = st.session_state.get("wiz_scores", {})

    for alt in alternatives:
        with st.expander(f"**{alt}**", expanded=True):
            for crit_idx, crit in enumerate(criteria):
                cost_hint = " (lower = better)" if crit["is_cost"] else ""
                score_key = (alt, crit["name"])
                default_val = int(scores.get(score_key, 5))
                val = st.slider(
                    f'{crit["name"]}{cost_hint}',
                    min_value=1,
                    max_value=10,
                    value=default_val,
                    key=f"wiz_score_{alt}_{crit_idx}",
                )
                scores[score_key] = float(val)

    st.session_state["wiz_scores"] = scores

    col_back, col_analyze = st.columns(2)
    with col_back:
        if st.button("Back to Weights", key="wiz_back_to_2"):
            st.session_state["wiz_stage"] = 2
            st.rerun()
    with col_analyze:
        if st.button("Analyze", key="wiz_analyze", type="primary"):
            _run_analysis()
            st.session_state["wiz_stage"] = 4
            st.rerun()


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------


def _run_analysis() -> None:
    """Compute rankings, sensitivity, LLM features. Store in wiz_results."""
    alternatives: list[str] = st.session_state["wiz_alternatives"]
    criteria_defs: list[dict] = st.session_state["wiz_criteria"]
    weights: list[float] = st.session_state["wiz_weights"]
    tier: Tier = st.session_state["wiz_tier"]
    raw_scores: dict[tuple[str, str], float] = st.session_state["wiz_scores"]

    # Build model objects
    criteria_objs = [
        Criterion(
            name=cd["name"],
            weight=weights[idx],
            is_cost=cd["is_cost"],
        )
        for idx, cd in enumerate(criteria_defs)
    ]
    score_objs = [
        Score(alternative_name=alt, criterion_name=crit, value=val)
        for (alt, crit), val in raw_scores.items()
    ]

    # Rankings
    rankings: dict[str, list[RankingResult]] = {}
    wsm_results = wsm_rank(alternatives, criteria_objs, score_objs)
    rankings["wsm"] = wsm_results

    if tier in (Tier.STANDARD, Tier.DEEP):
        topsis_results = topsis_rank(alternatives, criteria_objs, score_objs)
        rankings["topsis"] = topsis_results

    # Sensitivity (Deep only)
    sensitivity = []
    if tier == Tier.DEEP:
        sensitivity = analyze_sensitivity(
            alternatives, criteria_objs, score_objs, wsm_rank
        )

    # LLM features
    llm_summary = ""
    llm_bias = ""
    llm_devils = ""
    config = Config()
    llm: LLMClient | None = None
    if not config.no_llm and st.session_state.get("llm_enabled", True):
        thinking = st.session_state.get("llm_thinking", False)
        llm = LLMClient(config, thinking=thinking)
        if not llm.is_available():
            llm = None

    if llm:
        ranked_for_llm = {m: list(r) for m, r in rankings.items()}
        title = st.session_state["wiz_title"]
        sens_text = ""
        if sensitivity:
            lines = []
            for s in sensitivity:
                if s.threshold_pct is None:
                    lines.append(f"{s.criterion_name}: stable")
                else:
                    lines.append(
                        f"{s.criterion_name}: flips at +/-{s.threshold_pct:.0f}% -> {s.flip_to}"
                    )
            sens_text = "\n".join(lines)

        llm_summary = llm.summarize_decision(
            title, ranked_for_llm, criteria_objs, sens_text
        )
        if tier in (Tier.STANDARD, Tier.DEEP):
            llm_bias = llm.detect_bias(criteria_objs, score_objs)
        if tier == Tier.DEEP and wsm_results:
            llm_devils = llm.devils_advocate(title, wsm_results, criteria_objs)

    st.session_state["wiz_results"] = {
        "rankings": rankings,
        "criteria_objs": criteria_objs,
        "score_objs": score_objs,
        "sensitivity": sensitivity,
        "llm_summary": llm_summary,
        "llm_bias": llm_bias,
        "llm_devils": llm_devils,
    }


# ---------------------------------------------------------------------------
# Stage 4 -- Results
# ---------------------------------------------------------------------------


def _stage_results() -> None:
    st.header("New Decision")
    st.subheader("Stage 4: Results")

    results: dict = st.session_state["wiz_results"]
    if not results:
        st.error("No results available. Please go back and run analysis.")
        return

    rankings: dict[str, list[RankingResult]] = results["rankings"]
    criteria_objs: list[Criterion] = results["criteria_objs"]
    sensitivity = results.get("sensitivity", [])
    llm_summary: str = results.get("llm_summary", "")
    llm_bias: str = results.get("llm_bias", "")
    llm_devils: str = results.get("llm_devils", "")
    tier: Tier = st.session_state["wiz_tier"]

    # --- Ranking bar chart ---
    _render_ranking_chart(rankings)

    # --- Criteria weight donut ---
    _render_weight_donut(criteria_objs)

    # --- Sensitivity chart (Deep only) ---
    if tier == Tier.DEEP and sensitivity:
        _render_sensitivity_chart(sensitivity)

    # --- LLM panels ---
    if llm_summary:
        with st.expander("LLM Summary", expanded=True):
            st.markdown(llm_summary)
    if llm_bias:
        with st.expander("Bias Analysis"):
            st.markdown(llm_bias)
    if llm_devils:
        with st.expander("Devil's Advocate"):
            st.markdown(llm_devils)

    # --- Actions ---
    st.divider()
    col_save, col_restart = st.columns(2)
    with col_save:
        if st.button("Save Decision", key="wiz_save", type="primary"):
            _save_decision()
    with col_restart:
        if st.button("Start Over", key="wiz_restart"):
            _clear_state()
            st.rerun()


# ---------------------------------------------------------------------------
# Plotly charts
# ---------------------------------------------------------------------------


def _render_ranking_chart(rankings: dict[str, list[RankingResult]]) -> None:
    """Grouped bar chart of rankings by method."""
    fig = go.Figure()

    for method, results in rankings.items():
        sorted_results = sorted(results, key=lambda r: r.rank)
        alt_names = [r.alternative_name for r in sorted_results]
        scores = [r.score for r in sorted_results]
        color = COLORS.get(method, COLORS["primary"])
        fig.add_trace(
            go.Bar(
                x=alt_names,
                y=scores,
                name=method.upper(),
                marker_color=color,
            )
        )

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Rankings by Method",
        barmode="group",
        yaxis_title="Score",
        xaxis_title="Alternative",
    )
    st.plotly_chart(fig, width="stretch")


def _render_weight_donut(criteria: list[Criterion]) -> None:
    """Criteria weight donut chart."""
    names = [c.name for c in criteria]
    weights = [c.weight for c in criteria]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=names,
                values=weights,
                hole=0.4,
                textinfo="label+percent",
                marker=dict(
                    colors=[
                        COLORS["primary"],
                        COLORS["success"],
                        COLORS["warning"],
                        COLORS["danger"],
                        COLORS["muted"],
                        COLORS["topsis"],
                        "#10B981",
                        "#F59E0B",
                        "#EF4444",
                        "#8B5CF6",
                    ][: len(names)]
                ),
            )
        ]
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Criteria Weights",
    )
    st.plotly_chart(fig, width="stretch")


def _render_sensitivity_chart(sensitivity: list) -> None:
    """Horizontal bar chart of sensitivity thresholds."""
    names = []
    thresholds = []
    colors = []
    for s in sensitivity:
        names.append(s.criterion_name)
        pct = s.threshold_pct if s.threshold_pct is not None else 50.0
        thresholds.append(pct)
        if s.threshold_pct is None:
            colors.append(COLORS["success"])
        elif s.threshold_pct < 15:
            colors.append(COLORS["danger"])
        elif s.threshold_pct < 30:
            colors.append(COLORS["warning"])
        else:
            colors.append(COLORS["success"])

    fig = go.Figure(
        data=[
            go.Bar(
                x=thresholds,
                y=names,
                orientation="h",
                marker_color=colors,
                text=[
                    f"+/-{t:.0f}%" if s.threshold_pct is not None else "Stable"
                    for t, s in zip(thresholds, sensitivity)
                ],
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Sensitivity Analysis (% weight change to flip #1)",
        xaxis_title="Weight Perturbation (%)",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# Save to database
# ---------------------------------------------------------------------------


def _save_decision() -> None:
    """Build Decision object and persist to SQLite."""
    results: dict = st.session_state["wiz_results"]
    criteria_objs: list[Criterion] = results["criteria_objs"]
    score_objs: list[Score] = results["score_objs"]
    rankings: dict[str, list[RankingResult]] = results["rankings"]
    sensitivity = results.get("sensitivity", [])

    now = datetime.now(timezone.utc).isoformat()
    decision = Decision(
        id=uuid.uuid4().hex,
        title=st.session_state["wiz_title"],
        description=st.session_state["wiz_description"],
        tier=st.session_state["wiz_tier"],
        criteria=tuple(criteria_objs),
        alternatives=tuple(
            Alternative(name=a) for a in st.session_state["wiz_alternatives"]
        ),
        scores=tuple(score_objs),
        pairwise_comparisons=tuple(st.session_state.get("wiz_comparisons", [])),
        rankings={m: tuple(r) for m, r in rankings.items()},
        sensitivity=tuple(sensitivity),
        consistency_ratio=st.session_state.get("wiz_cr"),
        llm_summary=results.get("llm_summary", ""),
        llm_devils_advocate=results.get("llm_devils", ""),
        llm_bias_notes=results.get("llm_bias", ""),
        created_at=now,
        completed_at=now,
        status=DecisionStatus.COMPLETED,
    )

    config = Config()
    with Database(config.db_path) as db:
        db.save_decision(decision)

    st.success(f"Decision saved. ID: `{decision.id[:8]}`")
