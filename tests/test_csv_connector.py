"""
Step 57 - minimal connector abstraction around the existing ingestion
boundary.

Covers CSVConnector's validation and its delegation to
data_engine.ingestion.ingest_to_parquet, and that the upload route -
now going through CSVConnector - keeps its response shape, ownership,
registration and cleanup behavior.
"""

import glob
import os
import tempfile

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routes.dataset as dataset_route
import data_engine.connectors.csv_connector as csv_connector_module
import data_engine.dataset_manager as dataset_manager_module
from backend.dependencies import DEV_USER_ID_ENV_VAR
from backend.main import app
from data_engine.connectors import (
    Connector,
    ConnectorValidationError,
    CSVConnector,
    MaterializingConnector,
)
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_manifest import manifest_path_for, read_manifest
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import IngestionResult, ingest_to_parquet
from data_engine.storage import DuckDBStorage

client = TestClient(app)

VALID_CSV = b"id,name,amount\n1,alice,10.5\n2,bob,20.0\n3,carol,30.25\n"


def _write(tmp_path, content: bytes, name: str = "source.csv") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    storage_root = tmp_path / "parquet"
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(storage_root))
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)

    return registry


def _upload(filename: str = "sample.csv", content: bytes = VALID_CSV):
    return client.post(
        "/api/dataset/upload",
        files={"file": (filename, content, "text/csv")},
    )


def _leftover_tmp_files():
    return set(glob.glob(os.path.join(tempfile.gettempdir(), "dataset_upload_*")))


# =========================================================
# PROTOCOLS
# =========================================================


def test_csv_connector_satisfies_both_protocols(tmp_path):
    connector = CSVConnector(_write(tmp_path, VALID_CSV), filename="a.csv")

    assert connector.source_type == "csv"
    assert isinstance(connector, Connector)
    assert isinstance(connector, MaterializingConnector)


def test_connector_protocol_does_not_require_local_parquet():
    # A source that is queried in place (never materialized) is still a
    # Connector - it just isn't a MaterializingConnector.
    class InPlaceSource:
        source_type = "in-place"

        def validate(self) -> None:
            pass

    source = InPlaceSource()

    assert isinstance(source, Connector)
    assert not isinstance(source, MaterializingConnector)


# =========================================================
# VALIDATION
# =========================================================


def test_validate_accepts_valid_csv(tmp_path):
    CSVConnector(_write(tmp_path, VALID_CSV), filename="orders.CSV").validate()


@pytest.mark.parametrize("filename", ["data.txt", "data.csv.exe", "data", "data.parquet"])
def test_validate_rejects_non_csv_filename(tmp_path, filename):
    connector = CSVConnector(_write(tmp_path, VALID_CSV), filename=filename)

    with pytest.raises(ConnectorValidationError, match="Only CSV files"):
        connector.validate()


def test_validate_rejects_empty_file(tmp_path):
    connector = CSVConnector(_write(tmp_path, b""), filename="a.csv")

    with pytest.raises(ConnectorValidationError, match="empty"):
        connector.validate()


def test_validate_rejects_missing_file(tmp_path):
    connector = CSVConnector(str(tmp_path / "missing.csv"), filename="a.csv")

    with pytest.raises(ConnectorValidationError, match="empty"):
        connector.validate()


def test_validate_rejects_binary_file(tmp_path):
    connector = CSVConnector(_write(tmp_path, b"PK\x03\x04\x00\x00binary"), filename="a.csv")

    with pytest.raises(ConnectorValidationError, match="does not look like a text CSV"):
        connector.validate()


def test_validation_error_is_a_value_error():
    assert issubclass(ConnectorValidationError, ValueError)


# =========================================================
# INGESTION DELEGATES TO THE EXISTING BOUNDARY
# =========================================================


def test_ingest_delegates_to_ingest_to_parquet(tmp_path, monkeypatch):
    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return ingest_to_parquet(**kwargs)

    monkeypatch.setattr(csv_connector_module, "ingest_to_parquet", _spy)

    storage_root = str(tmp_path / "out")
    connector = CSVConnector(_write(tmp_path, VALID_CSV), filename="a.csv")
    result = connector.ingest(dataset_id="ds-1", storage_root=storage_root)

    assert len(calls) == 1
    assert calls[0]["dataset_id"] == "ds-1"
    assert calls[0]["storage_root"] == storage_root
    assert isinstance(result, IngestionResult)
    assert result.parquet_path == os.path.join(storage_root, "ds-1.parquet")
    assert result.row_count == 3
    assert result.column_names == ["id", "name", "amount"]
    assert pq.read_table(result.parquet_path).num_rows == 3


