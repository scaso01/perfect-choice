"""Shared Plotly theme and color constants.

Extracted from app.py to avoid circular imports (app imports views,
views need these constants).
"""

from __future__ import annotations

PLOTLY_LAYOUT = dict(
    font=dict(family="Inter, system-ui, sans-serif", size=13),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=20, r=20, t=40, b=20),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
    ),
)

COLORS = {
    "primary": "#4F46E5",
    "success": "#059669",
    "warning": "#D97706",
    "danger": "#DC2626",
    "muted": "#6B7280",
    "wsm": "#4F46E5",
    "topsis": "#7C3AED",
}
