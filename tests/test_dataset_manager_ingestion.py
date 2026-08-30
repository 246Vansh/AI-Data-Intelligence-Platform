"""Step 10: DatasetManager registers ingested (Parquet) datasets.

``register_ingested_dataset`` is the DatasetManager-tier counterpart to
the existing ``register_csv_bytes`` - but its input is an
``IngestionResult`` (a persistent Parquet reference) rather than raw
CSV bytes, and it never builds a full-source Pandas DataFrame to do the
registration. Storage-backend choice is delegated to
``select_storage_for_ingestion`` (the storage/selector tier) - this
module contains no engine-specific type check of its own.
"""

import io
import os

import pytest

from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import ingest_to_parquet
from data_engine.storage import DuckDBStorage


def _csv_stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def _ingest(tmp_path, dataset_id: str, csv_text: str):
    return ingest_to_parquet(
        source_stream=_csv_stream(csv_text),
        dataset_id=dataset_id,
        storage_root=str(tmp_path),
    )


def test_register_ingested_dataset_becomes_active_and_duckdb_backed(tmp_path):
    manager = DatasetManager(registry=DatasetRegistry())
    result = _ingest(tmp_path, "manager_ds", "id,amount\n1,10\n2,20\n3,30\n")

    dataset = manager.register_ingested_dataset(result, filename="orders.csv")

    assert dataset.dataset_id == "manager_ds"
    assert isinstance(dataset.storage, DuckDBStorage)
    assert dataset.row_count == 3
    assert dataset.column_count == 2
    assert manager.get_filename() == "orders.csv"
    assert manager.is_loaded()
    assert manager.get_dataframe()["amount"].sum() == 60


def test_register_ingested_dataset_is_discoverable_via_registry(tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)
    result = _ingest(tmp_path, "manager_ds_registry", "id\n1\n2\n")

    dataset = manager.register_ingested_dataset(result, filename="ids.csv")

    assert registry.exists("manager_ds_registry")
    assert registry.get("manager_ds_registry") is dataset


def test_register_ingested_dataset_cleans_up_parquet_on_storage_failure(tmp_path, monkeypatch):
    manager = DatasetManager(registry=DatasetRegistry())
    result = _ingest(tmp_path, "manager_fail", "id,amount\n1,10\n")

    def _boom(_result):
        raise RuntimeError("simulated storage build failure")

    monkeypatch.setattr(
        "data_engine.dataset_manager.select_storage_for_ingestion", _boom
    )

    with pytest.raises(RuntimeError, match="simulated storage build failure"):
        manager.register_ingested_dataset(result, filename="orders.csv")

    # No half-registered dataset, and the orphaned Parquet fragment is
    # scrubbed rather than left behind.
    assert not manager.is_loaded()
    assert not os.path.exists(result.parquet_path)
