from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.metadata_engine.base import MetadataEngine
from data_engine.metadata_engine.duckdb_metadata import DuckDBMetadataEngine
from data_engine.metadata_engine.pandas_metadata import PandasMetadataEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

# Stateless adapters - safe to share a single instance of each across
# every call rather than constructing one per dispatch.
_PANDAS_METADATA_ENGINE = PandasMetadataEngine()
_DUCKDB_METADATA_ENGINE = DuckDBMetadataEngine()


def select_metadata_engine_for(dataset: Dataset) -> MetadataEngine:
    """
    Choose the MetadataEngine matching a Dataset's own storage
    backend.

    This is the single place storage-type dispatch is allowed to
    happen for dataset metadata - Dataset, dataset_manager.py, and
    route handlers stay completely free of any
    `if isinstance(storage, DuckDBStorage)` branching of their own.
    """
    if isinstance(dataset.storage, DuckDBStorage):
        return _DUCKDB_METADATA_ENGINE

    return _PANDAS_METADATA_ENGINE


def metadata_for_dataset(dataset: Dataset) -> dict[str, Any]:
    """
    Compute dataset metadata for a specific Dataset instance, using
    whichever MetadataEngine matches its own storage backend.

    `dataset` must always be the specific Dataset instance to inspect
    - this function never resolves a "current" dataset through a
    global dataset manager, so multiple datasets can be inspected
    concurrently without cross-dataset crosstalk.
    """
    return select_metadata_engine_for(dataset).get_metadata(dataset)
