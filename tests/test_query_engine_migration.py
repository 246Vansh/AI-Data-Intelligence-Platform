"""Step 8: query/compute delegation - grouped/global aggregation,
sorting, and limiting fully behind the storage-aware ExecutionEngine
boundary.

This step adds no new production code: Step 7's
plan_executor.execute_plan_for_dataset() already routes a DuckDB-backed
Dataset's *entire* plan (filters, time-bucketing, grouping,
aggregation, sorting, limiting) to DuckDBExecutionEngine ->
execute_plan_duckdb(), and a Pandas-backed Dataset's entire plan to
PandasExecutionEngine -> execute_plan() -> query_engine.analyze() -
unmodified. This suite specifically exercises the aggregation/sort/
limit surface (rather than Step 7's filter/time-bucketing focus) to
prove that surface has full parity and never leaks a full-dataset
materialization on the DuckDB path, and that query_engine.py itself
stays storage/engine-agnostic.

Verifies:
  - Full semantic parity across all 6 canonical aggregations, grouped
    and global, between the DuckDB and Pandas paths.
  - limit / no-limit and sort_by="metric" / sort_by="time" combinations
    produce equivalent outputs on both paths.
  - Validation failures (unknown metric, unknown group-by column) are
    raised consistently on both paths.
  - Grouped/global aggregation, sorting, and limiting on a DuckDB-
    backed dataset never call storage.to_dataframe() on the raw data.
  - Legacy direct APIs (query_engine.analyze(), plan_executor.
    execute_plan()) remain fully functional and unmodified.
  - query_engine.py itself contains no DuckDB import, no raw SQL, and
    no storage-type checks.
"""

import ast
import inspect

import pandas as pd
import pytest

import data_engine.query_engine as query_engine_module
from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.duckdb_query_engine import DEFAULT_MAX_RESULT_ROWS
from data_engine.execution.result import ExecutionResult
from data_engine.plan_executor import execute_plan, execute_plan_for_dataset
from data_engine.query_engine import analyze
from data_engine.storage import DuckDBStorage, PandasStorage


def _to_dataframe(execution_result: ExecutionResult) -> pd.DataFrame:
    """
    Test-only compatibility conversion: execute_plan_for_dataset() now
    returns an engine-neutral ExecutionResult. Existing assertions in
    this file compare against pandas DataFrames, so results are
    converted back for the comparison rather than rewriting every
    assertion.
    """
    return pd.DataFrame(execution_result.rows, columns=execution_result.columns)


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
            "signed_up_at": pd.to_datetime(
                [
                    "2024-01-05",
                    "2024-02-10",
                    "2024-03-15",
                    "2024-04-20",
                    "2024-05-25",
                    "2024-06-30",
                ]
            ),
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# AGGREGATION PARITY - all 6 canonical aggregations
# =========================================================


@pytest.mark.parametrize(
    "aggregation", ["sum", "mean", "median", "min", "max", "count"]
)
def test_grouped_aggregation_parity_between_duckdb_and_pandas(aggregation):
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation=aggregation)

    duckdb_result = _to_dataframe(
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)
    )
    pandas_result = _to_dataframe(
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)
    )

    assert list(duckdb_result.columns) == list(pandas_result.columns)
    duckdb_sorted = duckdb_result.sort_values("region").reset_index(drop=True)
    pandas_sorted = pandas_result.sort_values("region").reset_index(drop=True)
    pd.testing.assert_frame_equal(duckdb_sorted, pandas_sorted, check_dtype=False)


@pytest.mark.parametrize(
    "aggregation", ["sum", "mean", "median", "min", "max", "count"]
)
def test_global_aggregation_parity_between_duckdb_and_pandas(aggregation):
    df = _make_dataframe()
    plan = AnalysisPlan(metric="quantity", aggregation=aggregation)

    duckdb_result = execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)
    pandas_result = execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)

    assert duckdb_result.columns == [f"{aggregation}_quantity"]
    assert duckdb_result.rows[0][f"{aggregation}_quantity"] == pytest.approx(
        pandas_result.rows[0][f"{aggregation}_quantity"]
    )


# =========================================================
# SORT / LIMIT COMBINATIONS
# =========================================================


@pytest.mark.parametrize("limit", [None, 1, 2])
@pytest.mark.parametrize("sort", ["asc", "desc"])
def test_sort_and_limit_combinations_parity(sort, limit):
    df = _make_dataframe()
    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort=sort,
        sort_by="metric",
        limit=limit,
    )

    duckdb_result = execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)
    pandas_result = execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)

    assert [row["region"] for row in duckdb_result.rows] == [
        row["region"] for row in pandas_result.rows
    ]
    assert [row["sum_quantity"] for row in duckdb_result.rows] == [
        row["sum_quantity"] for row in pandas_result.rows
    ]
    if limit is not None:
        assert duckdb_result.row_count == limit


