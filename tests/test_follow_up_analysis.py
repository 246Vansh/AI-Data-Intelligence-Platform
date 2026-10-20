"""Step 96: bounded follow-up questions on /api/analyze.

Unit tests pin ai.follow_up's two supported edits and its refusals;
route tests pin the analysis_context contract (strict, bounded, same
dataset, re-validated), the follow-up/fresh-plan decision, and dataset
isolation. Planners are stubbed: no test can reach an LLM.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
from ai.follow_up import references_previous, resolve_follow_up
from backend.dependencies import DEV_USER_ID_ENV_VAR
from backend.main import app
from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.storage.duckdb_storage import DuckDBStorage

METADATA = {
    "columns": {
        "order_date": {"role": "time"},
        "region": {"role": "dimension"},
        "product": {"role": "dimension"},
        "quantity": {"role": "metric"},
        "amount": {"role": "metric"},
    }
}

MONTHLY = AnalysisPlan(
    metric="quantity",
    aggregation="sum",
    group_by=["order_date"],
    time_column="order_date",
    time_granularity="month",
    sort="asc",
    sort_by="time",
)

TOP_5 = AnalysisPlan(metric="amount", aggregation="sum", group_by=["product"], limit=5)


# =========================================================
# Resolver: supported edits
# =========================================================


def test_break_down_adds_grouping_and_keeps_metric_aggregation_and_time():
    follow_up = resolve_follow_up("Break that down by region.", MONTHLY, METADATA)

    plan = follow_up.plan
    assert plan.group_by == ["order_date", "region"]
    assert (plan.metric, plan.aggregation) == ("quantity", "sum")
    assert (plan.time_column, plan.time_granularity) == ("order_date", "month")
    assert (plan.sort, plan.sort_by) == ("asc", "time")
    assert follow_up.change == "added region to the grouping"


def test_bottom_10_instead_replaces_limit_and_direction():
    follow_up = resolve_follow_up("Make it the bottom 10 instead", TOP_5, METADATA)

    plan = follow_up.plan
    assert (plan.limit, plan.sort, plan.sort_by) == (10, "asc", "metric")
    assert (plan.metric, plan.aggregation, plan.group_by) == ("amount", "sum", ["product"])
    assert follow_up.change == "changed to the bottom 10 groups"


def test_by_column_instead_replaces_grouping_and_drops_unrelated_time_settings():
    follow_up = resolve_follow_up("by region instead", MONTHLY, METADATA)

    plan = follow_up.plan
    assert plan.group_by == ["region"]
    assert (plan.time_column, plan.time_granularity, plan.sort_by) == (None, None, "metric")


def test_filters_are_carried_over_and_previous_plan_is_not_mutated():
    previous = AnalysisPlan(
        metric="amount",
        aggregation="sum",
        group_by=["product"],
        filters=[FilterCondition("region", "=", "north")],
    )

    plan = resolve_follow_up("break that down by region", previous, METADATA).plan
    plan.filters.append(FilterCondition("x", "=", 1))

    assert [f.column for f in previous.filters] == ["region"]
    assert previous.group_by == ["product"]


# =========================================================
# Resolver: refusals (never half-applied)
# =========================================================


@pytest.mark.parametrize(
    "question, previous",
    [
        ("break that down by quantity", MONTHLY),  # a metric, not a dimension
        ("break that down by city", MONTHLY),  # not in this dataset
        ("break that down by region and month", MONTHLY),  # says more than one edit
        ("break that down by region", TOP_5),  # top-5 per region combo: ambiguous
        ("break that down by order_date", MONTHLY),  # already grouped by it
        ("group by region", MONTHLY),  # neither "instead" nor "break down"
        ("top 5 regions by quantity", MONTHLY),  # a complete new question
        ("bottom 10 in 2023", TOP_5),  # extra condition
        ("top 3", AnalysisPlan(metric="amount", aggregation="sum")),  # nothing to rank
        ("make it better", TOP_5),
        ("what about last year?", TOP_5),
    ],
)
def test_unsupported_or_ambiguous_follow_ups_are_refused(question, previous):
    assert resolve_follow_up(question, previous, METADATA) is None


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Make it the bottom 10 instead", True),
        ("break that down by region", True),
        ("what about the north?", True),
        ("total amount for orders that shipped", False),
        ("average quantity by product", False),
    ],
)
def test_references_previous(question, expected):
    assert references_previous(question) is expected


# =========================================================
# Route fixtures
# =========================================================


def _sales_df():
    return pd.DataFrame(
        {
            "order_date": pd.to_datetime(
                ["2024-01-05", "2024-01-20", "2024-02-03", "2024-03-09", "2024-03-15"]
            ),
            "region": ["north", "south", "north", "east", "south"],
            "product": ["a", "b", "a", "c", "b"],
            "quantity": [1, 2, 3, 4, 5],
            "amount": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )


def _shop_df():
    return pd.DataFrame({"city": ["x", "y", "x"], "price": [1.0, 2.0, 3.0]})


@pytest.fixture
def env(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)

    fresh_plans: dict[str, AnalysisPlan] = {}
    ai_calls: list[str] = []

    class _StubFastPlanner:
        def create_plan(self, question, metadata):
            return fresh_plans.get(question)

    def _ai_planner(user_question, metadata):
        ai_calls.append(user_question)
        raise RuntimeError("AI planner must not be called in these tests")

    monkeypatch.setattr(analysis_route, "FastPlanner", _StubFastPlanner)
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _ai_planner)

    storages = []

    def register(df, owner_id="dev-user"):
        storage = DuckDBStorage(df)
        storages.append(storage)
        dataset = Dataset(storage=storage, owner_id=owner_id)
        registry.register(dataset)
        return dataset

    yield {"register": register, "fresh_plans": fresh_plans, "ai_calls": ai_calls}

    manager.shutdown(wait=True)
    for storage in storages:
        storage.close()


def _plan_payload(plan: AnalysisPlan) -> dict:
    return {
        "filters": [
            {"column": f.column, "operator": f.operator, "value": f.value} for f in plan.filters
        ],
        "group_by": list(plan.group_by),
        "metric": plan.metric,
        "aggregation": plan.aggregation,
        "sort": plan.sort,
        "sort_by": plan.sort_by,
        "limit": plan.limit,
        "visualization": plan.visualization,
        "time_column": plan.time_column,
        "time_granularity": plan.time_granularity,
    }


def _context(dataset_id, plan):
    return {"dataset_id": dataset_id, "previous_plan": _plan_payload(plan)}


def _post(dataset_id, question, context=None):
    body = {"dataset_id": dataset_id, "question": question}
    if context is not None:
        body["analysis_context"] = context
    return TestClient(app).post("/api/analyze", json=body)


# =========================================================
# Route: compatibility and follow-up behavior
# =========================================================


def test_request_without_context_is_unchanged(env):
    dataset = env["register"](_sales_df())
    env["fresh_plans"]["total amount by product"] = AnalysisPlan(
        metric="amount", aggregation="sum", group_by=["product"]
    )

    body = _post(dataset.dataset_id, "total amount by product").json()

    assert body["planner"] == {"type": "fast", "fallback": False}
    assert body["plan"]["group_by"] == ["product"]
    assert not body["plan_explanation"]["steps"][0].startswith("Follow-up")


def test_break_that_down_by_region(env):
    dataset = env["register"](_sales_df())

    response = _post(
        dataset.dataset_id, "Break that down by region", _context(dataset.dataset_id, MONTHLY)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planner"] == {"type": "follow_up", "fallback": False}
    assert body["plan"]["group_by"] == ["order_date", "region"]
    assert (body["plan"]["metric"], body["plan"]["aggregation"]) == ("quantity", "sum")
    assert body["plan"]["time_granularity"] == "month"
    assert "region" in body["data"]["columns"]
    assert body["plan_explanation"]["interpreted_by"] == "follow-up"
    assert body["plan_explanation"]["steps"][0] == (
        "Follow-up to the previous analysis: added region to the grouping."
    )
    assert env["ai_calls"] == []


def test_make_it_the_bottom_10_instead(env):
    dataset = env["register"](_sales_df())

    body = _post(
        dataset.dataset_id, "Make it the bottom 10 instead", _context(dataset.dataset_id, TOP_5)
    ).json()

    assert (body["plan"]["limit"], body["plan"]["sort"]) == (10, "asc")
    assert body["plan"]["group_by"] == ["product"]
    assert env["ai_calls"] == []


def test_complete_independent_question_gets_a_fresh_plan(env):
    dataset = env["register"](_sales_df())
    previous = AnalysisPlan(
        metric="amount",
        aggregation="sum",
        group_by=["product"],
        filters=[FilterCondition("region", "=", "north")],
    )
    env["fresh_plans"]["average quantity by region"] = AnalysisPlan(
        metric="quantity", aggregation="mean", group_by=["region"]
    )

    body = _post(
        dataset.dataset_id, "average quantity by region", _context(dataset.dataset_id, previous)
    ).json()

    assert body["planner"]["type"] == "fast"
    # Nothing inherited from the previous plan.
    assert body["plan"]["filters"] == []
    assert (body["plan"]["metric"], body["plan"]["aggregation"]) == ("quantity", "mean")


@pytest.mark.parametrize(
    "question, previous",
    [
        ("what about last year?", TOP_5),
        ("make it better", TOP_5),
        ("break that down by region", TOP_5),  # ambiguous with a top-5 limit
    ],
)
def test_unapplicable_follow_up_is_refused_without_inventing_a_plan(env, question, previous):
    dataset = env["register"](_sales_df())

    response = _post(dataset.dataset_id, question, _context(dataset.dataset_id, previous))

    assert response.status_code == 422
    assert "follow-up" in response.json()["detail"]
    assert env["ai_calls"] == []


# =========================================================
# Route: context contract validation
# =========================================================


def _valid_context(dataset_id):
    return _context(dataset_id, TOP_5)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(extra_field=1),
        lambda c: c["previous_plan"].update(rows=[{"a": 1}]),
        lambda c: c.pop("previous_plan"),
        lambda c: c["previous_plan"].pop("metric"),
        lambda c: c["previous_plan"].update(group_by=[f"g{i}" for i in range(11)]),
        lambda c: c["previous_plan"].update(metric="m" * 201),
        lambda c: c["previous_plan"].update(limit=0),
        lambda c: c["previous_plan"].update(
            filters=[{"column": "region", "operator": "LIKE", "value": "n%"}]
        ),
        lambda c: c["previous_plan"].update(
            filters=[{"column": "region", "operator": "=", "value": {"nested": 1}}]
        ),
        lambda c: c["previous_plan"].update(
            filters=[{"column": "region", "operator": "=", "value": "v" * 501}]
        ),
        lambda c: c["previous_plan"].update(
            filters=[{"column": "region", "operator": "=", "value": "n"}] * 21
        ),
        lambda c: c.update(dataset_id=""),
    ],
)
def test_malformed_or_oversized_context_is_rejected(env, mutate):
    dataset = env["register"](_sales_df())
    context = _valid_context(dataset.dataset_id)
    mutate(context)

    response = _post(dataset.dataset_id, "Make it the bottom 10 instead", context)

    assert response.status_code == 422
    assert env["ai_calls"] == []


def test_context_cannot_bypass_plan_validation(env):
    dataset = env["register"](_sales_df())
    unknown_column = AnalysisPlan(metric="no_such_column", aggregation="sum", group_by=["product"])
    unknown_aggregation = AnalysisPlan(metric="amount", aggregation="stddev", group_by=["product"])

    for plan in (unknown_column, unknown_aggregation):
        response = _post(
            dataset.dataset_id, "Make it the bottom 10 instead", _context(dataset.dataset_id, plan)
        )

        assert response.status_code == 400
        assert response.json()["detail"].startswith("Invalid analysis_context:")


# =========================================================
# Route: authorization and dataset isolation
# =========================================================


def test_context_for_another_dataset_is_rejected(env):
    sales = env["register"](_sales_df())
    shop = env["register"](_shop_df())

    response = _post(
        shop.dataset_id, "Make it the bottom 10 instead", _context(sales.dataset_id, TOP_5)
    )

    assert response.status_code == 400
    assert "different dataset" in response.json()["detail"]


def test_unknown_and_foreign_datasets_still_404_with_context(env, monkeypatch):
    sales = env["register"](_sales_df(), owner_id="alice")
    missing_id = "00000000-0000-0000-0000-000000000000"

    missing = _post(missing_id, "bottom 10", _context(missing_id, TOP_5))
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "mallory")
    foreign = _post(sales.dataset_id, "bottom 10", _context(sales.dataset_id, TOP_5))

    assert missing.status_code == 404
    assert foreign.status_code == 404


def test_context_naming_the_other_datasets_columns_is_rejected(env):
    env["register"](_sales_df())
    shop = env["register"](_shop_df())

    # A plan over the sales columns, relabelled with the shop dataset id.
    response = _post(
        shop.dataset_id, "Make it the bottom 10 instead", _context(shop.dataset_id, TOP_5)
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Invalid analysis_context:")


def test_follow_up_cannot_reach_the_other_datasets_columns(env):
    sales = env["register"](_sales_df())
    env["register"](_shop_df())

    # "city" exists only in the shop dataset.
    response = _post(
        sales.dataset_id, "break that down by city", _context(sales.dataset_id, MONTHLY)
    )

    assert response.status_code == 422
    assert env["ai_calls"] == []


def test_follow_up_plan_is_validated_against_the_requested_dataset(env):
    env["register"](_sales_df())
    shop = env["register"](_shop_df())
    previous = AnalysisPlan(metric="price", aggregation="sum", group_by=["city"], limit=2)

    body = _post(
        shop.dataset_id, "Make it the bottom 1 instead", _context(shop.dataset_id, previous)
    ).json()

    assert body["plan"]["group_by"] == ["city"]
    assert (body["plan"]["limit"], body["plan"]["sort"]) == (1, "asc")
    assert set(body["data"]["columns"]) == {"city", "sum_price"}
