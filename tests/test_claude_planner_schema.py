import json
from types import SimpleNamespace

import pytest

from ai.planner_models import AnalysisPlanResponse
from ai.prompts import SYSTEM_PROMPT
from ai.providers.claude_provider import ClaudeProvider


CANONICAL_KEYS = {
    "status",
    "reason",
    "clarification_question",
    "filters",
    "group_by",
    "metric",
    "aggregation",
    "sort",
    "sort_by",
    "limit",
    "time_granularity",
    "time_column",
    "visualization",
}

METADATA = {
    "columns": [
        {"name": "order_date", "role": "time"},
        {"name": "revenue", "role": "metric"},
    ]
}

MONTHLY_REVENUE_RESPONSE = {
    "status": "success",
    "reason": None,
    "clarification_question": None,
    "filters": [],
    "group_by": ["order_date"],
    "metric": "revenue",
    "aggregation": "sum",
    "sort": "asc",
    "sort_by": "time",
    "limit": None,
    "time_granularity": "month",
    "time_column": "order_date",
    "visualization": {
        "type": "line",
        "title": "Monthly Revenue Over Time",
    },
}

# The exact shape observed from Claude before the prompt
# declared the response contract.
NESTED_VALID_RESPONSE = {
    "status": "valid",
    "analysis": {
        "metric": "revenue",
        "aggregation": "sum",
        "group_by": ["order_date"],
        "time_granularity": "month",
        "sort_by": "time",
        "sort": "asc",
    },
    "visualization": {
        "type": "line",
        "title": "Monthly Revenue Over Time",
    },
}


class _FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))]
        )


def _provider_returning(monkeypatch, payload):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    provider = ClaudeProvider()
    provider.client = SimpleNamespace(messages=_FakeMessages(payload))
    return provider


def test_monthly_time_series_response_is_accepted(monkeypatch):
    provider = _provider_returning(monkeypatch, MONTHLY_REVENUE_RESPONSE)

    plan = provider.create_analysis_plan(
        "Show monthly revenue over time",
        METADATA,
    )

    assert isinstance(plan, AnalysisPlanResponse)
    assert plan.status == "success"
    assert plan.group_by == ["order_date"]
    assert plan.time_column == "order_date"
    assert plan.time_granularity == "month"
    assert plan.sort_by == "time"
    assert plan.sort == "asc"
    assert plan.visualization is not None
    assert plan.visualization.type == "line"
    assert plan.visualization.title == "Monthly Revenue Over Time"


def test_response_shape_is_canonical_and_flat(monkeypatch):
    provider = _provider_returning(monkeypatch, MONTHLY_REVENUE_RESPONSE)

    plan = provider.create_analysis_plan(
        "Show monthly revenue over time",
        METADATA,
    )

    dumped = plan.model_dump()

    assert set(dumped) == CANONICAL_KEYS
    assert set(AnalysisPlanResponse.model_fields) == CANONICAL_KEYS
    assert "analysis" not in dumped
    assert set(dumped["visualization"]) == {"type", "title"}


def test_prompt_declares_canonical_contract():
    for key in CANONICAL_KEYS:
        assert f'"{key}"' in SYSTEM_PROMPT

    assert '"success" | "clarification" | "invalid"' in SYSTEM_PROMPT
    assert '"valid"' in SYSTEM_PROMPT  # explicitly forbidden
    assert '"analysis"' in SYSTEM_PROMPT  # wrapper explicitly forbidden


def test_prompt_is_sent_as_system_prompt(monkeypatch):
    provider = _provider_returning(monkeypatch, MONTHLY_REVENUE_RESPONSE)

    provider.create_analysis_plan("Show monthly revenue over time", METADATA)

    (call,) = provider.client.messages.calls
    assert call["system"][0]["text"] == SYSTEM_PROMPT


def test_nested_valid_response_is_rejected(monkeypatch):
    provider = _provider_returning(monkeypatch, NESTED_VALID_RESPONSE)

    with pytest.raises(ValueError, match="does not match the expected planner schema"):
        provider.create_analysis_plan(
            "Show monthly revenue over time",
            METADATA,
        )


def test_time_granularity_without_time_column_is_rejected(monkeypatch):
    payload = {**MONTHLY_REVENUE_RESPONSE, "time_column": None}
    provider = _provider_returning(monkeypatch, payload)

    with pytest.raises(ValueError, match="time_granularity without time_column"):
        provider.create_analysis_plan(
            "Show monthly revenue over time",
            METADATA,
        )
