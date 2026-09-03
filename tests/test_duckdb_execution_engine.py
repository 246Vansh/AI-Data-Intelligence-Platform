"""Step 6: DuckDBExecutionEngine - native DuckDB execution behind the
ExecutionEngine contract.

Verifies:
  - DuckDBExecutionEngine inherits from ExecutionEngine.
  - It correctly handles filter + group_by + aggregation + sort + limit,
    matching the existing execute_plan_duckdb()/pandas execute_plan()
    results.
  - execute() never calls storage.to_dataframe() / never materializes
    the full dataset into pandas - only DuckDB-native SQL is used, with
    a DataFrame produced solely for the already-computed result.
  - The existing Pandas (Step 5) and Step 4 DuckDB suites remain
    unaffected by this addition.
"""

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.duckdb_query_engine import DEFAULT_MAX_RESULT_ROWS
from data_engine.execution import DuckDBExecutionEngine, ExecutionEngine
from data_engine.execution.result import ExecutionResult
from data_engine.plan_executor import execute_plan
from data_engine.storage import DuckDBStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
        }
    )


def _make_many_groups_dataframe(group_count: int) -> pd.DataFrame:
    # One row per distinct "region" group - the minimal shape needed to
    # exercise a grouped aggregation with `group_count` output rows,
    # keeping the fixture small/deterministic regardless of size.
    return pd.DataFrame(
        {
            "region": [f"region_{i}" for i in range(group_count)],
            "quantity": [1] * group_count,
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """
    Real DuckDBStorage (execute_plan_duckdb requires the concrete type)
    that additionally records whether to_dataframe() was ever invoked,
    so tests can prove the execution engine never materializes the
    full dataset into pandas.
    """

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# CONTRACT
# =========================================================


def test_duckdb_execution_engine_is_an_execution_engine():
    engine = DuckDBExecutionEngine()

    assert isinstance(engine, ExecutionEngine)
    assert hasattr(engine, "execute")


# =========================================================
# CORRECTNESS - filter, group_by, aggregation, sort, limit
# =========================================================


def test_duckdb_engine_handles_filter_group_by_agg_sort_limit():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">=", value=20)],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="desc",
        sort_by="metric",
        limit=2,
    )

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert isinstance(result, ExecutionResult)
    assert result.columns == ["region", "sum_quantity"]
    assert result.row_count == 2
    # south=30+40=70, east=50+60=110, north(only 20 survives filter)=20
    assert [row["region"] for row in result.rows] == ["east", "south"]
    assert [row["sum_quantity"] for row in result.rows] == [110, 70]


def test_duckdb_engine_global_aggregation_matches_pandas_path():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    engine = DuckDBExecutionEngine()
    duckdb_result = engine.execute(dataset, plan)
    pandas_result = execute_plan(df, plan)

    assert duckdb_result.columns == list(pandas_result.columns)
    assert duckdb_result.rows[0]["sum_quantity"] == pandas_result["sum_quantity"].iloc[0]


@pytest.mark.parametrize(
    "aggregation",
    ["sum", "mean", "median", "min", "max", "count"],
)
def test_duckdb_engine_supports_all_canonical_aggregations(aggregation):
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation=aggregation)

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert result.columns == ["region", f"{aggregation}_quantity"]
    assert result.row_count == 3


@pytest.mark.parametrize("operator", ["=", "!=", ">", ">=", "<", "<="])
def test_duckdb_engine_supports_all_logical_operators(operator):
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=operator, value=30)],
        metric="quantity",
        aggregation="count",
    )

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert result.columns == ["count_quantity"]


def test_duckdb_engine_rejects_unknown_metric_and_group_column():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))

    engine = DuckDBExecutionEngine()

    with pytest.raises(ValueError):
        engine.execute(dataset, AnalysisPlan(metric="does_not_exist"))

    with pytest.raises(ValueError):
        engine.execute(
            dataset,
            AnalysisPlan(group_by=["does_not_exist"], metric="quantity"),
        )


# =========================================================
# BOUNDARY DISCIPLINE - no to_dataframe(), no full materialization
# =========================================================


def test_duckdb_engine_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    engine = DuckDBExecutionEngine()
    engine.execute(dataset, plan)

    assert storage.to_dataframe_calls == []


# =========================================================
# RESULT-ROW SAFETY BOUND - DEFAULT_MAX_RESULT_ROWS
# =========================================================


def test_duckdb_engine_caps_unbounded_group_by_at_default_max_result_rows():
    df = _make_many_groups_dataframe(DEFAULT_MAX_RESULT_ROWS + 1)
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert result.row_count == DEFAULT_MAX_RESULT_ROWS


def test_duckdb_engine_preserves_explicit_limit_of_five():
    df = _make_many_groups_dataframe(DEFAULT_MAX_RESULT_ROWS + 1)
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        limit=5,
    )

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert result.row_count == 5


# =========================================================
# NO REGRESSIONS - Pandas + Step 4 DuckDB paths remain intact
# =========================================================


def test_pandas_execution_path_still_unaffected():
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    result = execute_plan(df, plan)

    assert list(result.columns) == ["region", "sum_quantity"]
    assert len(result) == 3
