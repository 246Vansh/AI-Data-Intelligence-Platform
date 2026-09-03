"""Step 7: plan_executor.execute_plan_for_dataset() - storage-aware
dispatch that stops DuckDB-backed datasets from materializing a full
DataFrame just to apply raw filters / time-bucketing.

Verifies:
  - DuckDB-native filters and time-bucketing match historical Pandas
    behavior (execute_plan_for_dataset on a DuckDBStorage dataset vs.
    execute_plan() on an equivalent PandasStorage dataset).
  - All logical operators and all time granularities are processed
    accurately through the dataset-aware entry point.
  - Invalid filter/time columns are rejected the same way on both
    storage backends.
  - execute_plan_for_dataset() never calls storage.to_dataframe() when
    the dataset is DuckDB-backed - raw filtering/bucketing never
    requires a full-dataset materialization.
  - The Pandas fallback path (apply_filter/apply_time_granularity/
    execute_plan) is untouched and still used, unmodified, for
    PandasStorage-backed datasets.
  - The existing Pandas + Step 4/5/6 regression suites remain green.
"""

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.execution.result import ExecutionResult
from data_engine.plan_executor import execute_plan, execute_plan_for_dataset
from data_engine.storage import DuckDBStorage, PandasStorage


def _to_dataframe(execution_result: ExecutionResult) -> pd.DataFrame:
    """
    Test-only compatibility conversion: execute_plan_for_dataset() now
    returns an engine-neutral ExecutionResult. Existing assertions in
    this file compare against pandas DataFrames (execute_plan()'s
    direct return value), so results are converted back for the
    comparison rather than rewriting every assertion.
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


class _SpyPandasStorage(PandasStorage):
    """PandasStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# FILTERS - all logical operators, DuckDB vs. historical Pandas
# =========================================================


@pytest.mark.parametrize("operator,value", [
    ("=", "north"),
    ("!=", "north"),
])
def test_duckdb_string_filters_match_pandas(operator, value):
    df = _make_dataframe()
    plan = AnalysisPlan(
        filters=[FilterCondition(column="region", operator=operator, value=value)],
        metric="quantity",
        aggregation="sum",
    )

    duckdb_dataset = Dataset(storage=DuckDBStorage(df))
    duckdb_result = _to_dataframe(execute_plan_for_dataset(duckdb_dataset, plan))
    pandas_result = execute_plan(df, plan)

    pd.testing.assert_frame_equal(duckdb_result, pandas_result, check_dtype=False)


@pytest.mark.parametrize("operator,value", [
    (">", 20),
    (">=", 20),
    ("<", 40),
    ("<=", 40),
])
def test_duckdb_numeric_filters_match_pandas(operator, value):
    df = _make_dataframe()
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=operator, value=value)],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="asc",
        sort_by="metric",
    )

    duckdb_dataset = Dataset(storage=DuckDBStorage(df))
    duckdb_result = _to_dataframe(execute_plan_for_dataset(duckdb_dataset, plan))
    pandas_result = execute_plan(df, plan)

    pd.testing.assert_frame_equal(
        duckdb_result.sort_values("region").reset_index(drop=True),
        pandas_result.sort_values("region").reset_index(drop=True),
        check_dtype=False,
    )


# =========================================================
# TIME BUCKETING - all granularities, DuckDB vs. historical Pandas
# =========================================================


@pytest.mark.parametrize(
    "granularity", ["day", "week", "month", "quarter", "year"]
)
def test_duckdb_time_bucketing_matches_pandas_for_every_granularity(granularity):
    df = _make_dataframe()
    plan = AnalysisPlan(
        group_by=["signed_up_at"],
        metric="quantity",
        aggregation="sum",
        time_column="signed_up_at",
        time_granularity=granularity,
        sort="asc",
        sort_by="time",
    )

    duckdb_dataset = Dataset(storage=DuckDBStorage(df))
    duckdb_result = execute_plan_for_dataset(duckdb_dataset, plan)
    pandas_result = execute_plan(df, plan)

    assert duckdb_result.columns == list(pandas_result.columns)
    assert duckdb_result.row_count == len(pandas_result)
    assert [row["sum_quantity"] for row in duckdb_result.rows] == list(
        pandas_result["sum_quantity"]
    )


# =========================================================
# VALIDATION CONTRACT - invalid columns rejected on both backends
# =========================================================


def test_invalid_filter_column_rejected_on_both_backends():
    df = _make_dataframe()
    plan = AnalysisPlan(
        filters=[FilterCondition(column="does_not_exist", operator="=", value=1)],
        metric="quantity",
    )

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


def test_invalid_time_column_rejected_on_both_backends():
    df = _make_dataframe()
    plan = AnalysisPlan(
        metric="quantity",
        time_column="does_not_exist",
        time_granularity="month",
    )

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


def test_invalid_time_granularity_rejected_on_both_backends():
    df = _make_dataframe()
    plan = AnalysisPlan(
        metric="quantity",
        time_column="signed_up_at",
        time_granularity="fortnight",
    )

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)

    with pytest.raises(ValueError):
        execute_plan_for_dataset(Dataset(storage=PandasStorage(df)), plan)


# =========================================================
# BOUNDARY DISCIPLINE - zero to_dataframe() for DuckDB filtering
# =========================================================


def test_duckdb_backed_execution_never_materializes_full_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">", value=15)],
        group_by=["signed_up_at"],
        metric="quantity",
        aggregation="sum",
        time_column="signed_up_at",
        time_granularity="month",
    )

    execute_plan_for_dataset(dataset, plan)

    assert storage.to_dataframe_calls == []


# =========================================================
# PANDAS FALLBACK PATH REMAINS INTACT AND UNMODIFIED
# =========================================================


def test_pandas_backed_dataset_still_uses_to_dataframe_fallback():
    df = _make_dataframe()
    storage = _SpyPandasStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">", value=15)],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
    )

    result = _to_dataframe(execute_plan_for_dataset(dataset, plan))
    direct_result = execute_plan(df, plan)

    pd.testing.assert_frame_equal(result, direct_result)
    # The Pandas path is expected to materialize via to_dataframe() -
    # it is only DuckDB-backed datasets that skip it.
    assert storage.to_dataframe_calls == [True]


def test_direct_execute_plan_and_helpers_remain_unmodified():
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    result = execute_plan(df, plan)

    assert list(result.columns) == ["region", "sum_quantity"]
    assert len(result) == 3
