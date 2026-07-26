"""Perfect Choice — Streamlit Dashboard."""

from __future__ import annotations

import os

import streamlit as st

# Page config must be first Streamlit call
st.set_page_config(
    page_title="Perfect Choice",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load CSS
_CSS_PATH = os.path.join(os.path.dirname(__file__), "style.css")
if os.path.exists(_CSS_PATH):
    with open(_CSS_PATH, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

from perfect_choice.dashboard.views import detail, history, new_decision, replay

# Page registry
PAGES: dict[str, object] = {
    "New Decision": new_decision,
    "History": history,
    "Decision Detail": detail,
    "Replay": replay,
}


def main() -> None:
    """Dashboard entry point."""
    # Sidebar navigation
    with st.sidebar:
        st.title("Perfect Choice")
        st.caption("Structured Decision Analysis")
        st.divider()

        # Determine default page
        default_idx = 0
        if st.session_state.get("nav_page"):
            page_name = st.session_state["nav_page"]
            if page_name in PAGES:
                default_idx = list(PAGES.keys()).index(page_name)

        page = st.radio(
            "Navigate",
            list(PAGES.keys()),
            index=default_idx,
            label_visibility="collapsed",
        )

        st.divider()
        st.subheader("LLM Settings")
        st.toggle("Enable LLM", value=True, key="llm_enabled")
        st.toggle(
            "Thinking mode",
            value=False,
            key="llm_thinking",
            help="Deep reasoning (slower, ~2 min). Off = fast responses (~5 s).",
        )
        st.divider()
        st.caption("v0.1.0 | AHP + WSM + TOPSIS")

    # Clear nav override after using it
    if "nav_page" in st.session_state and page != st.session_state.get("nav_page"):
        del st.session_state["nav_page"]

    # Route to page
    PAGES[page].render()  # type: ignore[union-attr]


if __name__ == "__main__":
    main()
