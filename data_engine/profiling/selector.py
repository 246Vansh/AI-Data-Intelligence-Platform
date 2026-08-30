from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.profiling.base import ProfilingEngine
from data_engine.profiling.duckdb_profiling import DuckDBProfilingEngine
from data_engine.profiling.pandas_profiling import PandasProfilingEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

# Stateless adapters - safe to share a single instance of each across
# every call rather than constructing one per dispatch.
_PANDAS_PROFILING_ENGINE = PandasProfilingEngine()
_DUCKDB_PROFILING_ENGINE = DuckDBProfilingEngine()


def select_profiling_engine_for(dataset: Dataset) -> ProfilingEngine:
    """
    Choose the ProfilingEngine matching a Dataset's own storage
    backend.

    This is the single place storage-type dispatch is allowed to
    happen for dataset inspection statistics - Dataset, dataset_
    manager.py, and route handlers stay completely free of any
    `if isinstance(storage, DuckDBStorage)` branching of their own.
    """
    if isinstance(dataset.storage, DuckDBStorage):
        return _DUCKDB_PROFILING_ENGINE

    return _PANDAS_PROFILING_ENGINE


def basic_statistics_for_dataset(dataset: Dataset) -> dict[str, Any]:
    """
    Compute basic dataset inspection statistics (row/column counts,
    per-column missing-value tallies, distinct counts, min/max bounds,
    basic data types) for a specific Dataset instance, using whichever
    ProfilingEngine matches its own storage backend.

    `dataset` must always be the specific Dataset instance to inspect
    - this function never resolves a "current" dataset through a
    global dataset manager, so multiple datasets can be inspected
    concurrently without cross-dataset crosstalk.
    """
    return select_profiling_engine_for(dataset).basic_statistics(dataset)
