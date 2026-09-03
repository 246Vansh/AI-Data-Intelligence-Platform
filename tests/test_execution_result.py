"""Step 13A: ExecutionResult - the engine-neutral boundary type returned
by ExecutionEngine.execute() implementations, replacing a raw pandas
DataFrame.

Verifies:
  - ExecutionResult exposes exactly the four documented fields.
  - DuckDBExecutionEngine.execute() returns an ExecutionResult.
  - PandasExecutionEngine.execute() returns an ExecutionResult.
  - Neither engine claims `truncated=True` without a provable signal
    (execute_plan_duckdb()/execute_plan() don't track it today).
"""

import dataclasses

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


def test_execution_result_has_exactly_the_documented_fields():
    result = ExecutionResult(
        columns=["region", "sum_quantity"],
        rows=[{"region": "north", "sum_quantity": 30}],
        row_count=1,
        truncated=False,
    )

    assert result.columns == ["region", "sum_quantity"]
    assert result.rows == [{"region": "north", "sum_quantity": 30}]
    assert result.row_count == 1
    assert result.truncated is False


def test_execution_result_is_frozen():
    result = ExecutionResult(columns=[], rows=[], row_count=0, truncated=False)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.row_count = 5


def test_execution_result_rejects_negative_row_count():
    with pytest.raises(ValueError):
        ExecutionResult(columns=[], rows=[], row_count=-1, truncated=False)


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
