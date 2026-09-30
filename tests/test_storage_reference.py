"""
Step 58 - storage-reference abstraction.

DatasetManifest now persists a StorageReference ({"type", "location"})
instead of a bare "parquet_path"; startup recovery opens it through
data_engine.storage.open_storage. Local-Parquet behavior is unchanged,
and legacy parquet_path manifests are still read as type "parquet".
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routes.dataset as dataset_route
from backend.dependencies import DEV_USER_ID_ENV_VAR
from backend.main import _recover_datasets, app
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_manifest import (
    LegacyManifestError,
    manifest_path_for,
    read_manifest,
    write_manifest,
)
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import ingest_to_parquet
from data_engine.storage import (
    DuckDBStorage,
    StorageReference,
    StorageReferenceError,
    UnsupportedStorageTypeError,
    open_storage,
    storage_reference_for_ingestion,
)

client = TestClient(app)

VALID_CSV = b"id,name,amount\n1,alice,10.5\n2,bob,20.0\n3,carol,30.25\n"
OWNER = "user-a"


def _ingest(tmp_path, dataset_id="ds-1", rows=b"a,b\n1,x\n2,y\n"):
    return ingest_to_parquet(
        source_stream=io.BytesIO(rows),
        dataset_id=dataset_id,
        storage_root=str(tmp_path),
    )


def _write_raw_manifest(tmp_path, dataset_id, **fields):
    payload = {
        "dataset_id": dataset_id,
        "owner_id": OWNER,
        "name": "d.csv",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    payload = {k: v for k, v in payload.items() if v is not ...}
    path = manifest_path_for(dataset_id, str(tmp_path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path / "parquet"))
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)
    return registry


# Serialization -----------------------------------------------------


def test_storage_reference_round_trip():
    ref = StorageReference.parquet("/data/ds-1.parquet")

    assert ref.to_dict() == {"type": "parquet", "location": "/data/ds-1.parquet"}
    assert StorageReference.from_dict(ref.to_dict()) == ref


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "parquet",
        {"type": "parquet"},
        {"location": "/x.parquet"},
        {"type": "", "location": "/x.parquet"},
        {"type": "parquet", "location": ""},
        {"type": 1, "location": "/x.parquet"},
    ],
)
def test_malformed_storage_reference_rejected(payload):
    with pytest.raises(StorageReferenceError):
        StorageReference.from_dict(payload)


def test_open_storage_rejects_unsupported_type():
    with pytest.raises(UnsupportedStorageTypeError):
        open_storage(StorageReference(type="iceberg", location="s3://b/t"))


# Upload / manifest format -----------------------------------------


def test_register_ingested_dataset_writes_new_manifest_format(tmp_path):
    result = _ingest(tmp_path)
    DatasetManager(registry=DatasetRegistry()).register_ingested_dataset(
        result, filename="d.csv", owner_id=OWNER
    )

    assert result.parquet_path == os.path.join(str(tmp_path), "ds-1.parquet")
    assert os.path.exists(result.parquet_path)

    with open(manifest_path_for("ds-1", str(tmp_path)), encoding="utf-8") as fh:
        payload = json.load(fh)

    assert set(payload) == {"dataset_id", "owner_id", "name", "created_at", "storage"}
    assert payload["storage"] == {"type": "parquet", "location": result.parquet_path}
    assert payload["owner_id"] == OWNER
    assert storage_reference_for_ingestion(result) == StorageReference.parquet(result.parquet_path)


def test_upload_api_unchanged_and_manifest_uses_storage_reference(isolated_registry, monkeypatch):
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, OWNER)

    response = client.post(
        "/api/dataset/upload", files={"file": ("orders.csv", VALID_CSV, "text/csv")}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "filename", "rows", "columns", "dataset_id"}
    assert (body["filename"], body["rows"], body["columns"]) == ("orders.csv", 3, 3)

    root = dataset_route.PARQUET_STORAGE_ROOT
    parquet_path = os.path.join(root, f"{body['dataset_id']}.parquet")
    assert os.path.exists(parquet_path)
    assert isinstance(isolated_registry.get(body["dataset_id"]).storage, DuckDBStorage)

    manifest = read_manifest(manifest_path_for(body["dataset_id"], root))
    assert manifest.storage == StorageReference.parquet(parquet_path)
    assert manifest.owner_id == OWNER


# Legacy manifests -------------------------------------------------


def test_legacy_parquet_path_manifest_read_as_parquet_reference(tmp_path):
    result = _ingest(tmp_path)
    path = _write_raw_manifest(tmp_path, "ds-1", parquet_path=result.parquet_path)

    manifest = read_manifest(path)

    assert manifest.storage == StorageReference.parquet(result.parquet_path)
    assert manifest.owner_id == OWNER


def test_legacy_manifest_recovered_with_owner_preserved(tmp_path):
    result = _ingest(tmp_path)
    _write_raw_manifest(tmp_path, "ds-1", parquet_path=result.parquet_path)

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)

    recovered = registry.get("ds-1")
    assert recovered.owner_id == OWNER
    assert recovered.storage.row_count() == 2


def test_legacy_manifest_without_owner_still_not_assigned_one(tmp_path):
    result = _ingest(tmp_path)
    path = _write_raw_manifest(tmp_path, "ds-1", owner_id=..., parquet_path=result.parquet_path)

    with pytest.raises(LegacyManifestError):
        read_manifest(path)

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)
    assert not registry.exists("ds-1")
    assert os.path.exists(path) and os.path.exists(result.parquet_path)


def test_manifest_with_both_storage_and_parquet_path_rejected(tmp_path):
    result = _ingest(tmp_path)
    path = _write_raw_manifest(
        tmp_path,
        "ds-1",
        parquet_path=result.parquet_path,
        storage={"type": "parquet", "location": result.parquet_path},
    )

    with pytest.raises(ValueError):
        read_manifest(path)


# Recovery ---------------------------------------------------------


def test_recovery_reopens_parquet_dataset_with_owner(tmp_path):
    result = _ingest(tmp_path)
    original = DatasetManager(registry=DatasetRegistry()).register_ingested_dataset(
        result, filename="d.csv", owner_id=OWNER
    )

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)

    recovered = registry.get("ds-1")
    assert isinstance(recovered.storage, DuckDBStorage)
    assert recovered.storage.artifact_path == result.parquet_path
    assert recovered.storage.column_names() == ["a", "b"]
    assert recovered.owner_id == OWNER
    assert recovered.created_at == original.created_at


def test_recovery_skips_unsupported_storage_type(tmp_path):
    _write_raw_manifest(tmp_path, "ds-ice", storage={"type": "iceberg", "location": "s3://b/t"})
    good = _ingest(tmp_path, dataset_id="ds-good")
    write_manifest(
        dataset_id="ds-good",
        name="g.csv",
        created_at=datetime.now(timezone.utc),
        storage=StorageReference.parquet(good.parquet_path),
        storage_root=str(tmp_path),
        owner_id=OWNER,
    )

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)  # must not raise

    assert not registry.exists("ds-ice")
    assert registry.exists("ds-good")


@pytest.mark.parametrize(
    "storage",
    ["not-an-object", {"type": "parquet"}, {"type": "", "location": "x"}, None],
)
def test_recovery_skips_malformed_storage_reference(tmp_path, storage):
    _write_raw_manifest(tmp_path, "ds-bad", storage=storage)

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)  # must not raise

    assert len(registry) == 0


# Deletion ---------------------------------------------------------


def test_delete_removes_artifact_and_manifest(tmp_path):
    registry = DatasetRegistry()
    result = _ingest(tmp_path)
    DatasetManager(registry=registry).register_ingested_dataset(
        result, filename="d.csv", owner_id=OWNER
    )
    manifest_path = manifest_path_for("ds-1", str(tmp_path))
    assert os.path.exists(manifest_path)

    registry.delete("ds-1")

    assert not os.path.exists(result.parquet_path)
    assert not os.path.exists(manifest_path)
