"""
Focused FastPlanner regression tests: categorical equality filters vs grouping.

"total revenue in the North region" must be a filtered scalar total
(filter region="North", no group_by), while "revenue by region" stays a
grouped comparison. Filter values must resolve to real metadata values;
anything unresolvable defers to the AI planner (None).
"""

import pytest

from ai.fast_planner import FastPlanner
from data_engine.analysis_plan import FilterCondition


METADATA = {
    "columns": {
        "revenue": {"role": "metric", "sample_values": [100.0, 250.5]},
        "sales": {"role": "metric", "sample_values": [10, 20]},
        "region": {
            "role": "dimension",
            "sample_values": ["North", "South", "East", "West"],
        },
        "country": {
            "role": "dimension",
            "sample_values": ["India", "USA", "Germany"],
        },
        "city": {
            "role": "dimension",
            "sample_values": ["Delhi", "Mumbai", "Berlin"],
        },
        "category": {
            "role": "dimension",
            "sample_values": ["Electronics", "Furniture"],
        },
        "order_date": {"role": "time", "sample_values": ["2024-01-01"]},
    }
}


@pytest.fixture
def planner():
    return FastPlanner()


def test_total_revenue_in_north_region_is_filter_not_group(planner):
    plan = planner.create_plan(
        "What was the total revenue in the North region?", METADATA
    )

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="region", operator="=", value="North")
    ]
    assert plan.group_by == []
    assert plan.metric == "revenue"
    assert plan.aggregation == "sum"
    assert plan.visualization == "table"


@pytest.mark.parametrize(
    "question",
    [
        "Show total revenue by region",
        "Show total revenue per region",
        "Show total revenue for each region",
    ],
)
def test_grouping_language_still_groups(planner, question):
    plan = planner.create_plan(question, METADATA)

    assert plan is not None
    assert plan.filters == []
    assert plan.group_by == ["region"]
    assert plan.metric == "revenue"


def test_total_sales_for_india_filters_country(planner):
    plan = planner.create_plan("Show total sales for India", METADATA)

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="country", operator="=", value="India")
    ]
    assert plan.group_by == []
    assert plan.metric == "sales"
    assert plan.aggregation == "sum"


def test_total_revenue_for_north_without_column_word(planner):
    plan = planner.create_plan("Show total revenue for North", METADATA)

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="region", operator="=", value="North")
    ]
    assert plan.group_by == []


def test_sales_from_delhi_filters_city(planner):
    plan = planner.create_plan("Show total sales from Delhi", METADATA)

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="city", operator="=", value="Delhi")
    ]
    assert plan.group_by == []


def test_revenue_in_electronics_category(planner):
    plan = planner.create_plan(
        "Show total revenue in the Electronics category", METADATA
    )

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="category", operator="=", value="Electronics")
    ]
    assert plan.group_by == []


def test_value_resolution_is_case_insensitive_and_canonical(planner):
    plan = planner.create_plan(
        "what was the total revenue in the north region", METADATA
    )

    assert plan is not None
    # Canonical dataset value, not the user's casing.
    assert plan.filters == [
        FilterCondition(column="region", operator="=", value="North")
    ]


def test_filter_combined_with_grouping_on_other_column(planner):
    plan = planner.create_plan(
        "Show total revenue by city in the North region", METADATA
    )

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="region", operator="=", value="North")
    ]
    assert plan.group_by == ["city"]


@pytest.mark.parametrize(
    "question",
    [
        "What was the total revenue in the Mars region?",
        "Show total sales for Atlantis",
    ],
)
def test_unresolved_categorical_value_returns_none(planner, question):
    assert planner.create_plan(question, METADATA) is None


def test_value_present_in_two_columns_is_ambiguous(planner):
    metadata = {
        "columns": {
            "revenue": {"role": "metric"},
            "region": {"role": "dimension", "sample_values": ["North"]},
            "zone": {"role": "dimension", "sample_values": ["North"]},
        }
    }

    assert planner.create_plan("Show total revenue for North", metadata) is None


def test_column_word_disambiguates_shared_value(planner):
    metadata = {
        "columns": {
            "revenue": {"role": "metric"},
            "region": {"role": "dimension", "sample_values": ["North"]},
            "zone": {"role": "dimension", "sample_values": ["North"]},
        }
    }

    plan = planner.create_plan(
        "Show total revenue in the North zone", metadata
    )

    assert plan is not None
    assert plan.filters == [
        FilterCondition(column="zone", operator="=", value="North")
    ]


def test_ranking_with_categorical_filter(planner):
    plan = planner.create_plan(
        "Show the top 3 cities by revenue in the North region", METADATA
    )

    assert plan is not None
    assert plan.group_by == ["city"]
    assert plan.limit == 3
    assert plan.filters == [
        FilterCondition(column="region", operator="=", value="North")
    ]


def test_plain_total_and_time_analysis_unchanged(planner):
    total = planner.create_plan("Show total revenue", METADATA)
    assert total is not None
    assert total.filters == []
    assert total.group_by == []

    monthly = planner.create_plan("Show monthly total revenue", METADATA)
    assert monthly is not None
    assert monthly.group_by == ["order_date"]
    assert monthly.time_granularity == "month"


def test_unsupported_conditions_still_defer(planner):
    assert (
        planner.create_plan(
            "Show total revenue in the North region during holidays", METADATA
        )
        is None
    )
