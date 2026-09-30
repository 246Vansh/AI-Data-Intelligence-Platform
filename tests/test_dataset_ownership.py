"""
Step 54 - dataset ownership and authorization.

Covers owner_id on Dataset / DatasetManifest, its persistence through
startup recovery, safe handling of legacy (ownerless) manifests, and
owner-scoped access to the dataset and analysis routes.
"""

import io
import json
import os
from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from backend.dependencies import (
    DEFAULT_DEV_USER_ID,
    DEV_USER_ID_ENV_VAR,
    get_current_user,
)
from backend.main import _recover_datasets, app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_manifest import (
    LegacyManifestError,
    manifest_path_for,
    read_manifest,
    write_manifest,
)
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import ingest_to_parquet
from data_engine.storage import PandasStorage, StorageReference


USER_A = "user-a"
USER_B = "user-b"

CSV = b"region,revenue\nNorth,10\nSouth,20\n"


def _ingest(tmp_path, dataset_id="ds-1"):
    return ingest_to_parquet(
        source_stream=io.BytesIO(CSV),
        dataset_id=dataset_id,
        storage_root=str(tmp_path),
    )


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)

    return registry


@pytest.fixture
def client():
    return TestClient(app)


def _as_user(monkeypatch, user_id):
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, user_id)


def _upload(client, filename="sales.csv"):
    response = client.post(
        "/api/dataset/upload",
        files={"file": (filename, CSV, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()["dataset_id"]


# a. Dataset construction -------------------------------------------


def test_dataset_carries_owner_id():
    dataset = Dataset(storage=PandasStorage(pd.DataFrame({"a": [1]})), owner_id=USER_A)

    assert dataset.owner_id == USER_A


def test_dataset_without_owner_is_unowned():
    dataset = Dataset(storage=PandasStorage(pd.DataFrame({"a": [1]})))

    assert dataset.owner_id == ""


# Authentication boundary -------------------------------------------


def test_current_user_defaults_to_dev_user(monkeypatch):
    monkeypatch.delenv(DEV_USER_ID_ENV_VAR, raising=False)

    assert get_current_user().user_id == DEFAULT_DEV_USER_ID == "dev-user"


def test_current_user_read_from_environment(monkeypatch):
    _as_user(monkeypatch, USER_A)

    assert get_current_user().user_id == USER_A


# b. Manifest round-trip --------------------------------------------


def test_manifest_round_trip_includes_owner_id(tmp_path):
    created_at = datetime.now(timezone.utc)

    path = write_manifest(
        dataset_id="ds-rt",
        name="d.csv",
        created_at=created_at,
        storage=StorageReference.parquet(str(tmp_path / "ds-rt.parquet")),
        storage_root=str(tmp_path),
        owner_id=USER_A,
    )

    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["owner_id"] == USER_A

    manifest = read_manifest(path)
    assert manifest.owner_id == USER_A
    assert manifest.dataset_id == "ds-rt"
    assert manifest.created_at == created_at


def test_write_manifest_rejects_missing_owner(tmp_path):
    with pytest.raises(ValueError):
        write_manifest(
            dataset_id="ds-x",
            name=None,
            created_at=datetime.now(timezone.utc),
            storage=StorageReference.parquet(str(tmp_path / "ds-x.parquet")),
            storage_root=str(tmp_path),
            owner_id="",
        )

    assert not os.path.exists(manifest_path_for("ds-x", str(tmp_path)))


def test_register_ingested_dataset_persists_owner(tmp_path):
    manager = DatasetManager(registry=DatasetRegistry())

    dataset = manager.register_ingested_dataset(
        _ingest(tmp_path), filename="d.csv", owner_id=USER_A
    )

    assert dataset.owner_id == USER_A
    assert read_manifest(manifest_path_for("ds-1", str(tmp_path))).owner_id == USER_A


# c. Startup recovery -----------------------------------------------


def test_startup_recovery_preserves_owner_id(tmp_path):
    manager = DatasetManager(registry=DatasetRegistry())
    manager.register_ingested_dataset(_ingest(tmp_path), filename="d.csv", owner_id=USER_B)

    fresh_registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=fresh_registry)

    assert fresh_registry.get("ds-1").owner_id == USER_B


# i. Legacy manifests -----------------------------------------------


def _write_legacy_manifest(tmp_path, dataset_id):
    result = _ingest(tmp_path, dataset_id=dataset_id)
    path = manifest_path_for(dataset_id, str(tmp_path))

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "dataset_id": dataset_id,
                "name": "legacy.csv",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "parquet_path": result.parquet_path,
            },
            fh,
        )

    return path, result.parquet_path


