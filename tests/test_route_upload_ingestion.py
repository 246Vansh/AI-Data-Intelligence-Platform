"""Step 10: wire the /api/dataset/upload route to bounded-memory ingestion.

Verifies, at the FastAPI route level:
  - Uploading a CSV invokes the real ``ingest_to_parquet`` utility.
  - A successful upload maps the registered dataset to the true,
    persistent Parquet reference ``ingest_to_parquet`` produced (backed
    by DuckDBStorage, not a Pandas DataFrame kept in memory).
  - An ingestion failure prevents dataset registration entirely - no
    orphaned/partial registry state, and the appropriate HTTP error is
    raised.
  - Zero calls to ``pandas.read_csv`` happen anywhere in the upload
    path - the full-source-DataFrame parse this step removes.

Each test gets its own DatasetManager/DatasetRegistry pair patched into
the route module, so this never touches the process-wide singletons
other test modules (or the running app) rely on.
"""

import os

import pandas as pd
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

import backend.routes.dataset as dataset_route
from backend.main import app
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.ingestion import IngestionResult, ingest_to_parquet
from data_engine.storage import DuckDBStorage

client = TestClient(app)

VALID_CSV = b"id,name,amount\n1,alice,10.5\n2,bob,20.0\n3,carol,30.25\n"


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """
    Give the upload route a private DatasetManager/DatasetRegistry pair
    and a private Parquet storage root, so this test's uploads never
    touch the process-wide singletons or the real data/uploads
    directory.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))

    return registry


def _upload(filename: str = "sample.csv", content: bytes = VALID_CSV):
    return client.post(
        "/api/dataset/upload",
        files={"file": (filename, content, "text/csv")},
    )


# =========================================================
# INVOKES THE REAL ingest_to_parquet UTILITY
# =========================================================


def test_upload_invokes_ingest_to_parquet(isolated_registry, monkeypatch):
    calls = []

    def _spy_ingest(**kwargs):
        calls.append(kwargs)
        return ingest_to_parquet(**kwargs)

    monkeypatch.setattr(dataset_route, "ingest_to_parquet", _spy_ingest)

    response = _upload()

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["dataset_id"] == response.json()["dataset_id"]


# =========================================================
# SUCCESS: DATASET MAPS TO THE TRUE PERSISTENT PARQUET REFERENCE
# =========================================================


def test_successful_upload_registers_dataset_backed_by_persistent_parquet(isolated_registry):
    response = _upload(filename="orders.csv")

    assert response.status_code == 200
    body = response.json()
    dataset_id = body["dataset_id"]

    dataset = isolated_registry.get(dataset_id)
    assert isinstance(dataset.storage, DuckDBStorage)
    assert dataset.name == "orders.csv"

    parquet_path = os.path.join(dataset_route.PARQUET_STORAGE_ROOT, f"{dataset_id}.parquet")
    assert os.path.exists(parquet_path)

    # Read the Parquet file independently of the app - it is the real,
    # persistent source of truth, not something only held in memory.
    table = pq.read_table(parquet_path)
    assert table.num_rows == body["rows"] == 3
    assert table.num_columns == body["columns"] == 3


# =========================================================
# INGESTION FAILURE PREVENTS DATASET REGISTRATION
# =========================================================


def test_ingestion_failure_registers_nothing_and_raises_http_error(isolated_registry, monkeypatch):
    def _failing_ingest(**kwargs):
        raise RuntimeError("simulated ingestion failure")

    monkeypatch.setattr(dataset_route, "ingest_to_parquet", _failing_ingest)

    response = _upload()

    assert response.status_code == 400
    assert "simulated ingestion failure" in response.json()["detail"]

    # No dataset was registered, and nothing became "active".
    assert isolated_registry.list() == []
    assert not dataset_route.dataset_manager.is_loaded()


def test_ingestion_failure_leaves_no_orphaned_parquet_fragment(isolated_registry, tmp_path):
    # A real ingestion failure (bad/corrupt CSV) still self-cleans via
    # ingest_to_parquet's own deterministic cleanup - nothing extra for
    # the route to do, and nothing left on disk under the dataset_id
    # that would have been assigned.
    response = _upload(filename="broken.csv", content=b"\x00\x01binary-not-csv")

    assert response.status_code == 400
    assert isolated_registry.list() == []
    assert list(tmp_path.iterdir()) == []


# =========================================================
# ZERO FULL-SOURCE pd.read_csv CALLS DURING REGISTRATION
# =========================================================


def test_successful_upload_never_calls_pandas_read_csv(isolated_registry, monkeypatch):
    read_csv_spy = pd.read_csv

    calls = []

    def _spy_read_csv(*args, **kwargs):
        calls.append((args, kwargs))
        return read_csv_spy(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", _spy_read_csv)

    response = _upload()

    assert response.status_code == 200
    assert calls == []
