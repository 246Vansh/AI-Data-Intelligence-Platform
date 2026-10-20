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


# =========================================================
# Step 97: filter follow-ups
# =========================================================

FILTER_METADATA = {
    "columns": {
        "region": {
            "role": "dimension",
            "data_type": "string",
            "sample_values": ["North", "South", "North", "East"],
        },
        "category": {
            "role": "dimension",
            "data_type": "string",
            "sample_values": ["Electronics", "Toys"],
        },
        "quantity": {"role": "metric", "data_type": "integer", "sample_values": [1, 2]},
        "unit_price": {"role": "metric", "data_type": "float", "sample_values": [1.5]},
        "order_date": {"role": "time", "data_type": "datetime", "sample_values": []},
    }
}

BY_CATEGORY = AnalysisPlan(
    metric="quantity",
    aggregation="sum",
    group_by=["category"],
    sort="asc",
    limit=5,
    filters=[FilterCondition("unit_price", ">", 1.0)],
)

UNFILTERED = AnalysisPlan(metric="quantity", aggregation="sum", group_by=["region"])


def _filters(plan):
    return [(f.column, f.operator, f.value) for f in plan.filters]


def test_equality_filter_is_added_and_everything_else_preserved():
    follow_up = resolve_follow_up("Only include the North region.", BY_CATEGORY, FILTER_METADATA)

    plan = follow_up.plan
    assert _filters(plan) == [("unit_price", ">", 1.0), ("region", "=", "North")]
    assert (plan.metric, plan.aggregation, plan.group_by) == ("quantity", "sum", ["category"])
    assert (plan.sort, plan.sort_by, plan.limit) == ("asc", "metric", 5)
    assert follow_up.change == 'added the filter region = "North"'
    # Never mutates the client-supplied previous plan.
    assert _filters(BY_CATEGORY) == [("unit_price", ">", 1.0)]


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Filter to category Electronics", ("category", "=", "Electronics")),
        ("only show region south", ("region", "=", "South")),  # dataset spelling
        ("keep only the region east", ("region", "=", "East")),
        ('only include region "West Coast"', ("region", "=", "West Coast")),  # quoted verbatim
    ],
)
def test_equality_filter_phrasings(question, expected):
    plan = resolve_follow_up(question, BY_CATEGORY, FILTER_METADATA).plan

    assert _filters(plan)[-1] == expected


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Only include quantity greater than 10", ("quantity", ">", 10)),
        ("only include quantity more than 10", ("quantity", ">", 10)),
        ("only include quantity above 10", ("quantity", ">", 10)),
        ("only include quantity at least 10", ("quantity", ">=", 10)),
        ("only include quantity less than 10", ("quantity", "<", 10)),
        ("only include quantity below -3", ("quantity", "<", -3)),
        ("only include quantity at most 10", ("quantity", "<=", 10)),
        ("only include quantity >= 10", ("quantity", ">=", 10)),
        ("only show unit price at most 2.5", ("unit_price", "<=", 2.5)),
    ],
)
def test_numeric_comparison_filters(question, expected):
    plan = resolve_follow_up(question, UNFILTERED, FILTER_METADATA).plan

    condition = plan.filters[-1]
    assert (condition.column, condition.operator, condition.value) == expected
    assert type(condition.value) is type(expected[2])


@pytest.mark.parametrize(
    "question",
    [
        "only include the Mars region",  # value not in the column
        "only include the north territory",  # no such column
        "keep only toys",  # no column named
        "only include quantity greater than ten",  # not a number
        "only include quantity != 3",  # unsupported operator
        "only include quantity equals 3",  # numeric equality unsupported
        "only include region greater than 5",  # comparison on a text column
        "only include order date after 2024",  # unsupported condition
        "exclude the north region",  # exclusion unsupported
        "only include the north region and top 5",  # compound edit
        "only include the north region by city instead",  # compound edit
        'only include region "a" or region "b"',  # two values
    ],
)
def test_unsupported_filter_follow_ups_are_refused(question):
    previous = AnalysisPlan(metric="quantity", aggregation="sum", group_by=["category"])

    assert resolve_follow_up(question, previous, FILTER_METADATA) is None