def test_read_legacy_manifest_raises_explicit_error(tmp_path):
    path, _ = _write_legacy_manifest(tmp_path, "ds-legacy")

    with pytest.raises(LegacyManifestError):
        read_manifest(path)


def test_legacy_manifest_not_recovered_and_left_on_disk(tmp_path):
    manifest_path, parquet_path = _write_legacy_manifest(tmp_path, "ds-legacy")

    manager = DatasetManager(registry=DatasetRegistry())
    manager.register_ingested_dataset(
        _ingest(tmp_path, dataset_id="ds-owned"), filename="d.csv", owner_id=USER_A
    )

    registry = DatasetRegistry()
    _recover_datasets(storage_root=str(tmp_path), registry=registry)  # must not raise

    assert not registry.exists("ds-legacy")
    assert registry.get("ds-owned").owner_id == USER_A

    # Nothing is deleted or rewritten with an invented owner.
    assert os.path.exists(manifest_path)
    assert os.path.exists(parquet_path)
    with open(manifest_path, encoding="utf-8") as fh:
        assert "owner_id" not in json.load(fh)


# d-h. Route authorization ------------------------------------------


def test_upload_assigns_authenticated_owner(isolated, client, monkeypatch):
    _as_user(monkeypatch, USER_A)

    dataset_id = _upload(client)

    assert isolated.get(dataset_id).owner_id == USER_A


@pytest.mark.parametrize("suffix", ["", "/profile", "/preview", "/quality", "/metadata"])
def test_owner_can_access_dataset(isolated, client, monkeypatch, suffix):
    _as_user(monkeypatch, USER_A)
    dataset_id = _upload(client)

    response = client.get(f"/api/dataset/{dataset_id}{suffix}")

    assert response.status_code == 200
    assert "owner_id" not in response.json()


@pytest.mark.parametrize("suffix", ["", "/profile", "/preview", "/quality", "/metadata"])
def test_other_user_cannot_access_dataset(isolated, client, monkeypatch, suffix):
    _as_user(monkeypatch, USER_B)
    dataset_id = _upload(client)

    _as_user(monkeypatch, USER_A)
    response = client.get(f"/api/dataset/{dataset_id}{suffix}")

    # Indistinguishable from a dataset that doesn't exist.
    assert response.status_code == 404
    assert response.json() == {"detail": f"No dataset found for dataset_id: {dataset_id!r}"}


def test_unowned_dataset_is_not_accessible(isolated, client, monkeypatch):
    dataset = Dataset(storage=PandasStorage(pd.DataFrame({"a": [1]})))
    isolated.register(dataset)

    _as_user(monkeypatch, USER_A)

    assert client.get(f"/api/dataset/{dataset.dataset_id}").status_code == 404
    assert client.get("/api/dataset").json() == {"datasets": []}


def test_other_user_cannot_analyze_dataset(isolated, client, monkeypatch):
    _as_user(monkeypatch, USER_B)
    dataset_id = _upload(client)

    _as_user(monkeypatch, USER_A)
    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset_id, "question": "total revenue by region"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": f"No dataset found for dataset_id: {dataset_id!r}"}