@pytest.mark.parametrize(
    "time_granularity", ["day", "week", "month", "quarter", "year"]
)
def test_sort_by_time_parity(time_granularity):
    df = _make_dataframe()
    plan = AnalysisPlan(
        group_by=["signed_up_at"],
        metric="quantity",
        aggregation="sum",
        time_column="signed_up_at",
        time_granularity=time_granularity,
        sort="desc",
        sort_by="time",
    )

    duckdb_result = execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)
    pandas_result = execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)

    assert [row["sum_quantity"] for row in duckdb_result.rows] == [
        row["sum_quantity"] for row in pandas_result.rows
    ]


# =========================================================
# VALIDATION / REJECTION PARITY
# =========================================================


def test_unknown_metric_rejected_on_both_paths():
    df = _make_dataframe()
    plan = AnalysisPlan(metric="does_not_exist", aggregation="sum")

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


def test_unknown_group_by_column_rejected_on_both_paths():
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["does_not_exist"], metric="quantity", aggregation="sum")

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


def test_unsupported_aggregation_rejected_on_both_paths():
    df = _make_dataframe()
    plan = AnalysisPlan(metric="quantity", aggregation="stdev")

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


# =========================================================
# BOUNDARY DISCIPLINE - aggregation/sort/limit never materialize
# the raw dataset into pandas on the DuckDB path.
# =========================================================


def test_duckdb_grouped_aggregation_sort_limit_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="mean",
        sort="desc",
        sort_by="metric",
        limit=2,
    )

    execute_plan_for_dataset(dataset, plan)

    assert storage.to_dataframe_calls == []


def test_duckdb_global_aggregation_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(metric="quantity", aggregation="count")

    execute_plan_for_dataset(dataset, plan)

    assert storage.to_dataframe_calls == []


# =========================================================
# LEGACY DIRECT APIs REMAIN FULLY FUNCTIONAL
# =========================================================


def test_legacy_direct_analyze_still_works():
    df = _make_dataframe()

    result = analyze(df, group_by=["region"], metric="quantity", aggregation="sum")

    assert list(result.columns) == ["region", "sum_quantity"]
    assert len(result) == 3


def test_legacy_direct_execute_plan_still_works():
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    result = execute_plan(df, plan)

    assert list(result.columns) == ["region", "sum_quantity"]
    assert len(result) == 3


# =========================================================
# QUERY ENGINE STAYS STORAGE/ENGINE-AGNOSTIC
# =========================================================


def test_query_engine_module_has_no_duckdb_import():
    source = inspect.getsource(query_engine_module)
    tree = ast.parse(source)

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.split(".")[0])

    assert "duckdb" not in imported_names
    assert not hasattr(query_engine_module, "duckdb")


def test_query_engine_module_has_no_raw_sql_or_storage_type_checks():
    source = inspect.getsource(query_engine_module)

    assert "SELECT" not in source.upper()
    assert "isinstance" not in source
    assert "Storage" not in source


# =========================================================
# STEP 12A - PANDAS RESULT-BOUNDARY HARDENING
#
# Grouped aggregation on the Pandas fallback path caps at
# DEFAULT_MAX_RESULT_ROWS when plan.limit is None, mirroring the
# DuckDB path's existing safety net (duckdb_query_engine.py). An
# explicit plan.limit remains authoritative either way.
# =========================================================


def test_pandas_grouped_aggregation_caps_result_when_limit_none_but_honors_explicit_limit():
    num_groups = DEFAULT_MAX_RESULT_ROWS + 500
    df = pd.DataFrame(
        {
            "region": [f"region_{i}" for i in range(num_groups)],
            "quantity": list(range(num_groups)),
        }
    )
    dataset = Dataset(storage=PandasStorage(df))

    uncapped_plan = AnalysisPlan(
        group_by=["region"], metric="quantity", aggregation="sum", limit=None
    )
    capped_result = execute_plan_for_dataset(dataset, uncapped_plan)

    assert capped_result.row_count == DEFAULT_MAX_RESULT_ROWS

    explicit_limit_plan = AnalysisPlan(
        group_by=["region"], metric="quantity", aggregation="sum", limit=5
    )
    limited_result = execute_plan_for_dataset(dataset, explicit_limit_plan)

    assert limited_result.row_count == 5
