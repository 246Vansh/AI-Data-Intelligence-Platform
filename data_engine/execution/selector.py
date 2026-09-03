from __future__ import annotations

from data_engine.dataset import Dataset
from data_engine.execution.base import ExecutionEngine
from data_engine.execution.duckdb_engine import DuckDBExecutionEngine
from data_engine.execution.pandas_engine import PandasExecutionEngine
from data_engine.storage.duckdb_storage import DuckDBStorage
from data_engine.storage.pandas_storage import PandasStorage

# Stateless adapters - safe to share a single instance of each across
# every call rather than constructing one per dispatch.
_PANDAS_ENGINE = PandasExecutionEngine()
_DUCKDB_ENGINE = DuckDBExecutionEngine()


def select_engine_for(dataset: Dataset) -> ExecutionEngine:
    """
    Choose the ExecutionEngine matching a Dataset's own storage
    backend.

    This is the single place storage-type dispatch is allowed to
    happen. Neither PandasExecutionEngine nor DuckDBExecutionEngine
    ever branches on storage type inside execute() - picking the
    engine that matches a given storage backend is exactly what a
    selector/factory function is for, kept here so DuckDB-specific
    types stay confined to the execution package instead of leaking
    into callers such as plan_executor.py.

    Raises:
        TypeError: if dataset.storage is neither DuckDBStorage nor
            PandasStorage. Unsupported storage types must fail
            explicitly here rather than silently falling back to
            PandasExecutionEngine, which would either crash deeper in
            the call stack with a confusing error or - worse - execute
            successfully against the wrong engine.
    """
    if isinstance(dataset.storage, DuckDBStorage):
        return _DUCKDB_ENGINE

    if isinstance(dataset.storage, PandasStorage):
        return _PANDAS_ENGINE

    raise TypeError(
        "No ExecutionEngine is registered for storage type "
        f"{type(dataset.storage).__name__!r}. Supported storage types "
        "are DuckDBStorage and PandasStorage."
    )
