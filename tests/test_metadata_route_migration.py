"""Phase 2 / Step 6A: wire backend/routes/dataset.py's GET /metadata,
GET /{dataset_id}/metadata, and GET /{dataset_id}/preview handlers to
the storage-aware ``metadata_for_dataset()`` / ``preview_dataset()``
entry points instead of the legacy ``dataset_manager.get_cached(...)``
/ ``get_cached_on(...)`` pair (metadata) and unconditional
``.to_dataframe().head(10)`` (preview), both of which unconditionally
materialize a full DataFrame for a DuckDB-backed dataset.

Verifies, at the FastAPI route level:
  - All three endpoints funnel their computation strictly through
    ``metadata_for_dataset`` / ``preview_dataset``.
  - A DuckDB-backed dataset's metadata/preview completes with zero raw
    ``to_dataframe()`` calls on its storage.
  - A Pandas-backed dataset still completes successfully via the
    historical PandasMetadataEngine fallback.
  - The historical response schema is fully preserved.
  - Metadata caching semantics are preserved: a second call reuses
    ``dataset.cache["metadata"]`` without recomputation.
  - An unhandled failure still propagates exactly as it did before
    this step.

Each test gets its own DatasetRegistry/DatasetManager pair patched into
the route module, so this never touches the process-wide singletons or
any dataset registered by another test module.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routes.dataset as dataset_route
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata_engine import metadata_for_dataset
from data_engine.storage import DuckDBStorage, PandasStorage

client = TestClient(app)


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


class _SpyPandasStorage(PandasStorage):
    """PandasStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


@pytest.fixture
def isolated_manager(monkeypatch):
    """
    Give the metadata/preview routes a private DatasetRegistry/
    DatasetManager pair, so this test's datasets never touch the
    process-wide singletons or any dataset registered by another test
    module.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)

    # backend.dependencies (has_dataset_loaded()/get_current_dataset_name())
    # binds its own module-level reference to the process-wide
    # DatasetManager singleton at import time - patch it too, so the
    # implicit "active dataset" routes see this test's isolated
    # manager instead of the real one.
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)

    return registry, manager


def _register(registry: DatasetRegistry, storage, *, name="dataset.csv") -> Dataset:
    dataset = Dataset(storage=storage, name=name)
    registry.register(dataset)
    return dataset


# =========================================================
# EXPLICIT dataset_id PATH: PRODUCTION ROUTE USES
# metadata_for_dataset / preview_dataset
# =========================================================


def test_metadata_by_id_route_uses_metadata_for_dataset(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_metadata(dataset_arg):
        calls.append(dataset_arg)
        return metadata_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "metadata_for_dataset", _spy_metadata)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0] is dataset


def test_preview_by_id_route_uses_preview_dataset(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_preview(dataset_arg, limit=10):
        calls.append(dataset_arg)
        from data_engine.preview import preview_dataset

        return preview_dataset(dataset_arg, limit=limit)

    monkeypatch.setattr(dataset_route, "preview_dataset", _spy_preview)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/preview")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0] is dataset


# =========================================================
# DUCKDB-BACKED: ZERO to_dataframe() CALLS
# =========================================================


def test_duckdb_backed_metadata_by_id_never_materializes_full_dataframe(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


def test_duckdb_backed_preview_by_id_never_materializes_full_dataframe(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/preview")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


def test_duckdb_backed_active_metadata_never_materializes_full_dataframe(isolated_manager):
    registry, manager = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage, name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/metadata")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


def test_duckdb_backed_active_preview_never_materializes_full_dataframe(isolated_manager):
    registry, manager = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage, name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/preview")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


# =========================================================
# PANDAS FALLBACK PATH STILL COMPLETES GRACEFULLY
# =========================================================


def test_pandas_backed_metadata_by_id_falls_back_gracefully(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyPandasStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == [True]


def test_pandas_backed_preview_by_id_falls_back_gracefully(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyPandasStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/preview")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == [True]


# =========================================================
# RESPONSE SCHEMA STAYS FULLY INTACT
# =========================================================


def test_metadata_by_id_response_schema_unchanged(isolated_manager):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")

    assert response.status_code == 200
    body = response.json()

    for key in ("row_count", "column_count", "columns", "time_column", "time_columns"):
        assert key in body

    assert body["row_count"] == 6
    assert body["column_count"] == 3

    quantity = body["columns"]["quantity"]
    for key in (
        "data_type",
        "role",
        "allowed_operations",
        "nullable",
        "missing_count",
        "unique_values",
        "sample_values",
    ):
        assert key in quantity


def test_preview_by_id_response_schema_unchanged(isolated_manager):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()), name="orders.csv")

    response = client.get(f"/api/dataset/{dataset.dataset_id}/preview")

    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {"filename", "columns", "rows"}
    assert body["filename"] == "orders.csv"
    assert body["columns"] == ["region", "category", "quantity"]
    assert len(body["rows"]) == 6


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_active_metadata_route_response_schema_unchanged(isolated_manager, storage_cls):
    registry, manager = isolated_manager
    dataset = Dataset(storage=storage_cls(_make_dataframe()), name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/metadata")

    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 6
    assert body["column_count"] == 3


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_active_preview_route_response_schema_unchanged(isolated_manager, storage_cls):
    registry, manager = isolated_manager
    dataset = Dataset(storage=storage_cls(_make_dataframe()), name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "active.csv"
    assert body["columns"] == ["region", "category", "quantity"]


# =========================================================
# CACHING SEMANTICS PRESERVED FOR METADATA (NOT PREVIEW)
# =========================================================


def test_metadata_by_id_route_caches_after_first_call(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_metadata(dataset_arg):
        calls.append(dataset_arg)
        return metadata_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "metadata_for_dataset", _spy_metadata)

    first = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")
    second = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()


def test_preview_by_id_route_is_never_cached(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_preview(dataset_arg, limit=10):
        calls.append(dataset_arg)
        from data_engine.preview import preview_dataset

        return preview_dataset(dataset_arg, limit=limit)

    monkeypatch.setattr(dataset_route, "preview_dataset", _spy_preview)

    client.get(f"/api/dataset/{dataset.dataset_id}/preview")
    client.get(f"/api/dataset/{dataset.dataset_id}/preview")

    assert len(calls) == 2
    assert "preview" not in dataset.cache


# =========================================================
# UNHANDLED FAILURES STILL PROPAGATE UNCHANGED
# =========================================================


def test_metadata_failure_still_propagates_unhandled(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    def _boom(dataset_arg):
        raise RuntimeError("simulated metadata failure")

    monkeypatch.setattr(dataset_route, "metadata_for_dataset", _boom)

    with pytest.raises(RuntimeError, match="simulated metadata failure"):
        client.get(f"/api/dataset/{dataset.dataset_id}/metadata")


def test_preview_failure_still_propagates_unhandled(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    def _boom(dataset_arg, limit=10):
        raise RuntimeError("simulated preview failure")

    monkeypatch.setattr(dataset_route, "preview_dataset", _boom)

    with pytest.raises(RuntimeError, match="simulated preview failure"):
        client.get(f"/api/dataset/{dataset.dataset_id}/preview")


# =========================================================
# 404 WHEN NOTHING IS LOADED (ACTIVE-DATASET ROUTES)
# =========================================================


def test_active_metadata_route_404_when_nothing_loaded(isolated_manager):
    response = client.get("/api/dataset/metadata")
    assert response.status_code == 404


def test_active_preview_route_404_when_nothing_loaded(isolated_manager):
    response = client.get("/api/dataset/preview")
    assert response.status_code == 404
