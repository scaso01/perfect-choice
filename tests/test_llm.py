"""Tests for LLM integration layer."""

from __future__ import annotations

import json

import httpx
import pytest

from perfect_choice.config import Config
from perfect_choice.llm import LLMClient, parse_json_response
from perfect_choice.models import Criterion, RankingResult, Score, ScoreMethod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> LLMClient:
    """Create an LLMClient with a fake URL (all calls will be mocked)."""
    cfg = Config(llm_url="http://fake:8080", no_llm=False)
    return LLMClient(cfg)


def _sample_rankings() -> list[RankingResult]:
    return [
        RankingResult(
            alternative_name="Option A",
            score=0.65,
            rank=1,
            method=ScoreMethod.WSM,
        ),
        RankingResult(
            alternative_name="Option B",
            score=0.55,
            rank=2,
            method=ScoreMethod.WSM,
        ),
        RankingResult(
            alternative_name="Option C",
            score=0.40,
            rank=3,
            method=ScoreMethod.WSM,
        ),
    ]


def _sample_criteria() -> list[Criterion]:
    return [
        Criterion(name="Cost", weight=0.4, is_cost=True),
        Criterion(name="Quality", weight=0.35),
        Criterion(name="Speed", weight=0.25),
    ]


def _sample_scores() -> list[Score]:
    return [
        Score(alternative_name="Option A", criterion_name="Cost", value=7.0),
        Score(alternative_name="Option A", criterion_name="Quality", value=8.0),
        Score(alternative_name="Option B", criterion_name="Cost", value=5.0),
        Score(alternative_name="Option B", criterion_name="Quality", value=6.0),
    ]


# ===========================================================================
# parse_json_response tests
# ===========================================================================


class TestParseJsonResponse:
    """Tests for the JSON extraction helper."""

    def test_plain_json_object(self) -> None:
        raw = '{"name": "Price", "is_cost": true}'
        result = parse_json_response(raw)
        assert result == {"name": "Price", "is_cost": True}

    def test_json_with_markdown_fences(self) -> None:
        raw = '```json\n{"key": "value"}\n```'
        result = parse_json_response(raw)
        assert result == {"key": "value"}

    def test_json_array(self) -> None:
        raw = '[{"name": "A"}, {"name": "B"}]'
        result = parse_json_response(raw)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "A"

    def test_garbage_with_embedded_json(self) -> None:
        raw = 'Sure! Here is the JSON:\n\n{"answer": 42}\n\nHope that helps!'
        result = parse_json_response(raw)
        assert result == {"answer": 42}

    def test_no_json_returns_none(self) -> None:
        raw = "I have no idea what you're asking."
        result = parse_json_response(raw)
        assert result is None

    def test_invalid_json_returns_none(self) -> None:
        raw = "{not: valid json, missing quotes}"
        result = parse_json_response(raw)
        assert result is None


# ===========================================================================
# LLMClient.is_available tests
# ===========================================================================