def test_other_user_cannot_delete_dataset(isolated, client, monkeypatch):
    _as_user(monkeypatch, USER_B)
    dataset_id = _upload(client)

    _as_user(monkeypatch, USER_A)
    response = client.delete(f"/api/dataset/{dataset_id}")

    assert response.status_code == 404
    assert isolated.exists(dataset_id)

    _as_user(monkeypatch, USER_B)
    response = client.delete(f"/api/dataset/{dataset_id}")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Dataset deleted successfully.",
        "dataset_id": dataset_id,
    }
    assert not isolated.exists(dataset_id)


def test_dataset_listing_is_owner_scoped(isolated, client, monkeypatch):
    _as_user(monkeypatch, USER_A)
    a_id = _upload(client, "a.csv")

    _as_user(monkeypatch, USER_B)
    b_id = _upload(client, "b.csv")

    _as_user(monkeypatch, USER_A)
    listing = client.get("/api/dataset").json()["datasets"]
    assert [d["dataset_id"] for d in listing] == [a_id]
    assert "owner_id" not in listing[0]

    _as_user(monkeypatch, USER_B)
    listing = client.get("/api/dataset").json()["datasets"]
    assert [d["dataset_id"] for d in listing] == [b_id]


# i. Legacy active-dataset routes -----------------------------------
#
# GET /api/dataset/{profile,preview,quality,metadata} target the
# process-global active dataset. They must apply the same ownership
# check as the /{dataset_id}/... routes, and a foreign active dataset
# must look exactly like no dataset having been uploaded.

LEGACY_SUFFIXES = ["/profile", "/preview", "/quality", "/metadata"]
NO_DATASET = {"detail": "No dataset has been uploaded yet."}


@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_owner_can_access_active_dataset_via_legacy_route(
    isolated, client, monkeypatch, suffix
):
    _as_user(monkeypatch, USER_A)
    dataset_id = _upload(client)

    legacy = client.get(f"/api/dataset{suffix}")
    explicit = client.get(f"/api/dataset/{dataset_id}{suffix}")

    assert legacy.status_code == 200
    # Same response shape (and content) as the explicit-id route.
    assert legacy.json() == explicit.json()
    assert "owner_id" not in legacy.json()


def test_legacy_route_response_shapes_unchanged(isolated, client, monkeypatch):
    _as_user(monkeypatch, USER_A)
    _upload(client, "sales.csv")

    profile = client.get("/api/dataset/profile").json()
    assert set(profile) == {
        "rows", "columns", "column_names", "data_types", "missing_values",
        "duplicate_rows", "memory_usage_bytes", "column_details", "filename",
    }
    assert profile["filename"] == "sales.csv"
    assert profile["rows"] == 2

    preview = client.get("/api/dataset/preview").json()
    assert preview["filename"] == "sales.csv"


@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_other_users_active_dataset_not_exposed_via_legacy_route(
    isolated, client, monkeypatch, suffix
):
    _as_user(monkeypatch, USER_B)
    dataset_id = _upload(client, "secret.csv")

    _as_user(monkeypatch, USER_A)
    response = client.get(f"/api/dataset{suffix}")

    assert response.status_code == 404
    assert response.json() == NO_DATASET
    assert dataset_id not in response.text
    assert "secret.csv" not in response.text


@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_foreign_active_dataset_indistinguishable_from_none(
    isolated, client, monkeypatch, suffix
):
    _as_user(monkeypatch, USER_A)
    empty = client.get(f"/api/dataset{suffix}")

    _as_user(monkeypatch, USER_B)
    _upload(client)

    _as_user(monkeypatch, USER_A)
    foreign = client.get(f"/api/dataset{suffix}")

    assert (foreign.status_code, foreign.json()) == (empty.status_code, empty.json())
    assert empty.status_code == 404


@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_unowned_active_dataset_not_exposed_via_legacy_route(
    isolated, client, monkeypatch, suffix
):
    manager = dataset_route.dataset_manager
    manager.register_csv_bytes(CSV, filename="legacy.csv")  # no owner_id

    _as_user(monkeypatch, USER_A)
    response = client.get(f"/api/dataset{suffix}")

    assert response.status_code == 404
    assert response.json() == NO_DATASET
