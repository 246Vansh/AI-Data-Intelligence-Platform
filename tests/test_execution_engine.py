"""Step 5: ExecutionEngine abstraction + PandasExecutionEngine adapter.

Verifies:
  - ExecutionEngine is a genuine abstract contract (cannot be
    instantiated directly; a subclass missing execute() can't either).
  - PandasExecutionEngine satisfies the contract and produces results
    identical to calling plan_executor.execute_plan() directly - the
    adapter adds no query logic of its own.
  - The adapter reads dataset contents strictly through
    dataset.storage.to_dataframe() - never a `.dataframe` attribute,
    never an isinstance/type check on the concrete storage backend.
  - The existing Pandas production path (plan_executor/query_engine)
    remains completely unmodified and independently correct.
"""

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.execution import ExecutionEngine, PandasExecutionEngine
from data_engine.plan_executor import execute_plan
from data_engine.storage import DatasetStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
        }
    )


class _RecordingStorage(DatasetStorage):
    """
    Storage stand-in that records exactly which DatasetStorage methods
    are called on it, so tests can prove the execution engine only
    ever pulls data through `to_dataframe()`.
    """

    def __init__(self, dataframe: pd.DataFrame):
        self._dataframe = dataframe
        self.calls: list[str] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.calls.append("to_dataframe")
        return self._dataframe

    def row_count(self) -> int:
        self.calls.append("row_count")
        return len(self._dataframe)

    def column_count(self) -> int:
        self.calls.append("column_count")
        return len(self._dataframe.columns)

    def column_names(self) -> list[str]:
        self.calls.append("column_names")
        return self._dataframe.columns.tolist()

    def close(self) -> None:
        self.calls.append("close")


# =========================================================
# CONTRACT / ABSTRACTNESS
# =========================================================


def test_execution_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ExecutionEngine()


def test_incomplete_subclass_cannot_be_instantiated():
    class IncompleteEngine(ExecutionEngine):
        pass

    with pytest.raises(TypeError):
        IncompleteEngine()


def test_pandas_execution_engine_is_an_execution_engine():
    engine = PandasExecutionEngine()

    assert isinstance(engine, ExecutionEngine)
    assert hasattr(engine, "execute")


# =========================================================
# ADAPTER CORRECTNESS - matches execute_plan() exactly
# =========================================================


def test_pandas_engine_matches_direct_execute_plan_global_aggregation():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))
    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    engine = PandasExecutionEngine()
    engine_result = engine.execute(dataset, plan)
    direct_result = execute_plan(df, plan)

    assert engine_result.columns == list(direct_result.columns)
    assert engine_result.rows == direct_result.to_dict(orient="records")
    assert engine_result.row_count == len(direct_result)


def test_pandas_engine_matches_direct_execute_plan_group_by_filter_sort_limit():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))
    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">=", value=20)],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="desc",
        sort_by="metric",
        limit=2,
    )

    engine = PandasExecutionEngine()
    engine_result = engine.execute(dataset, plan)
    direct_result = execute_plan(df, plan)

    assert engine_result.columns == list(direct_result.columns)
    assert engine_result.rows == direct_result.to_dict(orient="records")
    assert engine_result.row_count == 2


def test_pandas_engine_result_footprint_has_expected_columns():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))
    plan = AnalysisPlan(group_by=["category"], metric="quantity", aggregation="mean")

    engine = PandasExecutionEngine()
    result = engine.execute(dataset, plan)

    assert result.columns == ["category", "mean_quantity"]
    assert result.row_count == 2


# =========================================================
# BOUNDARY DISCIPLINE - storage contract only, no leaks
# =========================================================


def test_pandas_engine_reads_dataset_strictly_through_storage_contract():
    df = _make_dataframe()
    storage = _RecordingStorage(df)
    dataset = Dataset(storage=storage)
    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    engine = PandasExecutionEngine()
    engine.execute(dataset, plan)

    # Only the compatibility boundary method was touched - no
    # row_count/column_count/column_names probing, and (structurally)
    # no access to a `.dataframe` attribute, which _RecordingStorage
    # doesn't even define.
    assert storage.calls == ["to_dataframe"]


def test_dataset_object_has_no_dataframe_attribute_for_engine_to_misuse():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    assert not hasattr(dataset, "dataframe")


# =========================================================
# PRODUCTION PATH UNCHANGED
# =========================================================


def test_direct_execute_plan_still_works_unmodified():
    df = _make_dataframe()
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    result = execute_plan(df, plan)

    assert list(result.columns) == ["region", "sum_quantity"]
    assert len(result) == 3