def test_ambiguous_value_or_column_is_refused():
    ambiguous_value = {
        "columns": {
            "region": {
                "role": "dimension",
                "data_type": "string",
                "sample_values": ["North", "north"],
            },
        }
    }
    ambiguous_column = {
        "columns": {
            "unit_price": {"role": "metric", "data_type": "float", "sample_values": []},
            "unit-price": {"role": "metric", "data_type": "float", "sample_values": []},
        }
    }
    previous = AnalysisPlan(metric="x", aggregation="sum")

    assert resolve_follow_up("only include the north region", previous, ambiguous_value) is None
    assert resolve_follow_up("only include unit price above 2", previous, ambiguous_column) is None


def test_adding_a_second_value_for_a_column_is_refused_not_replaced():
    previous = AnalysisPlan(
        metric="quantity", aggregation="sum", filters=[FilterCondition("region", "=", "North")]
    )

    assert resolve_follow_up("only include the south region", previous, FILTER_METADATA) is None
    assert resolve_follow_up("only include the north region", previous, FILTER_METADATA) is None


def test_replacement_only_on_explicit_wording_and_keeps_other_filters():
    previous = AnalysisPlan(
        metric="quantity",
        aggregation="sum",
        group_by=["category"],
        filters=[FilterCondition("region", "=", "North"), FilterCondition("quantity", ">", 1)],
    )

    follow_up = resolve_follow_up("Use South instead of North", previous, FILTER_METADATA)

    assert _filters(follow_up.plan) == [("region", "=", "South"), ("quantity", ">", 1)]
    assert follow_up.change == 'replaced the filter region = "North" with region = "South"'
    # Nothing to replace / unknown new value / same value.
    assert resolve_follow_up("use Toys instead of Electronics", previous, FILTER_METADATA) is None
    assert resolve_follow_up("use Mars instead of North", previous, FILTER_METADATA) is None
    assert resolve_follow_up("use North instead of North", previous, FILTER_METADATA) is None


def test_replacement_never_targets_a_different_column_than_named():
    metadata = {
        "columns": {
            **FILTER_METADATA["columns"],
            "region_code": {
                "role": "dimension",
                "data_type": "string",
                "sample_values": ["N1", "S1"],
            },
        }
    }
    previous = AnalysisPlan(
        metric="quantity",
        aggregation="sum",
        filters=[FilterCondition("region", "=", "North"), FilterCondition("region_code", "=", "N1")],
    )

    # "North" is region's value, but the user named region_code.
    assert resolve_follow_up("use South instead of North region code", previous, metadata) is None
    # Naming the matching column is still fine.
    follow_up = resolve_follow_up("use South instead of North region", previous, metadata)
    assert _filters(follow_up.plan) == [("region", "=", "South"), ("region_code", "=", "N1")]


def test_existing_filters_are_preserved_when_adding_another():
    previous = AnalysisPlan(
        metric="quantity",
        aggregation="sum",
        filters=[FilterCondition("region", "=", "North"), FilterCondition("quantity", ">", 1)],
    )

    plan = resolve_follow_up("filter to category Toys", previous, FILTER_METADATA).plan

    assert _filters(plan) == [
        ("region", "=", "North"),
        ("quantity", ">", 1),
        ("category", "=", "Toys"),
    ]


@pytest.mark.parametrize(
    "question",
    ["only include the Mars region", "exclude north", "filter it to whatever"],
)
def test_filter_cues_count_as_references_so_failures_are_refused(question):
    assert references_previous(question) is True


# ---------------------------------------------------------
# Route
# ---------------------------------------------------------

BY_PRODUCT = AnalysisPlan(metric="quantity", aggregation="sum", group_by=["product"])


