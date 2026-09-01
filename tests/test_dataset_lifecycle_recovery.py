"""Step 4: Restart & Durability.

R1 - manifest written on dataset creation.
R2 - manifest removed on dataset deletion.
R3 - startup recovery re-registers a dataset from manifest + parquet.
R4 - corrupt manifest JSON is skipped, not fatal.
R5 - missing parquet file is skipped, not fatal.
R6 - corrupt parquet file is skipped, not fatal.
R7 - dataset_id and created_at are preserved exactly across recovery.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd
import pytest

from backend.main import _recover_datasets
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_manifest import manifest_path_for, write_manifest
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import IngestionResult, ingest_to_parquet


def _ingest(tmp_path, dataset_id="ds-1", rows=b"a,b\n1,x\n2,y\n") -> IngestionResult:
    import io

    return ingest_to_parquet(
        source_stream=io.BytesIO(rows),
        dataset_id=dataset_id,
        storage_root=str(tmp_path),
    )


# R1 --------------------------------------------------------------


def test_manifest_written_on_dataset_creation(tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    result = _ingest(tmp_path)
    dataset = manager.register_ingested_dataset(result, filename="d.csv")

    manifest_path = manifest_path_for(dataset.dataset_id, str(tmp_path))
    assert os.path.exists(manifest_path)

    with open(manifest_path) as fh:
        payload = json.load(fh)

    assert payload["dataset_id"] == dataset.dataset_id
    assert payload["parquet_path"] == result.parquet_path


# R2 --------------------------------------------------------------


def test_manifest_removed_on_dataset_deletion(tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    result = _ingest(tmp_path)
    dataset = manager.register_ingested_dataset(result, filename="d.csv")
    manifest_path = manifest_path_for(dataset.dataset_id, str(tmp_path))

    assert os.path.exists(manifest_path)

    registry.delete(dataset.dataset_id)

    assert not os.path.exists(manifest_path)
    assert not os.path.exists(result.parquet_path)


# R3 --------------------------------------------------------------


def test_startup_recovery_reregisters_dataset(tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    result = _ingest(tmp_path)
    original = manager.register_ingested_dataset(result, filename="d.csv")

    fresh_registry = DatasetRegistry()  # simulates a new process
    _recover_datasets(storage_root=str(tmp_path), registry=fresh_registry)

    assert fresh_registry.exists(original.dataset_id)
    recovered = fresh_registry.get(original.dataset_id)
    assert recovered.storage.row_count() == 2
    assert recovered.storage.column_names() == ["a", "b"]


# R4 --------------------------------------------------------------


def test_recovery_skips_corrupt_manifest_json(tmp_path):
    (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)  # must not raise

    assert len(registry) == 0


# R5 --------------------------------------------------------------


def test_recovery_skips_missing_parquet(tmp_path):
    write_manifest(
        dataset_id="ds-missing",
        name="d.csv",
        created_at=datetime.now(timezone.utc),
        parquet_path=str(tmp_path / "ds-missing.parquet"),  # never created
        storage_root=str(tmp_path),
    )

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)

    assert not registry.exists("ds-missing")


# R6 --------------------------------------------------------------


def test_recovery_skips_corrupt_parquet(tmp_path):
    parquet_path = tmp_path / "ds-corrupt.parquet"
    parquet_path.write_bytes(b"not a real parquet file")

    write_manifest(
        dataset_id="ds-corrupt",
        name="d.csv",
        created_at=datetime.now(timezone.utc),
        parquet_path=str(parquet_path),
        storage_root=str(tmp_path),
    )

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)  # must not raise

    assert not registry.exists("ds-corrupt")


# R7 --------------------------------------------------------------


def test_recovery_preserves_dataset_id_and_created_at(tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    result = _ingest(tmp_path, dataset_id="ds-fixed-id")
    original = manager.register_ingested_dataset(result, filename="d.csv")

    fresh_registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=fresh_registry)

    recovered = fresh_registry.get("ds-fixed-id")
    assert recovered.dataset_id == original.dataset_id == "ds-fixed-id"
    assert recovered.created_at == original.created_at
