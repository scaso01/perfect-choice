"""History view — browse past decisions."""
from __future__ import annotations

import streamlit as st

from perfect_choice.config import Config
from perfect_choice.db import Database


def render() -> None:
    st.header("Decision History")

    config = Config()

    # Filters in columns
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        status_filter = st.selectbox(
            "Status", ["All", "completed", "in_progress", "abandoned"]
        )
    with col2:
        tier_filter = st.selectbox("Tier", ["All", "quick", "standard", "deep"])
    with col3:
        limit = st.number_input("Limit", min_value=5, max_value=100, value=20)

    # Load decisions
    with Database(config.db_path) as db:
        decisions = db.list_decisions(
            limit=limit,
            status_filter=status_filter if status_filter != "All" else None,
        )

    if not decisions:
        st.info("No decisions found. Create one from the New Decision page!")
        return

    # Display as a table with clickable rows
    for d in decisions:
        # Filter by tier if needed
        if tier_filter != "All" and d.tier.value != tier_filter:
            continue

        with st.container():
            cols = st.columns([1, 4, 1, 1, 1, 1])
            cols[0].code(d.id[:8])
            cols[1].markdown(f"**{d.title}**")
            cols[2].caption(d.tier.value.upper())
            cols[3].caption(d.status.value)
            cols[4].caption(d.created_at[:10] if d.created_at else "")

            # View button -> navigate to Detail
            if cols[5].button("View", key=f"view_{d.id}"):
                st.session_state["selected_decision_id"] = d.id
                st.session_state["nav_page"] = "Decision Detail"
                st.rerun()

            st.divider()

    # Bulk delete section
    with st.expander("Manage Decisions"):
        decision_to_delete = st.selectbox(
            "Select decision to delete",
            options=[(d.id[:8], d.title) for d in decisions],
            format_func=lambda x: f"{x[0]} — {x[1]}",
            key="delete_select",
        )
        if st.button("Delete Selected", type="secondary"):
            if decision_to_delete:
                full_id = next(
                    d.id for d in decisions
                    if d.id[:8] == decision_to_delete[0]
                )
                with Database(config.db_path) as db:
                    db.delete_decision(full_id)
                st.success(f"Deleted: {decision_to_delete[1]}")
                st.rerun()
