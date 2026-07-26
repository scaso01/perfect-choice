"""Optional memory webhook — POST finished decisions to an external service.

Off unless PERFECT_CHOICE_BRAIN_URL is set. Point it at any endpoint that
accepts the JSON payload built below and answers `{"ok": true}`; it exists so
a long-term memory or knowledge store can keep your decision history.
"""
from __future__ import annotations

import json
import os
import urllib.request

from perfect_choice.models import Decision

BRAIN_TIMEOUT = 5


def brain_url() -> str:
    """Configured webhook endpoint, or "" when unset.

    Opt-in by design: with no PERFECT_CHOICE_BRAIN_URL set, the sync is
    skipped entirely rather than attempted. Without this, every completed
    decision paid ~4s connecting to a service almost nobody runs.
    """
    return os.environ.get("PERFECT_CHOICE_BRAIN_URL", "").strip()


def store_decision_in_brain(decision: Decision) -> bool:
    """POST a completed decision to the memory webhook. Fire-and-forget."""
    content = _format_decision(decision)
    payload = {
        "content": content,
        "memory_type": "decision",
        "importance": 0.75,
        "source": f"perfect-choice-{decision.id[:8]}",
        "tags": "perfect-choice,decision",
    }
    return _post_to_brain(payload)


def update_brain_context(decisions: list[Decision]) -> bool:
    """Update brain context with recent decision summaries."""
    if not decisions:
        return False
    lines = []
    for d in decisions[:10]:  # Last 10
        winner = ""
        if d.rankings:
            for method, results in d.rankings.items():
                sorted_r = sorted(results, key=lambda r: r.rank)
                if sorted_r:
                    winner = f" → Winner: {sorted_r[0].alternative_name} ({method.upper()})"
                    break
        lines.append(f"- {d.title} [{d.tier.value}]{winner} ({d.created_at[:10]})")

    content = "Recent decisions from Perfect Choice:\n" + "\n".join(lines)
    payload = {
        "content": content,
        "memory_type": "context",
        "importance": 0.5,
        "source": "perfect-choice-context",
        "tags": "perfect-choice,context,decisions",
    }
    return _post_to_brain(payload)


def _format_decision(decision: Decision) -> str:
    """Format a decision for brain storage."""
    parts = [f"Decision: {decision.title}"]
    if decision.description:
        parts.append(f"Description: {decision.description}")
    parts.append(f"Tier: {decision.tier.value}")
    parts.append(f"Alternatives: {', '.join(a.name for a in decision.alternatives)}")
    parts.append(f"Criteria: {', '.join(f'{c.name} ({c.weight:.0%})' for c in decision.criteria)}")

    for method, results in decision.rankings.items():
        sorted_r = sorted(results, key=lambda r: r.rank)
        ranking_str = ", ".join(f"#{r.rank} {r.alternative_name} ({r.score:.3f})" for r in sorted_r[:3])
        parts.append(f"{method.upper()} ranking: {ranking_str}")

    if decision.consistency_ratio is not None:
        parts.append(f"Consistency Ratio: {decision.consistency_ratio:.3f}")
    if decision.llm_summary:
        parts.append(f"Summary: {decision.llm_summary[:200]}")

    return "\n".join(parts)


def _post_to_brain(payload: dict) -> bool:
    """POST to the configured webhook. Returns True on success."""
    url = brain_url()
    if not url:
        return False
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=BRAIN_TIMEOUT) as resp:
            result = json.loads(resp.read())
            return bool(result.get("ok"))
    except Exception:
        return False
