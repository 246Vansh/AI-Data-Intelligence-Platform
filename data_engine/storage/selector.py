from __future__ import annotations

from data_engine.ingestion import IngestionResult
from data_engine.storage.base import DatasetStorage
from data_engine.storage.duckdb_storage import DuckDBStorage


def select_storage_for_ingestion(result: IngestionResult) -> DatasetStorage:
    """
    Choose and build the DatasetStorage backend for a freshly ingested
    dataset (a Parquet file on disk, described by ``IngestionResult``).

    This is the single place storage-backend dispatch is allowed to
    happen for the ingestion -> registration path - mirroring
    ``data_engine.execution.selector.select_engine_for`` for execution
    engines. Callers (DatasetManager, and the upload route through it)
    never branch on storage/engine type themselves; they just hand this
    an IngestionResult and get back a ready-to-register DatasetStorage.

    Always DuckDBStorage today, built straight from the Parquet file
    via ``DuckDBStorage.from_parquet`` - no Pandas DataFrame of the
    full dataset is created to get there.
    """
    return DuckDBStorage.from_parquet(result.parquet_path)