def test_route_equality_filter_follow_up(env):
    dataset = env["register"](_sales_df())

    response = _post(
        dataset.dataset_id, "Only include the North region", _context(dataset.dataset_id, BY_PRODUCT)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planner"] == {"type": "follow_up", "fallback": False}
    # Dataset spelling ("north"), resolved from planning metadata.
    assert body["plan"]["filters"] == [{"column": "region", "operator": "=", "value": "north"}]
    assert body["data"]["rows"] == [{"product": "a", "sum_quantity": 4}]
    assert body["plan_explanation"]["steps"][:3] == [
        'Follow-up to the previous analysis: added the filter region = "north".',
        "Sum of quantity for each product.",
        'Only rows where region equals "north" were included.',
    ]
    assert env["ai_calls"] == []


def test_route_numeric_filter_follow_up(env):
    dataset = env["register"](_sales_df())

    body = _post(
        dataset.dataset_id,
        "Only include quantity greater than 2",
        _context(dataset.dataset_id, BY_PRODUCT),
    ).json()

    assert body["plan"]["filters"] == [{"column": "quantity", "operator": ">", "value": 2}]
    assert sorted(
        (row["product"], row["sum_quantity"]) for row in body["data"]["rows"]
    ) == [("a", 3), ("b", 5), ("c", 4)]
    assert "Only rows where quantity is greater than 2 were included." in (
        body["plan_explanation"]["steps"]
    )


@pytest.mark.parametrize(
    "question",
    [
        "only include the Mars region",
        "only include price greater than 1",  # column of the other dataset
        "exclude the north region",
        "only include the north region and top 5",
    ],
)
def test_route_refuses_unapplicable_filter_follow_ups(env, question):
    dataset = env["register"](_sales_df())
    env["register"](_shop_df())

    response = _post(dataset.dataset_id, question, _context(dataset.dataset_id, BY_PRODUCT))

    assert response.status_code == 422
    assert "follow-up" in response.json()["detail"]
    assert env["ai_calls"] == []


def test_route_filter_context_from_another_dataset_is_rejected(env):
    sales = env["register"](_sales_df())
    shop = env["register"](_shop_df())

    response = _post(
        shop.dataset_id, "Only include the North region", _context(sales.dataset_id, BY_PRODUCT)
    )

    assert response.status_code == 400


def test_route_previous_filter_naming_unknown_column_is_rejected(env):
    dataset = env["register"](_sales_df())
    previous = AnalysisPlan(
        metric="quantity",
        aggregation="sum",
        group_by=["product"],
        filters=[FilterCondition("city", "=", "x")],  # not in this dataset
    )

    response = _post(
        dataset.dataset_id, "Only include the North region", _context(dataset.dataset_id, previous)
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Invalid analysis_context:")


# ---------------------------------------------------------
# Engine parity for the operators filter follow-ups produce
# ---------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        FilterCondition("region", "=", "north"),
        FilterCondition("quantity", ">", 2),
        FilterCondition("quantity", "<=", 4),
    ],
)
def test_duckdb_and_pandas_agree_on_follow_up_filters_with_nulls(condition):
    from data_engine.plan_executor import execute_plan_for_dataset
    from data_engine.storage import PandasStorage

    df = pd.DataFrame(
        {
            "region": ["north", None, "south", "north", "east"],
            "product": ["a", "b", "a", "c", "b"],
            "quantity": [1.0, 3.0, None, 5.0, 2.0],
        }
    )
    plan = AnalysisPlan(
        metric="quantity",
        aggregation="count",
        group_by=["product"],
        filters=[condition],
    )

    def run(storage):
        result = execute_plan_for_dataset(Dataset(storage=storage), plan)
        return sorted((row["product"], row["count_quantity"]) for row in result.rows)

    duck = DuckDBStorage(df)
    try:
        assert run(duck) == run(PandasStorage(df))
    finally:
        duck.close()
