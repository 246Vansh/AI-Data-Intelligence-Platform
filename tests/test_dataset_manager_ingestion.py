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

    dataset = manager.register_ingested_dataset(result, filename="orders.csv", owner_id="dev-user")

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

    dataset = manager.register_ingested_dataset(result, filename="ids.csv", owner_id="dev-user")

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
        manager.register_ingested_dataset(result, filename="orders.csv", owner_id="dev-user")

    # No half-registered dataset, and the orphaned Parquet fragment is
    # scrubbed rather than left behind.
    assert not manager.is_loaded()
    assert not os.path.exists(result.parquet_path)


# =========================================================
# Step 80: manifest-write failure rollback
# =========================================================


def _capture_storage(monkeypatch, close_error: Exception | None = None) -> list:
    """
    Let select_storage_for_ingestion build the real storage, but keep a
    handle on it - and optionally make its close() fail - so the test
    can check what rollback did with it.
    """

    import data_engine.dataset_manager as manager_module

    built: list = []
    real_select = manager_module.select_storage_for_ingestion

    def _select(result):
        storage = real_select(result)
        if close_error is not None:
            real_close = storage.close

            def _failing_close():
                built.append("close-attempted")
                raise close_error

            storage.close = _failing_close
            storage.real_close = real_close
        built.insert(0, storage)
        return storage

    monkeypatch.setattr(manager_module, "select_storage_for_ingestion", _select)
    return built


def _failing_write_manifest(**kwargs):
    # Leave a truncated manifest behind, as an interrupted write would.
    path = os.path.join(kwargs["storage_root"], f"{kwargs['dataset_id']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"dataset_id": ')
    raise OSError("simulated manifest write failure")


def test_manifest_failure_closes_storage_and_removes_artifacts(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)
    result = _ingest(tmp_path, "manifest_fail", "id,amount\n1,10\n")
    built = _capture_storage(monkeypatch)
    monkeypatch.setattr(
        "data_engine.dataset_manager.write_manifest", _failing_write_manifest
    )

    with pytest.raises(OSError, match="simulated manifest write failure"):
        manager.register_ingested_dataset(result, filename="orders.csv", owner_id="dev-user")

    storage = built[0]
    assert isinstance(storage, DuckDBStorage)
    assert storage._closed is True
    assert not os.path.exists(storage._temp_dir)

    assert not registry.exists("manifest_fail")
    assert not manager.is_loaded()
    assert not os.path.exists(result.parquet_path)
    assert not os.path.exists(os.path.join(str(tmp_path), "manifest_fail.json"))


def test_manifest_failure_is_not_masked_by_storage_close_failure(
    tmp_path, monkeypatch, caplog
):
    manager = DatasetManager(registry=DatasetRegistry())
    result = _ingest(tmp_path, "manifest_and_close_fail", "id,amount\n1,10\n")
    built = _capture_storage(monkeypatch, close_error=RuntimeError("simulated close failure"))
    monkeypatch.setattr(
        "data_engine.dataset_manager.write_manifest", _failing_write_manifest
    )
    cleaned: list = []
    import data_engine.dataset_manager as manager_module

    real_cleanup = manager_module._cleanup_parquet
    monkeypatch.setattr(
        manager_module,
        "_cleanup_parquet",
        lambda path: (cleaned.append(path), real_cleanup(path)),
    )

    try:
        with pytest.raises(OSError, match="simulated manifest write failure"):
            manager.register_ingested_dataset(
                result, filename="orders.csv", owner_id="dev-user"
            )

        assert "close-attempted" in built
        assert cleaned == [result.parquet_path]
        assert not manager.is_loaded()
        assert "during registration rollback" in caplog.text
    finally:
        built[0].real_close()


def test_successful_registration_keeps_storage_parquet_and_manifest(tmp_path):
    manager = DatasetManager(registry=DatasetRegistry())
    result = _ingest(tmp_path, "manifest_ok", "id,amount\n1,10\n2,20\n")

    dataset = manager.register_ingested_dataset(result, filename="ok.csv", owner_id="dev-user")

    assert dataset.row_count == 2
    assert os.path.exists(result.parquet_path)
    assert os.path.exists(os.path.join(str(tmp_path), "manifest_ok.json"))


def test_cleanup_failures_are_logged_without_masking_manifest_failure(
    tmp_path, monkeypatch, caplog
):
    manager = DatasetManager(registry=DatasetRegistry())
    result = _ingest(tmp_path, "cleanup_logged", "id,amount\n1,10\n")
    monkeypatch.setattr(
        "data_engine.dataset_manager.write_manifest", _failing_write_manifest
    )
    monkeypatch.setattr(
        "data_engine.dataset_manager.os.remove",
        lambda path: (_ for _ in ()).throw(PermissionError("simulated lock")),
    )

    with pytest.raises(OSError, match="simulated manifest write failure"):
        manager.register_ingested_dataset(result, filename="orders.csv", owner_id="dev-user")

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    messages = [r.getMessage() for r in warnings]
    assert any("cleanup_logged.parquet" in m for m in messages)
    assert any("cleanup_logged.json" in m for m in messages)
    assert all(r.exc_info and r.exc_info[0] is PermissionError for r in warnings)
    assert not manager.is_loaded()
