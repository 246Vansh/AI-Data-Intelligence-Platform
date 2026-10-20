"""Step 95: deterministic "How this was calculated" explanation.

Unit tests pin every sentence data_engine.plan_explanation.explain_plan
can produce against the plan semantics the engines actually implement;
route tests pin how /api/analyze attaches it without changing any
existing field or error behavior.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
from ai.adapter import AnalysisClarificationError
from backend.dependencies import DEV_USER_ID_ENV_VAR
from backend.main import app
from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.plan_explanation import explain_plan
from data_engine.storage.duckdb_storage import DuckDBStorage


def _explain(plan, *, planner_type="fast", row_limit=None, row_limit_reached=False):
    return explain_plan(
        plan,
        planner_type=planner_type,
        row_limit=row_limit,
        row_limit_reached=row_limit_reached,
    )


def _all_text(explanation) -> str:
    return " ".join(explanation["steps"] + explanation["limitations"])


# =========================================================
# Aggregations
# =========================================================


@pytest.mark.parametrize(
    "aggregation, expected",
    [
        ("sum", "Sum of Total_Amount for each Product_ID."),
        ("mean", "Average (mean) of Total_Amount for each Product_ID."),
        ("median", "Median of Total_Amount for each Product_ID."),
        ("min", "Minimum of Total_Amount for each Product_ID."),
        ("max", "Maximum of Total_Amount for each Product_ID."),
        ("count", "Number of non-empty Total_Amount values for each Product_ID."),
    ],
)
def test_every_aggregation_is_described(aggregation, expected):
    plan = AnalysisPlan(metric="Total_Amount", aggregation=aggregation, group_by=["Product_ID"])

    assert _explain(plan)["steps"][0] == expected


def test_count_describes_non_null_values_not_rows():
    plan = AnalysisPlan(metric="Rating", aggregation="count")

    first = _explain(plan)["steps"][0]

    assert first.startswith("Number of non-empty Rating values")
    assert "rows" not in first.lower()


def test_unknown_aggregation_is_refused_not_guessed():
    with pytest.raises(ValueError):
        _explain(AnalysisPlan(metric="x", aggregation="stddev"))


# =========================================================
# Grouping
# =========================================================


def test_no_grouping_is_a_single_value_without_sort_or_limit():
    explanation = _explain(AnalysisPlan(metric="Total_Amount", aggregation="sum", limit=5))

    assert explanation["steps"] == [
        "Sum of Total_Amount, calculated as a single value (no grouping).",
        "No filters were applied.",
    ]
    assert explanation["limitations"] == []


def test_two_and_three_grouping_columns():
    two = AnalysisPlan(metric="m", aggregation="sum", group_by=["Region", "City"])
    three = AnalysisPlan(metric="m", aggregation="sum", group_by=["Region", "City", "Store"])

    assert _explain(two)["steps"][0] == "Sum of m for each combination of Region and City."
    assert (
        _explain(three)["steps"][0]
        == "Sum of m for each combination of Region, City, and Store."
    )


# =========================================================
# Filters
# =========================================================


@pytest.mark.parametrize(
    "operator, value, expected",
    [
        ("=", "North", 'Region equals "North"'),
        (">", 100, "Region is greater than 100"),
        (">=", 100.5, "Region is greater than or equal to 100.5"),
        ("<", 0, "Region is less than 0"),
        ("<=", -3, "Region is less than or equal to -3"),
        ("=", True, "Region equals true"),
    ],
)
def test_every_filter_operator(operator, value, expected):
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        filters=[FilterCondition("Region", operator, value)],
    )

    assert _explain(plan)["steps"][1] == f"Only rows where {expected} were included."


def test_multiple_filters_are_all_required():
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        filters=[
            FilterCondition("Region", "=", "North"),
            FilterCondition("Amount", ">", 10),
        ],
    )

    assert _explain(plan)["steps"][1] == (
        "Only rows matching all of these conditions were included: "
        'Region equals "North"; Amount is greater than 10.'
    )


def test_not_equal_filter_is_stated_without_null_semantics():
    # DuckDB drops NULLs for `col != ?`, the pandas executor keeps NaN
    # rows - the wording must not claim either behavior.
    plan = AnalysisPlan(
        metric="m", aggregation="sum", filters=[FilterCondition("Region", "!=", "North")]
    )

    step = _explain(plan)["steps"][1]

    assert step == 'Filter condition: Region != "North".'
    assert "included" not in step and "empty" not in step


def test_not_equal_among_other_filters_states_every_condition_neutrally():
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        filters=[
            FilterCondition("Region", "!=", "North"),
            FilterCondition("Amount", ">=", 10),
        ],
    )

    assert _explain(plan)["steps"][1] == (
        'Filter conditions (all must hold): Region != "North"; Amount >= 10.'
    )


def test_unknown_filter_operator_is_refused():
    plan = AnalysisPlan(metric="m", aggregation="sum", filters=[FilterCondition("a", "LIKE", "x")])

    with pytest.raises(ValueError):
        _explain(plan)


def test_quotes_and_html_like_values_stay_literal_text():
    value = '<script>alert("x")</script> & \'q\''
    plan = AnalysisPlan(
        metric="<b>m</b>",
        aggregation="sum",
        group_by=["<i>Region</i>"],
        filters=[FilterCondition("<i>Region</i>", "=", value)],
    )

    explanation = _explain(plan)

    assert explanation["steps"][0] == "Sum of <b>m</b> for each <i>Region</i>."
    # JSON literal: inner double quotes escaped, nothing HTML-escaped.
    assert explanation["steps"][1] == (
        'Only rows where <i>Region</i> equals '
        '"<script>alert(\\"x\\")</script> & \'q\'" were included.'
    )
    assert "&lt;" not in _all_text(explanation)


def test_never_claims_all_rows_were_included():
    plans = [
        AnalysisPlan(metric="m", aggregation="sum"),
        AnalysisPlan(metric="m", aggregation="sum", filters=[FilterCondition("a", "=", 1)]),
        AnalysisPlan(
            metric="m", aggregation="sum", group_by=["d"], time_column="d", time_granularity="month"
        ),
    ]

    for plan in plans:
        assert "all rows" not in _all_text(_explain(plan)).lower()


# =========================================================
# Sorting
# =========================================================


@pytest.mark.parametrize(
    "aggregation, sort, expected",
    [
        ("sum", "desc", "Sorted by the calculated sum, highest first."),
        ("sum", "asc", "Sorted by the calculated sum, lowest first."),
        ("mean", "desc", "Sorted by the calculated average, highest first."),
        ("count", "asc", "Sorted by the calculated count, lowest first."),
    ],
)
def test_metric_sort(aggregation, sort, expected):
    plan = AnalysisPlan(metric="m", aggregation=aggregation, group_by=["g"], sort=sort)

    assert expected in _explain(plan)["steps"]


@pytest.mark.parametrize("sort, expected", [("asc", "earliest"), ("desc", "latest")])
def test_time_sort(sort, expected):
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        group_by=["Order_Date"],
        time_column="Order_Date",
        time_granularity="month",
        sort=sort,
        sort_by="time",
    )

    assert f"Sorted by Order_Date, {expected} first." in _explain(plan)["steps"]


# =========================================================
# Time granularity
# =========================================================


@pytest.mark.parametrize(
    "granularity, label, plural",
    [
        ("day", "day", "days"),
        ("week", "week", "weeks starting on Monday"),
        ("month", "month", "months"),
        ("quarter", "quarter", "quarters"),
        ("year", "year", "years"),
    ],
)
def test_each_time_granularity(granularity, label, plural):
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        group_by=["Order_Date"],
        time_column="Order_Date",
        time_granularity=granularity,
    )

    explanation = _explain(plan)

    assert explanation["steps"][0] == f"Sum of m for each {label} of Order_Date."
    assert f"Dates in Order_Date were grouped into {plural}." in explanation["steps"]
    assert explanation["limitations"] == [
        "Rows where Order_Date is empty or could not be read as a date were excluded."
    ]


def test_date_exclusion_stated_even_when_time_column_is_not_grouped():
    # Both engines rebuild and null-filter the time column whenever a
    # granularity is set, grouped on or not.
    plan = AnalysisPlan(
        metric="m", aggregation="sum", group_by=["Region"], time_column="d", time_granularity="year"
    )

    explanation = _explain(plan)

    assert not any(step.startswith("Dates in") for step in explanation["steps"])
    assert explanation["limitations"] == [
        "Rows where d is empty or could not be read as a date were excluded."
    ]


def test_unknown_granularity_is_refused():
    plan = AnalysisPlan(metric="m", aggregation="sum", time_column="d", time_granularity="hour")

    with pytest.raises(ValueError):
        _explain(plan)


# =========================================================
# Limits
# =========================================================


@pytest.mark.parametrize(
    "sort, sort_by, expected",
    [
        ("desc", "metric", "Limited to the top 5 groups."),
        ("asc", "metric", "Limited to the bottom 5 groups."),
        ("asc", "time", "Limited to the first 5 groups in this order."),
    ],
)
def test_explicit_limit(sort, sort_by, expected):
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        group_by=["d"],
        time_column="d" if sort_by == "time" else None,
        time_granularity="month" if sort_by == "time" else None,
        sort=sort,
        sort_by=sort_by,
        limit=5,
    )

    assert expected in _explain(plan, row_limit=5)["steps"]


def test_limit_wording_never_claims_that_many_groups_exist():
    plan = AnalysisPlan(metric="m", aggregation="sum", group_by=["g"], limit=25_000)

    steps = _explain(plan, row_limit=25_000)["steps"]

    assert "Limited to the top 25,000 groups." in steps
    assert not any(step.startswith("Showing") for step in steps)


def test_descending_time_sort_with_limit():
    plan = AnalysisPlan(
        metric="m",
        aggregation="sum",
        group_by=["Order_Date"],
        time_column="Order_Date",
        time_granularity="month",
        sort="desc",
        sort_by="time",
        limit=3,
    )

    explanation = _explain(plan, row_limit=3, row_limit_reached=True)

    assert explanation["steps"][-2:] == [
        "Sorted by Order_Date, latest first.",
        "Limited to the first 3 groups in this order.",
    ]
    assert explanation["limitations"] == [
        "Rows where Order_Date is empty or could not be read as a date were excluded.",
        "The result reached the requested limit of 3 groups, so more groups may exist.",
    ]


def test_global_aggregate_with_time_granularity_still_states_date_exclusion():
    # No grouping, so no sort/limit lines - but both engines still drop
    # rows whose time value cannot be parsed before aggregating.
    plan = AnalysisPlan(
        metric="m", aggregation="sum", time_column="Order_Date", time_granularity="month"
    )

    explanation = _explain(plan)

    assert explanation["steps"] == [
        "Sum of m, calculated as a single value (no grouping).",
        "No filters were applied.",
    ]
    assert explanation["limitations"] == [
        "Rows where Order_Date is empty or could not be read as a date were excluded."
    ]


def test_limit_warning_only_from_execution_metadata():
    plan = AnalysisPlan(metric="m", aggregation="sum", group_by=["g"], limit=5)

    not_reached = _explain(plan, row_limit=5, row_limit_reached=False)
    reached = _explain(plan, row_limit=5, row_limit_reached=True)

    assert not_reached["limitations"] == []
    assert reached["limitations"] == [
        "The result reached the requested limit of 5 groups, so more groups may exist."
    ]


def test_default_cap_mentioned_only_when_reached():
    plan = AnalysisPlan(metric="m", aggregation="sum", group_by=["g"])

    assert _explain(plan, row_limit=10_000)["limitations"] == []
    assert not any("10,000" in step for step in _explain(plan, row_limit=10_000)["steps"])
    assert _explain(plan, row_limit=10_000, row_limit_reached=True)["limitations"] == [
        "The result reached the default cap of 10,000 groups, so more groups may exist."
    ]


def test_example_from_the_feature_request():
    plan = AnalysisPlan(
        metric="Total_Amount", aggregation="sum", group_by=["Product_ID"], limit=5
    )

    explanation = _explain(plan, row_limit=5, row_limit_reached=True)

    assert explanation == {
        "interpreted_by": "rule-based",
        "steps": [
            "Sum of Total_Amount for each Product_ID.",
            "No filters were applied.",
            "Sorted by the calculated sum, highest first.",
            "Limited to the top 5 groups.",
        ],
        "limitations": [
            "The result reached the requested limit of 5 groups, so more groups may exist."
        ],
    }


@pytest.mark.parametrize("planner_type, label", [("fast", "rule-based"), ("ai", "ai"), (None, "unknown")])
def test_planner_label(planner_type, label):
    plan = AnalysisPlan(metric="m", aggregation="sum")

    assert _explain(plan, planner_type=planner_type)["interpreted_by"] == label


# =========================================================
# /api/analyze
# =========================================================

EXISTING_RESPONSE_KEYS = {
    "success",
    "question",
    "planner",
    "data",
    "insights",
    "insight_status",
    "insight_source",
    "insight_error",
    "visualization",
    "plan",
    "performance",
}


@pytest.fixture
def route(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)

    storages = []

    def register(df, owner_id="dev-user"):
        storage = DuckDBStorage(df)
        storages.append(storage)
        dataset = Dataset(storage=storage, owner_id=owner_id)
        registry.register(dataset)
        return dataset

    yield register

    manager.shutdown(wait=True)
    for storage in storages:
        storage.close()


def _post(dataset_id, question):
    return TestClient(app).post(
        "/api/analyze", json={"dataset_id": dataset_id, "question": question}
    )


def _sales_df():
    return pd.DataFrame(
        {"region": ["north", "north", "south", "east"], "quantity": [10, 20, 30, 40]}
    )


def _use_ai_planner(monkeypatch, outcome):
    """Force the AI planner path with a stubbed result or exception."""

    class _NoFastPlan:
        def create_plan(self, question, metadata):
            return None

    def _ai(user_question, metadata):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(analysis_route, "FastPlanner", _NoFastPlan)
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _ai)


def test_route_adds_explanation_and_keeps_existing_fields(route, monkeypatch):
    dataset = route(_sales_df())

    # Rule-based planner stubbed to a known valid plan; the AI planner
    # (which could make a real network call) must never run.
    class _StubFastPlanner:
        def create_plan(self, question, metadata):
            return AnalysisPlan(metric="quantity", aggregation="sum", group_by=["region"])

    def _no_ai_planner(**kwargs):
        raise AssertionError("AI planner must not be called")

    monkeypatch.setattr(analysis_route, "FastPlanner", _StubFastPlanner)
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _no_ai_planner)

    response = _post(dataset.dataset_id, "total quantity by region")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXISTING_RESPONSE_KEYS | {"plan_explanation"}
    assert set(body["data"]) == {"columns", "rows", "row_count", "row_limit", "row_limit_reached"}

    # Derived from the canonical plan the route returned.
    plan = body["plan"]
    assert body["plan_explanation"] == {
        "interpreted_by": "rule-based",
        "steps": [
            f"Sum of {plan['metric']} for each {plan['group_by'][0]}.",
            "No filters were applied.",
            "Sorted by the calculated sum, highest first.",
        ],
        "limitations": [],
    }
    assert body["planner"] == {"type": "fast", "fallback": False}


def test_route_explanation_reflects_ai_plan_and_execution_limit(route, monkeypatch):
    dataset = route(_sales_df())
    _use_ai_planner(
        monkeypatch,
        AnalysisPlan(metric="quantity", aggregation="mean", group_by=["region"], limit=2),
    )

    body = _post(dataset.dataset_id, "anything").json()

    assert body["planner"] == {"type": "ai", "fallback": True}
    assert body["data"]["row_limit_reached"] is True
    assert body["plan_explanation"]["interpreted_by"] == "ai"
    assert "Limited to the top 2 groups." in body["plan_explanation"]["steps"]
    assert body["plan_explanation"]["limitations"] == [
        "The result reached the requested limit of 2 groups, so more groups may exist."
    ]


def test_explanation_failure_returns_null_without_failing_analysis(route, monkeypatch):
    dataset = route(_sales_df())

    # Rule-based planner stubbed to a known valid plan; the AI planner
    # (which could make a real network call) must never run.
    class _StubFastPlanner:
        def create_plan(self, question, metadata):
            return AnalysisPlan(metric="quantity", aggregation="sum", group_by=["region"])

    def _no_ai_planner(**kwargs):
        raise AssertionError("AI planner must not be called")

    monkeypatch.setattr(analysis_route, "FastPlanner", _StubFastPlanner)
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _no_ai_planner)

    def _boom(*args, **kwargs):
        raise RuntimeError("explainer broke")

    monkeypatch.setattr(analysis_route, "explain_plan", _boom)

    response = _post(dataset.dataset_id, "total quantity by region")

    assert response.status_code == 200
    body = response.json()
    assert body["plan_explanation"] is None
    assert body["success"] is True
    assert body["data"]["row_count"] == 3
    assert set(body) == EXISTING_RESPONSE_KEYS | {"plan_explanation"}


@pytest.mark.parametrize(
    "outcome, status, detail",
    [
        (
            AnalysisClarificationError("Which date column should be used?"),
            422,
            "Which date column should be used?",
        ),
        (
            RuntimeError("OPENAI_API_KEY is not configured."),
            503,
            None,
        ),
        (
            AnalysisPlan(metric="no_such_column", aggregation="sum"),
            400,
            "Invalid analysis plan: Unknown metric: no_such_column",
        ),
    ],
)
def test_existing_error_responses_are_unchanged(route, monkeypatch, outcome, status, detail):
    dataset = route(_sales_df())
    _use_ai_planner(monkeypatch, outcome)

    response = _post(dataset.dataset_id, "anything")

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"detail"}
    if detail is not None:
        assert body["detail"] == detail
    else:
        assert "API key" in body["detail"]


def test_authorization_errors_are_unchanged(route, monkeypatch):
    dataset = route(_sales_df(), owner_id="alice")

    missing = _post("00000000-0000-0000-0000-000000000000", "total quantity by region")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "mallory")
    foreign = _post(dataset.dataset_id, "total quantity by region")

    for response in (missing, foreign):
        assert response.status_code == 404
        assert set(response.json()) == {"detail"}


def test_explanation_comes_only_from_the_requested_dataset(route, monkeypatch):
    sales = route(_sales_df())
    shop = route(pd.DataFrame({"city": ["a", "b", "a"], "amount": [1.0, 2.0, 3.0]}))

    # Both planners stubbed: plans come from this table, and the AI
    # planner (which could make a real network call) must never run.
    plans = {
        "total quantity by region": AnalysisPlan(
            metric="quantity", aggregation="sum", group_by=["region"]
        ),
        "total amount by city": AnalysisPlan(
            metric="amount", aggregation="sum", group_by=["city"]
        ),
    }

    class _StubFastPlanner:
        def create_plan(self, question, metadata):
            return plans[question]

    def _no_ai_planner(**kwargs):
        raise AssertionError("AI planner must not be called")

    monkeypatch.setattr(analysis_route, "FastPlanner", _StubFastPlanner)
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _no_ai_planner)

    sales_body = _post(sales.dataset_id, "total quantity by region").json()
    shop_body = _post(shop.dataset_id, "total amount by city").json()

    sales_text = _all_text(sales_body["plan_explanation"])
    shop_text = _all_text(shop_body["plan_explanation"])

    assert "quantity" in sales_text and "region" in sales_text
    assert "amount" not in sales_text and "city" not in sales_text
    assert "amount" in shop_text and "city" in shop_text
    assert "quantity" not in shop_text and "region" not in shop_text
    assert shop_body["plan"]["metric"] == "amount"

    # A plan naming the other dataset's columns is rejected against the
    # requested dataset - never answered from the other one.
    crossed = _post(shop.dataset_id, "total quantity by region")
    assert crossed.status_code == 400
    assert set(crossed.json()) == {"detail"}
