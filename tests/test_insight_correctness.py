"""Insight correctness fixes (Step 93).

Each test pins one verified defect in the deterministic insight path:
  - a "trend" derived from row order over a non-time grouping;
  - a trend read in metric order instead of chronological order;
  - extremes/coverage computed on a LIMIT-ed result as if it were whole;
  - coverage counting rows as periods, and ignoring the plan granularity;
  - integer columns mistaken for dates;
  - a NaN in a result row rejecting every insight in validation;
  - nondeterministic tie order under LIMIT.
"""

import math

import pandas as pd

from ai.insight_validator import validate_insights
from data_engine.analysis_plan import AnalysisPlan
from data_engine.duckdb_query_engine import execute_plan_duckdb
from data_engine.insight_engine import build_deterministic_insights
from data_engine.insight_generator import build_insight_response
from data_engine.storage.duckdb_storage import DuckDBStorage

METRIC = "sum_revenue"


def _insights(result, group_by, **kwargs):
    context = build_deterministic_insights(
        result=result, metric_column=METRIC, group_by=group_by, **kwargs
    )
    response = build_insight_response(context=context)
    validate_insights(response, context)
    return context, {insight.type: insight for insight in response.insights}


# =========================================================
# Trend
# =========================================================


def test_categorical_grouping_produces_no_trend():
    # Metric-descending order (the query default) used to be read as
    # "values decreased across the observed periods".
    result = pd.DataFrame({"region": ["West", "East", "North"], METRIC: [900, 500, 100]})

    context, insights = _insights(result, ["region"])

    assert "trend" not in context
    assert "trend" not in insights
    assert "highest" in insights and "lowest" in insights


def test_time_trend_uses_chronological_order_not_row_order():
    # Returned metric-descending: Apr, Mar, Feb, Jan - chronologically rising.
    result = pd.DataFrame(
        {
            "month": pd.to_datetime(["2024-04-01", "2024-03-01", "2024-02-01", "2024-01-01"]),
            METRIC: [40, 30, 20, 10],
        }
    )

    context, insights = _insights(result, ["month"], time_granularity="month")

    assert context["trend"]["direction"] == "increasing"
    assert context["trend"]["first_value"] == 10
    assert context["trend"]["last_value"] == 40
    trend = insights["trend"]
    assert "increased" in trend.title
    assert [row[METRIC] for row in trend.evidence.rows] == [10, 20, 30, 40]


def test_multiple_group_by_columns_produce_no_trend():
    result = pd.DataFrame(
        {
            "region": ["north", "south", "north", "south"],
            "month": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01"]),
            METRIC: [10, 50, 20, 5],
        }
    )

    context, _ = _insights(result, ["region", "month"])

    assert "trend" not in context


# =========================================================
# LIMIT-ed results
# =========================================================


def test_limited_descending_result_keeps_only_highest():
    result = pd.DataFrame({"product": ["a", "b", "c"], METRIC: [900, 700, 650]})

    context, insights = _insights(
        result, ["product"], row_limit_reached=True, sort="desc", sort_by="metric"
    )

    assert context["row_limit_reached"] is True
    assert "lowest" not in context and "difference" not in context
    assert set(insights) == {"highest"}
    assert insights["highest"].evidence.value == 900


def test_limited_ascending_result_keeps_only_lowest():
    result = pd.DataFrame({"product": ["a", "b", "c"], METRIC: [5, 7, 9]})

    _, insights = _insights(
        result, ["product"], row_limit_reached=True, sort="asc", sort_by="metric"
    )

    assert set(insights) == {"lowest"}
    assert insights["lowest"].evidence.value == 5


def test_limited_time_result_has_no_coverage_trend_or_extremes():
    # Top 3 months by revenue: the "gaps" are rows past the LIMIT.
    result = pd.DataFrame(
        {
            "month": pd.to_datetime(["2024-12-01", "2024-07-01", "2024-03-01"]),
            METRIC: [90, 80, 70],
        }
    )

    context, insights = _insights(
        result, ["month"], row_limit_reached=True, sort="desc", sort_by="time"
    )

    assert "date_coverage" not in context
    assert "trend" not in context
    assert insights == {}


# =========================================================
# Coverage
# =========================================================


def test_coverage_counts_distinct_periods_not_rows():
    # 3 months x 2 regions = 6 rows, March missing.
    result = pd.DataFrame(
        {
            "region": ["n", "s"] * 3,
            "month": pd.to_datetime(
                ["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01", "2024-04-01", "2024-04-01"]
            ),
            METRIC: [1, 2, 3, 4, 5, 6],
        }
    )

    context, insights = _insights(result, ["region", "month"])

    coverage = context["date_coverage"]
    assert coverage["observed_periods"] == 3
    assert coverage["expected_periods"] == 4
    assert coverage["missing_periods"] == ["2024-03"]
    assert "Only 3 of the 4 expected month periods" in insights["coverage"].description


def test_coverage_follows_plan_granularity():
    # Yearly buckets used to be checked month by month (25 expected).
    result = pd.DataFrame(
        {
            "year": pd.to_datetime(["2020-01-01", "2021-01-01", "2023-01-01"]),
            METRIC: [1, 2, 3],
        }
    )

    context, _ = _insights(result, ["year"], time_granularity="year")

    coverage = context["date_coverage"]
    assert coverage["frequency"] == "year"
    assert coverage["expected_periods"] == 4
    assert coverage["observed_periods"] == 3
    assert coverage["missing_periods"] == ["2022"]


