"""LLM integration via llama-server (OpenAI-compatible API)."""

from __future__ import annotations

import json
import re

import httpx

from perfect_choice.config import Config
from perfect_choice.models import Criterion, RankingResult, Score


def parse_json_response(raw: str) -> dict | list | None:
    """Parse JSON from LLM response, stripping markdown fences."""
    # Try raw first
    raw = raw.strip()
    # Strip ```json ... ``` fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    # Find first { or [ to last } or ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = raw.find(start_char)
        end = raw.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


class LLMClient:
    """llama-server client with graceful fallback."""

    def __init__(self, config: Config, thinking: bool = True) -> None:
        self._url = config.llm_url.rstrip("/")
        self._model = config.llm_model
        self._timeout = config.llm_timeout
        self.thinking = thinking

    def is_available(self) -> bool:
        """Check if llama-server is responding."""
        try:
            resp = httpx.get(f"{self._url}/health", timeout=2.0)
            return resp.status_code == 200
        except (httpx.HTTPError, httpx.ConnectError, OSError):
            return False

    def _chat(
        self, system: str, user: str, temperature: float = 0.7,
        thinking: bool | None = None,
    ) -> str:
        """Send chat completion. Returns content string or empty on failure.

        *thinking*: override instance default. False sends
        ``chat_template_kwargs: {"enable_thinking": false}`` to llama-server
        (Qwen3.5), cutting response time from ~2 min to ~5 s.
        """
        use_thinking = thinking if thinking is not None else self.thinking
        try:
            payload: dict = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "stream": False,
            }
            if self._model:
                payload["model"] = self._model
            if not use_thinking:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            resp = httpx.post(
                f"{self._url}/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(10.0, read=self._timeout),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return ""

    def suggest_criteria(
        self, context: str, alternatives: list[str]
    ) -> list[dict]:
        """Suggest evaluation criteria based on decision context.

        Returns list of {"name": str, "description": str, "is_cost": bool}.
        """
        system = (
            "You are a decision analysis expert. Given a decision context and "
            "the available options, suggest 5-7 evaluation criteria. "
            "Return ONLY a JSON array of objects with keys: "
            '"name" (short label), "description" (one sentence), '
            '"is_cost" (true if lower is better, like price or commute time).'
        )
        user = (
            f"Decision: {context}\n"
            f"Options: {', '.join(alternatives)}\n\n"
            "Suggest evaluation criteria as a JSON array:"
        )
        raw = self._chat(system, user, temperature=0.4, thinking=False)
        if not raw:
            return []
        parsed = parse_json_response(raw)
        if isinstance(parsed, list):
            return [
                {
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                    "is_cost": bool(item.get("is_cost", False)),
                }
                for item in parsed
                if isinstance(item, dict) and item.get("name")
            ]
        return []

    def devils_advocate(
        self,
        decision_title: str,
        rankings: list[RankingResult],
        criteria: list[Criterion],
    ) -> str:
        """Argue for the #2 option. Returns natural language text."""
        if len(rankings) < 2:
            return ""
        winner = rankings[0]
        runner_up = rankings[1]
        criteria_text = ", ".join(
            f"{c.name} ({c.weight:.0%})" for c in criteria
        )
        system = (
            "You are a devil's advocate. Your job is to make a compelling "
            "argument for the second-place option in a decision analysis. "
            "Be persuasive but honest. Keep it under 150 words."
        )
        user = (
            f"Decision: {decision_title}\n"
            f"Winner: {winner.alternative_name} (score: {winner.score:.4f})\n"
            f"Runner-up: {runner_up.alternative_name} (score: {runner_up.score:.4f})\n"
            f"Criteria: {criteria_text}\n\n"
            f"Make the case for choosing {runner_up.alternative_name} instead:"
        )
        return self._chat(system, user, temperature=0.7)

    def detect_bias(
        self, criteria: list[Criterion], scores: list[Score]
    ) -> str:
        """Check for cognitive biases in the scoring.

        Detects: anchoring, confirmation, halo effect, range compression.
        """
        criteria_text = "\n".join(
            f"- {c.name}: weight={c.weight:.0%}, cost={'yes' if c.is_cost else 'no'}"
            for c in criteria
        )
        # Group scores by alternative
        by_alt: dict[str, list[str]] = {}
        for s in scores:
            by_alt.setdefault(s.alternative_name, []).append(
                f"{s.criterion_name}={s.value}"
            )
        scores_text = "\n".join(
            f"- {alt}: {', '.join(vals)}" for alt, vals in by_alt.items()
        )
        system = (
            "You are a cognitive bias analyst. Review decision scores for common biases:\n"
            "1. Anchoring: first criterion gets disproportionate weight\n"
            "2. Confirmation: all criteria favor same alternative\n"
            "3. Halo effect: one alternative scores high on everything\n"
            "4. Range compression: scores clustered in narrow band (e.g., all 6-8)\n\n"
            "If you detect bias, explain which type and why. "
            "If the scoring looks fair, say so. Keep it under 100 words."
        )
        user = f"Criteria:\n{criteria_text}\n\nScores:\n{scores_text}"
        return self._chat(system, user, temperature=0.3, thinking=False)

    def summarize_decision(
        self,
        title: str,
        rankings: dict[str, list[RankingResult]],
        criteria: list[Criterion],
        sensitivity_text: str = "",
    ) -> str:
        """Generate natural language summary of the analysis."""
        # Build method agreement summary
        methods_agree = True
        winners = set()
        ranking_lines = []
        for method, results in rankings.items():
            if results:
                winners.add(results[0].alternative_name)
                top3 = ", ".join(
                    f"{r.alternative_name} ({r.score:.3f})"
                    for r in results[:3]
                )
                ranking_lines.append(f"{method.upper()}: {top3}")
        if len(winners) > 1:
            methods_agree = False

        system = (
            "You are a decision analyst writing a clear, confident summary. "
            "State the recommendation, explain why based on the scoring, "
            "and note any caveats. Keep it under 200 words."
        )
        user = (
            f"Decision: {title}\n"
            f"Methods agree: {'yes' if methods_agree else 'no'}\n"
            f"Rankings:\n" + "\n".join(ranking_lines)
        )
        if sensitivity_text:
            user += f"\n\nSensitivity:\n{sensitivity_text}"
        return self._chat(system, user, temperature=0.5)
