"""
Tests for data_engine.execution.selector.select_engine_for - the single
storage -> ExecutionEngine dispatch boundary.

Covers:
  - DuckDBStorage / PandasStorage dispatch to their matching engines
  - storage subclasses dispatch to their parent's engine
  - unsupported storage types fail explicitly (no silent fallback)
  - execute_plan_for_dataset() routes through select_engine_for()
"""

from __future__ import annotations

import pandas as pd
import pytest

from data_engine import plan_executor
from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.execution import (
    DuckDBExecutionEngine,
    ExecutionEngine,
    ExecutionResult,
    PandasExecutionEngine,
    select_engine_for,
)
from data_engine.execution import selector as selector_module
from data_engine.storage import DatasetStorage, DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "south", "north"],
            "quantity": [10, 20, 30],
        }
    )


class _UnsupportedStorage(DatasetStorage):
    """A valid DatasetStorage no ExecutionEngine is registered for."""

    def to_dataframe(self) -> pd.DataFrame:
        raise AssertionError("an unsupported storage must never be read")

    def row_count(self) -> int:
        return 0

    def column_count(self) -> int:
        return 0

    def column_names(self) -> list[str]:
        return []

    def close(self) -> None:
        pass


class _DuckDBSubclassStorage(DuckDBStorage):
    pass


class _PandasSubclassStorage(PandasStorage):
    pass


# =========================================================
# DISPATCH
# =========================================================


def test_duckdb_storage_selects_duckdb_engine():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()))

    engine = select_engine_for(dataset)

    assert isinstance(engine, DuckDBExecutionEngine)


def test_pandas_storage_selects_pandas_engine():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))

    engine = select_engine_for(dataset)

    assert isinstance(engine, PandasExecutionEngine)


@pytest.mark.parametrize(
    "storage_cls,engine_cls",
    [
        (_DuckDBSubclassStorage, DuckDBExecutionEngine),
        (_PandasSubclassStorage, PandasExecutionEngine),
    ],
)
def test_storage_subclass_selects_parent_engine(storage_cls, engine_cls):
    dataset = Dataset(storage=storage_cls(_make_dataframe()))

    assert isinstance(select_engine_for(dataset), engine_cls)


def test_selector_returns_shared_stateless_engine_instances():
    first = select_engine_for(Dataset(storage=DuckDBStorage(_make_dataframe())))
    second = select_engine_for(Dataset(storage=DuckDBStorage(_make_dataframe())))

    assert first is second


def test_every_dispatch_row_maps_storage_to_execution_engine():
    assert selector_module._ENGINE_DISPATCH
    for storage_type, engine in selector_module._ENGINE_DISPATCH:
        assert issubclass(storage_type, DatasetStorage)
        assert isinstance(engine, ExecutionEngine)


# =========================================================
# UNSUPPORTED STORAGE - EXPLICIT FAILURE, NO FALLBACK
# =========================================================


def test_unsupported_storage_raises_type_error():
    dataset = Dataset(storage=_UnsupportedStorage())

    with pytest.raises(TypeError) as excinfo:
        select_engine_for(dataset)

    message = str(excinfo.value)
    assert "_UnsupportedStorage" in message
    assert "DuckDBStorage" in message
    assert "PandasStorage" in message


def test_unsupported_storage_never_reaches_an_engine_via_execute_plan_for_dataset():
    dataset = Dataset(storage=_UnsupportedStorage())
    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    with pytest.raises(TypeError, match="No ExecutionEngine is registered"):
        plan_executor.execute_plan_for_dataset(dataset, plan)


# =========================================================
# INTEGRATION - plan_executor ROUTES THROUGH THE SELECTOR
# =========================================================


def test_execute_plan_for_dataset_dispatches_through_select_engine_for(monkeypatch):
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    plan = AnalysisPlan(metric="quantity", aggregation="sum")
    sentinel = ExecutionResult(
        columns=["x"],
        row_count=1,
        truncated=False,
        _dataframe=pd.DataFrame({"x": [1]}),
    )
    calls: list[tuple] = []

    class _RecordingEngine(ExecutionEngine):
        def execute(self, dataset_reference, validated_plan):
            calls.append(("execute", dataset_reference, validated_plan))
            return sentinel

    def _fake_select(ds):
        calls.append(("select", ds))
        return _RecordingEngine()

    # execute_plan_for_dataset() imports select_engine_for lazily from
    # the data_engine.execution package, so patch it there.
    monkeypatch.setattr("data_engine.execution.select_engine_for", _fake_select)

    result = plan_executor.execute_plan_for_dataset(dataset, plan)

    assert result is sentinel
    assert calls == [("select", dataset), ("execute", dataset, plan)]