class TestIsAvailable:
    """Tests for health-check endpoint."""

    def test_available_when_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()

        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, text="ok")

        monkeypatch.setattr(httpx, "get", fake_get)
        assert client.is_available() is True

    def test_unavailable_on_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()

        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "get", fake_get)
        assert client.is_available() is False

    def test_unavailable_on_non_200(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()

        def fake_get(url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(503, text="loading")

        monkeypatch.setattr(httpx, "get", fake_get)
        assert client.is_available() is False


# ===========================================================================
# LLMClient.suggest_criteria tests
# ===========================================================================


class TestSuggestCriteria:
    """Tests for criteria suggestion."""

    def test_returns_parsed_criteria(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        criteria_json = json.dumps(
            [
                {
                    "name": "Price",
                    "description": "Total cost of ownership",
                    "is_cost": True,
                },
                {
                    "name": "Quality",
                    "description": "Build quality and durability",
                    "is_cost": False,
                },
            ]
        )
        monkeypatch.setattr(client, "_chat", lambda *a, **kw: criteria_json)

        result = client.suggest_criteria("Buy a laptop", ["MacBook", "ThinkPad"])
        assert len(result) == 2
        assert result[0]["name"] == "Price"
        assert result[0]["is_cost"] is True
        assert result[1]["name"] == "Quality"

    def test_returns_empty_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        monkeypatch.setattr(client, "_chat", lambda *a, **kw: "")

        result = client.suggest_criteria("Buy a car", ["Tesla", "Toyota"])
        assert result == []

    def test_returns_empty_on_garbage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        monkeypatch.setattr(
            client, "_chat", lambda *a, **kw: "I can't help with that."
        )

        result = client.suggest_criteria("something", ["a", "b"])
        assert result == []

    def test_filters_items_without_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        data = json.dumps(
            [
                {"name": "Valid", "description": "ok", "is_cost": False},
                {"description": "missing name", "is_cost": False},
                {"name": "", "description": "empty name", "is_cost": False},
            ]
        )
        monkeypatch.setattr(client, "_chat", lambda *a, **kw: data)

        result = client.suggest_criteria("test", ["x", "y"])
        assert len(result) == 1
        assert result[0]["name"] == "Valid"


# ===========================================================================
# LLMClient.devils_advocate tests
# ===========================================================================


class TestDevilsAdvocate:
    """Tests for devil's advocate argument."""

    def test_returns_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        monkeypatch.setattr(
            client,
            "_chat",
            lambda *a, **kw: "Option B has superior long-term value.",
        )

        result = client.devils_advocate(
            "Laptop choice", _sample_rankings(), _sample_criteria()
        )
        assert "Option B" in result

    def test_returns_empty_with_fewer_than_two_rankings(self) -> None:
        client = _make_client()
        single = [_sample_rankings()[0]]
        result = client.devils_advocate("Test", single, _sample_criteria())
        assert result == ""

    def test_returns_empty_with_empty_rankings(self) -> None:
        client = _make_client()
        result = client.devils_advocate("Test", [], _sample_criteria())
        assert result == ""


# ===========================================================================
# LLMClient.detect_bias tests
# ===========================================================================


class TestDetectBias:
    """Tests for bias detection."""

    def test_returns_analysis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        monkeypatch.setattr(
            client,
            "_chat",
            lambda *a, **kw: "Range compression detected: scores cluster 5-8.",
        )

        result = client.detect_bias(_sample_criteria(), _sample_scores())
        assert "compression" in result.lower()

    def test_returns_empty_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        monkeypatch.setattr(client, "_chat", lambda *a, **kw: "")

        result = client.detect_bias(_sample_criteria(), _sample_scores())
        assert result == ""


# ===========================================================================
# LLMClient.summarize_decision tests
# ===========================================================================


class TestSummarizeDecision:
    """Tests for decision summary generation."""

    def test_returns_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        monkeypatch.setattr(
            client,
            "_chat",
            lambda *a, **kw: "Option A is the clear winner across all methods.",
        )

        rankings = {"wsm": _sample_rankings()}
        result = client.summarize_decision(
            "Laptop choice", rankings, _sample_criteria()
        )
        assert "Option A" in result

    def test_handles_disagreeing_methods(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()

        captured_args: list[str] = []

        def capture_chat(system: str, user: str, **kw: object) -> str:
            captured_args.append(user)
            return "Methods disagree."

        monkeypatch.setattr(client, "_chat", capture_chat)

        # WSM says A wins, TOPSIS says B wins
        wsm_rankings = _sample_rankings()
        topsis_rankings = [
            RankingResult("Option B", 0.70, 1, ScoreMethod.TOPSIS),
            RankingResult("Option A", 0.60, 2, ScoreMethod.TOPSIS),
        ]
        rankings = {"wsm": wsm_rankings, "topsis": topsis_rankings}

        result = client.summarize_decision(
            "Test", rankings, _sample_criteria()
        )
        assert result == "Methods disagree."
        # Verify the prompt mentions methods don't agree
        assert "Methods agree: no" in captured_args[0]

    def test_includes_sensitivity_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()

        captured_args: list[str] = []

        def capture_chat(system: str, user: str, **kw: object) -> str:
            captured_args.append(user)
            return "Summary with sensitivity."

        monkeypatch.setattr(client, "_chat", capture_chat)

        rankings = {"wsm": _sample_rankings()}
        client.summarize_decision(
            "Test",
            rankings,
            _sample_criteria(),
            sensitivity_text="Cost weight is critical.",
        )
        assert "Sensitivity" in captured_args[0]
        assert "Cost weight is critical" in captured_args[0]

    def test_returns_empty_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client()
        monkeypatch.setattr(client, "_chat", lambda *a, **kw: "")

        result = client.summarize_decision(
            "Test", {"wsm": _sample_rankings()}, _sample_criteria()
        )
        assert result == ""
