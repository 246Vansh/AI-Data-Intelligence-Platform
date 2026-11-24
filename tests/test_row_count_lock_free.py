"""R1 (backend performance audit): row counts without the storage lock.

DuckDBStorage serializes every query on its instance lock, and a
first-time profile/quality scan can hold that lock for minutes. Dataset
listing and upload responses only need the row count, which is fixed at
upload (datasets never change), so reading it must never wait for that
lock:

  - upload reuses the count ingestion already made (no re-query);
  - startup recovery counts once while opening, before the storage is
    shared;
  - DuckDBStorage.row_count() returns the stored value without taking
    the lock, and still raises StorageClosedError once closed.

Lock-freedom is tested directly: another thread holds the storage's
lock while the count is read, and the read must finish within a
deadline instead of waiting for that thread.
"""

from __future__ import annotations

import io
import os
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import backend.routes.dataset as dataset_route
import data_engine.dataset_manager as dataset_manager_module
from backend.dependencies import DEFAULT_DEV_USER_ID
from backend.main import _recover_datasets, app
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import ingest_to_parquet
from data_engine.storage import DuckDBStorage, StorageClosedError

ROWS = 7
CSV = ("id,region,amount\n" + "".join(f"{i},r{i % 3},{i * 1.5}\n" for i in range(ROWS))).encode()

# Generous: a lock-free read takes milliseconds. A regression would
# block until the holder releases, i.e. forever without this deadline.
DEADLINE_SECONDS = 10

client = TestClient(app)


@contextmanager
def lock_held_elsewhere(storage: DuckDBStorage):
    """Hold `storage`'s instance lock in another thread for the block."""

    acquired = threading.Event()
    release = threading.Event()

    def hold():
        with storage._lock:
            acquired.set()
            release.wait()

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert acquired.wait(DEADLINE_SECONDS), "holder thread never took the lock"

    try:
        yield
    finally:
        release.set()
        holder.join(DEADLINE_SECONDS)


def call_within_deadline(fn):
    """Run fn() in a thread; fail (instead of hanging) if it blocks."""

    outcome = {}

    def run():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # surfaced below
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(DEADLINE_SECONDS)

    assert not worker.is_alive(), "blocked on the storage lock held by another thread"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _ingest(tmp_path, dataset_id="ds-r1"):
    return ingest_to_parquet(
        source_stream=io.BytesIO(CSV),
        dataset_id=dataset_id,
        storage_root=str(tmp_path),
    )


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))

    yield registry, manager

    for dataset in registry.list():
        registry.delete(dataset.dataset_id)


# =========================================================
# Upload
# =========================================================


def test_upload_response_row_count_is_correct(isolated):
    response = client.post("/api/dataset/upload", files={"file": ("d.csv", CSV, "text/csv")})

    assert response.status_code == 200
    assert response.json()["rows"] == ROWS


def test_upload_reuses_ingestion_row_count_without_the_lock(isolated, monkeypatch):
    real_select = dataset_manager_module.select_storage_for_ingestion
    built = {}
    holders = []

    # Hold the new storage's lock from the moment it is built, so the
    # upload response can only be produced if reading its row count
    # neither queries nor locks.
    def select_and_lock(result):
        storage = real_select(result)
        built["storage"] = storage
        holder = lock_held_elsewhere(storage)
        holder.__enter__()
        holders.append(holder)
        return storage

    monkeypatch.setattr(dataset_manager_module, "select_storage_for_ingestion", select_and_lock)

    try:
        response = call_within_deadline(
            lambda: client.post("/api/dataset/upload", files={"file": ("d.csv", CSV, "text/csv")})
        )
    finally:
        for holder in holders:
            holder.__exit__(None, None, None)

    assert response.status_code == 200
    assert response.json()["rows"] == ROWS
    assert built["storage"]._row_count == ROWS


# =========================================================
# Listing
# =========================================================


def test_listing_returns_row_count_while_storage_lock_is_held(isolated, tmp_path):
    _registry, manager = isolated
    dataset = manager.register_ingested_dataset(
        _ingest(tmp_path), filename="d.csv", owner_id=DEFAULT_DEV_USER_ID
    )

    with lock_held_elsewhere(dataset.storage):
        response = call_within_deadline(lambda: client.get("/api/dataset"))

    assert response.status_code == 200
    entries = response.json()["datasets"]
    assert [(entry["dataset_id"], entry["rows"]) for entry in entries] == [
        (dataset.dataset_id, ROWS)
    ]


def test_dataset_by_id_returns_row_count_while_storage_lock_is_held(isolated, tmp_path):
    _registry, manager = isolated
    dataset = manager.register_ingested_dataset(
        _ingest(tmp_path), filename="d.csv", owner_id=DEFAULT_DEV_USER_ID
    )

    with lock_held_elsewhere(dataset.storage):
        response = call_within_deadline(lambda: client.get(f"/api/dataset/{dataset.dataset_id}"))

    assert response.status_code == 200
    assert response.json()["rows"] == ROWS


# =========================================================
# Startup recovery
# =========================================================


def test_restored_dataset_has_correct_row_count_without_the_lock(tmp_path):
    manager = DatasetManager(registry=DatasetRegistry())
    original = manager.register_ingested_dataset(
        _ingest(tmp_path), filename="d.csv", owner_id=DEFAULT_DEV_USER_ID
    )

    fresh = DatasetRegistry()  # a new process
    _recover_datasets(storage_root=str(tmp_path), registry=fresh)
    recovered = fresh.get(original.dataset_id)

    try:
        with lock_held_elsewhere(recovered.storage):
            assert call_within_deadline(lambda: recovered.row_count) == ROWS
    finally:
        recovered.storage.close()
        original.storage.close()


# =========================================================
# DuckDBStorage contract
# =========================================================


def test_from_parquet_counts_rows_when_not_given(tmp_path):
    result = _ingest(tmp_path)
    storage = DuckDBStorage.from_parquet(result.parquet_path)

    try:
        assert storage.row_count() == ROWS == result.row_count
    finally:
        storage.close()


def test_dataframe_backed_storage_row_count_is_lock_free():
    import pandas as pd

    storage = DuckDBStorage(pd.DataFrame({"a": [1, 2, 3]}))

    try:
        with lock_held_elsewhere(storage):
            assert call_within_deadline(storage.row_count) == 3
    finally:
        storage.close()


def test_row_count_still_raises_once_closed(tmp_path):
    storage = DuckDBStorage.from_parquet(_ingest(tmp_path).parquet_path)
    storage.close()

    with pytest.raises(StorageClosedError):
        storage.row_count()


@pytest.mark.parametrize("bad", [-1, 1.5, "7", True])
def test_from_parquet_rejects_invalid_row_count(tmp_path, bad):
    with pytest.raises(ValueError):
        DuckDBStorage.from_parquet(_ingest(tmp_path).parquet_path, row_count=bad)


def test_failed_open_releases_its_spill_directory(tmp_path, monkeypatch):
    spill_root = tmp_path / "spill"
    spill_root.mkdir()
    monkeypatch.setenv("DUCKDB_TEMP_ROOT", str(spill_root))

    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_bytes(b"not a parquet file")

    with pytest.raises(Exception):
        DuckDBStorage.from_parquet(str(corrupt))

    assert os.listdir(spill_root) == []