def test_integer_group_column_is_not_treated_as_a_date():
    result = pd.DataFrame({"fiscal_year": [2021, 2022, 2024], METRIC: [5, 6, 7]})

    context, _ = _insights(result, ["fiscal_year"])

    assert "date_coverage" not in context
    assert "trend" not in context


def test_daily_labels_distinguish_days_in_the_same_month():
    result = pd.DataFrame(
        {
            "order_date": pd.to_datetime(["2024-03-01", "2024-03-02", "2024-03-03"]),
            METRIC: [10, 30, 20],
        }
    )

    _, insights = _insights(result, ["order_date"], time_granularity="day")

    assert insights["highest"].title.startswith("02 March 2024")
    assert insights["lowest"].title.startswith("01 March 2024")


# =========================================================
# Null handling
# =========================================================


def test_nan_group_key_does_not_reject_all_insights():
    result = pd.DataFrame({"discount": [0.1, math.nan, 0.3], METRIC: [100, 900, 50]})

    context, insights = _insights(result, ["discount"])

    # The NULL group is the highest; its evidence row carries NaN.
    assert math.isnan(insights["highest"].evidence.row["discount"])
    assert insights["highest"].evidence.value == 900
    assert "lowest" in insights and "difference" in insights


def test_nan_metric_row_is_excluded_from_trend_evidence():
    result = pd.DataFrame(
        {
            "month": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
            METRIC: [10.0, math.nan, 30.0],
        }
    )

    context, insights = _insights(result, ["month"])

    assert context["trend"]["direction"] == "increasing"
    assert [row[METRIC] for row in insights["trend"].evidence.rows] == [10.0, 30.0]


def test_format_number_hides_float_noise_and_keeps_separators():
    from data_engine.insight_generator import _format_number

    assert _format_number(38507381.92000001) == "38,507,381.92"
    assert _format_number(4643.209240401993) == "4,643.21"
    assert _format_number(26534.5) == "26,534.5"
    assert _format_number(1234567) == "1,234,567"
    assert _format_number(1234567.0) == "1,234,567"
    assert _format_number(0) == "0"
    assert _format_number(0.0) == "0"
    assert _format_number(-1234.567) == "-1,234.57"
    assert _format_number(9.999) == "10"
    # Below 0.01, two decimals would read as 0 - keep 2 significant digits.
    assert _format_number(0.004321) == "0.0043"
    assert _format_number(-0.004) == "-0.004"


def test_format_number_never_uses_scientific_notation_for_tiny_values():
    from data_engine.insight_generator import _format_number

    assert _format_number(0.0000001) == "0.0000001"
    assert _format_number(-0.0000001) == "-0.0000001"
    assert _format_number(0.000000123456) == "0.00000012"
    assert _format_number(0.004321) == "0.0043"
    assert _format_number(9.999) == "10"


def test_description_is_rounded_but_evidence_keeps_exact_value():
    result = pd.DataFrame(
        {"product": ["a", "b"], METRIC: [38507381.92000001, 1000.0]}
    )

    _, insights = _insights(result, ["product"])

    highest = insights["highest"]
    assert "38,507,381.92." in highest.description
    assert "92000001" not in highest.description
    assert highest.evidence.value == 38507381.92000001


def test_gap_insight_makes_no_unsupported_size_claim():
    result = pd.DataFrame({"region": ["a", "b"], METRIC: [100.0, 100.01]})

    _, insights = _insights(result, ["region"])

    assert "Large" not in insights["difference"].title


# =========================================================
# /api/analyze exposes the row limit to the client
# =========================================================


def test_analyze_response_reports_row_limit(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.jobs as jobs
    import backend.routes.analysis as analysis_route
    from backend.main import app
    from data_engine.dataset import Dataset
    from data_engine.dataset_registry import DatasetRegistry
    from data_engine.metadata import get_metadata
    from data_engine.storage import PandasStorage

    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)

    df = pd.DataFrame({"region": ["north", "north", "south"], "quantity": [1, 2, 3]})
    dataset = Dataset(storage=PandasStorage(df), owner_id="dev-user")
    dataset.cache["planning_metadata"] = get_metadata(df)
    registry.register(dataset)

    try:
        response = TestClient(app).post(
            "/api/analyze",
            json={"dataset_id": dataset.dataset_id, "question": "total quantity by region"},
        )
    finally:
        manager.shutdown(wait=True)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["row_count"] == 2
    assert data["row_limit"] == 10_000
    assert data["row_limit_reached"] is False


# =========================================================
# Deterministic ties
# =========================================================


def test_tied_metric_values_are_ordered_by_group_columns():
    df = pd.DataFrame({"region": ["c", "a", "b"], "revenue": [5, 5, 5]})
    storage = DuckDBStorage(df)
    try:
        plan = AnalysisPlan(
            metric="revenue", aggregation="sum", group_by=["region"], limit=2
        )
        result = execute_plan_duckdb(storage, plan)
    finally:
        storage.close()

    assert list(result["region"]) == ["a", "b"]
