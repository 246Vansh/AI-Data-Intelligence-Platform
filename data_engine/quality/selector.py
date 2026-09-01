from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.quality.base import QualityEngine
from data_engine.quality.duckdb_quality import DuckDBQualityEngine
from data_engine.quality.pandas_quality import PandasQualityEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

# Stateless adapters - safe to share a single instance of each across
# every call rather than constructing one per dispatch.
_PANDAS_QUALITY_ENGINE = PandasQualityEngine()
_DUCKDB_QUALITY_ENGINE = DuckDBQualityEngine()


def select_quality_engine_for(dataset: Dataset) -> QualityEngine:
    """
    Choose the QualityEngine matching a Dataset's own storage backend.

    This is the single place storage-type dispatch is allowed to
    happen for dataset quality analysis - Dataset, dataset_manager.py,
    and route handlers stay completely free of any
    `if isinstance(storage, DuckDBStorage)` branching of their own.
    """
    if isinstance(dataset.storage, DuckDBStorage):
        return _DUCKDB_QUALITY_ENGINE

    return _PANDAS_QUALITY_ENGINE


def check_quality_for_dataset(dataset: Dataset) -> dict[str, Any]:
    """
    Compute quality analysis for a specific Dataset instance, using
    whichever QualityEngine matches its own storage backend.

    `dataset` must always be the specific Dataset instance to inspect
    - this function never resolves a "current" dataset through a
    global dataset manager, so multiple datasets can be inspected
    concurrently without cross-dataset crosstalk.
    """
    return select_quality_engine_for(dataset).check_quality(dataset)