def test_ingest_propagates_failure_and_leaves_no_parquet(tmp_path):
    storage_root = tmp_path / "out"
    # Ragged row: pyarrow's CSV reader rejects it mid-stream.
    connector = CSVConnector(_write(tmp_path, b"a,b\n1,2\n3,4,5\n"), filename="a.csv")

    with pytest.raises(Exception):
        connector.ingest(dataset_id="ds-bad", storage_root=str(storage_root))

    assert not (storage_root / "ds-bad.parquet").exists()


# =========================================================
# UPLOAD ROUTE THROUGH CSVConnector
# =========================================================


def test_upload_goes_through_csv_connector(isolated_registry, monkeypatch):
    calls = []
    original_ingest = CSVConnector.ingest

    def _spy_ingest(self, dataset_id, storage_root):
        calls.append((self.filename, dataset_id, storage_root))
        return original_ingest(self, dataset_id=dataset_id, storage_root=storage_root)

    monkeypatch.setattr(CSVConnector, "ingest", _spy_ingest)

    response = _upload(filename="orders.csv")

    assert response.status_code == 200
    assert calls == [
        ("orders.csv", response.json()["dataset_id"], dataset_route.PARQUET_STORAGE_ROOT)
    ]


def test_upload_response_shape_and_registration_unchanged(isolated_registry):
    response = _upload(filename="orders.csv")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "filename", "rows", "columns", "dataset_id"}
    assert body["message"] == "Dataset uploaded successfully."
    assert body["filename"] == "orders.csv"
    assert body["rows"] == 3
    assert body["columns"] == 3

    dataset = isolated_registry.get(body["dataset_id"])
    assert isinstance(dataset.storage, DuckDBStorage)
    assert dataset.name == "orders.csv"

    parquet_path = os.path.join(dataset_route.PARQUET_STORAGE_ROOT, f"{body['dataset_id']}.parquet")
    assert os.path.exists(parquet_path)

    manifest = read_manifest(manifest_path_for(body["dataset_id"], dataset_route.PARQUET_STORAGE_ROOT))
    assert manifest.dataset_id == body["dataset_id"]
    assert manifest.name == "orders.csv"


def test_upload_preserves_ownership(isolated_registry, monkeypatch):
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "user-a")

    dataset_id = _upload().json()["dataset_id"]

    assert isolated_registry.get(dataset_id).owner_id == "user-a"
    manifest = read_manifest(manifest_path_for(dataset_id, dataset_route.PARQUET_STORAGE_ROOT))
    assert manifest.owner_id == "user-a"

    # Another user can't reach it.
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "user-b")
    assert client.get(f"/api/dataset/{dataset_id}/preview").status_code == 404


@pytest.mark.parametrize(
    "filename, content, detail",
    [
        ("data.txt", VALID_CSV, "Only CSV files are currently supported."),
        ("data.csv", b"", "The uploaded CSV file is empty."),
        ("data.csv", b"a,b\n\x00\x01", "The uploaded file does not look like a text CSV file."),
    ],
)
def test_upload_validation_errors_unchanged(isolated_registry, filename, content, detail):
    before = _leftover_tmp_files()

    response = _upload(filename=filename, content=content)

    assert response.status_code == 400
    assert response.json()["detail"] == detail
    assert isolated_registry.list() == []
    assert _leftover_tmp_files() == before


def test_upload_ingestion_failure_cleans_up(isolated_registry, monkeypatch):
    def _failing_ingest(**kwargs):
        raise RuntimeError("internal ingestion detail")

    monkeypatch.setattr(csv_connector_module, "ingest_to_parquet", _failing_ingest)
    before = _leftover_tmp_files()

    response = _upload()

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unable to load dataset. Please check that the file is a valid CSV."
    )
    assert "internal ingestion detail" not in response.text
    assert isolated_registry.list() == []
    assert _leftover_tmp_files() == before


def test_upload_malformed_csv_cleans_up(isolated_registry):
    before = _leftover_tmp_files()

    response = _upload(content=b"a,b\n1,2\n3,4,5\n")

    assert response.status_code == 400
    assert isolated_registry.list() == []
    assert _leftover_tmp_files() == before
    assert glob.glob(os.path.join(dataset_route.PARQUET_STORAGE_ROOT, "*.parquet")) == []


def test_upload_registration_failure_removes_parquet(isolated_registry, monkeypatch):
    def _failing_storage(result):
        raise RuntimeError("storage build failed")

    monkeypatch.setattr(dataset_manager_module, "select_storage_for_ingestion", _failing_storage)
    before = _leftover_tmp_files()

    response = _upload()

    assert response.status_code == 400
    assert isolated_registry.list() == []
    assert _leftover_tmp_files() == before
    assert glob.glob(os.path.join(dataset_route.PARQUET_STORAGE_ROOT, "*.parquet")) == []
