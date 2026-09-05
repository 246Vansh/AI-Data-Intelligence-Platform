"""Step 13A/21: ExecutionResult - the engine-neutral boundary type returned
by ExecutionEngine.execute() implementations, replacing a raw pandas
DataFrame.

Step 21 makes the engine-produced DataFrame the canonical internal
representation: ExecutionResult is constructed from that DataFrame (not
a pre-built rows list). `.rows` becomes a lazily computed, cached
property, and `.to_dataframe()` returns the exact DataFrame object the
result was built from - never a rebuilt/copied one.

Verifies:
  - ExecutionResult can be constructed from a DataFrame.
  - `.columns` / `.row_count` / `.truncated` behave exactly as before.
  - `.rows` is lazy: constructing an ExecutionResult never converts the
    DataFrame to records; the conversion happens once, on first `.rows`
    access, and is cached for every later access.
  - `.to_dataframe()` returns the canonical DataFrame object itself.
  - DuckDBExecutionEngine.execute() and PandasExecutionEngine.execute()
    still return an ExecutionResult with the same observable values.
  - Neither engine claims `truncated=True` without a provable signal
    (execute_plan_duckdb()/execute_plan() don't track it today).
"""

import dataclasses
from unittest import mock

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.execution import DuckDBExecutionEngine, PandasExecutionEngine
from data_engine.execution.result import ExecutionResult
from data_engine.storage import DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south"],
            "quantity": [10, 20, 30, 40],
        }
    )


def _make_grouped_dataframe() -> pd.DataFrame:
    return pd.DataFrame({"region": ["north", "south"], "sum_quantity": [30, 70]})


# =========================================================
# CONSTRUCTION FROM A DATAFRAME
# =========================================================


def test_execution_result_can_be_constructed_from_a_dataframe():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=["region", "sum_quantity"],
        row_count=2,
        truncated=False,
        _dataframe=df,
    )

    assert isinstance(result, ExecutionResult)


def test_columns_matches_dataframe_columns():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=df.columns.tolist(),
        row_count=len(df),
        truncated=False,
        _dataframe=df,
    )

    assert result.columns == ["region", "sum_quantity"]


def test_row_count_matches_dataframe_length():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=df.columns.tolist(),
        row_count=len(df),
        truncated=False,
        _dataframe=df,
    )

    assert result.row_count == len(df) == 2


def test_truncated_behavior_unchanged():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=df.columns.tolist(),
        row_count=len(df),
        truncated=False,
        _dataframe=df,
    )

    assert result.truncated is False


def test_execution_result_is_frozen():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=df.columns.tolist(),
        row_count=len(df),
        truncated=False,
        _dataframe=df,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.row_count = 5


def test_execution_result_rejects_negative_row_count():
    df = _make_grouped_dataframe()

    with pytest.raises(ValueError):
        ExecutionResult(columns=[], row_count=-1, truncated=False, _dataframe=df)


# =========================================================
# LAZY, CACHED .rows
# =========================================================


def test_rows_is_lazy_and_cached():
    df = _make_grouped_dataframe()
    expected_rows = df.to_dict(orient="records")

    call_count = {"n": 0}
    original_to_dict = pd.DataFrame.to_dict

    def _spy_to_dict(self, *args, **kwargs):
        call_count["n"] += 1
        return original_to_dict(self, *args, **kwargs)

    with mock.patch.object(pd.DataFrame, "to_dict", _spy_to_dict):
        result = ExecutionResult(
            columns=df.columns.tolist(),
            row_count=len(df),
            truncated=False,
            _dataframe=df,
        )

        # Construction itself must never have converted the DataFrame.
        assert call_count["n"] == 0

        first_access = result.rows
        assert call_count["n"] == 1
        assert first_access == expected_rows

        second_access = result.rows
        # Cached - no second conversion, same list object returned.
        assert call_count["n"] == 1
        assert second_access is first_access


def test_to_dataframe_returns_the_canonical_dataframe_object():
    df = _make_grouped_dataframe()

    result = ExecutionResult(
        columns=df.columns.tolist(),
        row_count=len(df),
        truncated=False,
        _dataframe=df,
    )

    assert result.to_dataframe() is df


# =========================================================
# ENGINE PARITY - unchanged observable behavior
# =========================================================


def test_duckdb_engine_returns_execution_result():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    engine = DuckDBExecutionEngine()
    result = engine.execute(dataset, plan)

    assert isinstance(result, ExecutionResult)
    assert result.columns == ["region", "sum_quantity"]
    assert result.row_count == 2
    assert result.truncated is False
    assert result.rows == result.to_dataframe().to_dict(orient="records")


def test_pandas_engine_returns_execution_result():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    engine = PandasExecutionEngine()
    result = engine.execute(dataset, plan)

    assert isinstance(result, ExecutionResult)
    assert result.columns == ["region", "sum_quantity"]
    assert result.row_count == 2
    assert result.truncated is False
    assert result.rows == result.to_dataframe().to_dict(orient="records")
