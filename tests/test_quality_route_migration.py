"""Phase 2 / Step 6A: wire backend/routes/dataset.py's GET /quality
and GET /{dataset_id}/quality handlers to the storage-aware
``check_quality_for_dataset()`` entry point instead of the legacy
``dataset_manager.get_cached(...)`` / ``get_cached_on(...)`` pair,
which unconditionally materializes a full DataFrame via
``dataset.storage.to_dataframe()`` before calling
``data_engine.data_quality.check_data_quality()``.

Verifies, at the FastAPI route level:
  - Both /quality endpoints funnel their computation strictly through
    ``check_quality_for_dataset``.
  - A DuckDB-backed dataset's quality check completes with zero raw
    ``to_dataframe()`` calls on its storage.
  - A Pandas-backed dataset still completes successfully via the
    historical PandasQualityEngine fallback (one ``to_dataframe()``
    call).
  - The historical response schema (status, issue_count, issues) is
    fully preserved.
  - Caching semantics are preserved: a second call reuses
    ``dataset.cache["quality"]`` without recomputation.
  - An unhandled quality-check failure still propagates exactly as it
    did before this step.

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
from data_engine.quality import check_quality_for_dataset
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
    Give the quality routes a private DatasetRegistry/DatasetManager
    pair, so this test's datasets never touch the process-wide
    singletons or any dataset registered by another test module.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)

    return registry, manager


def _register(registry: DatasetRegistry, storage, *, name="dataset.csv") -> Dataset:
    dataset = Dataset(storage=storage, name=name)
    registry.register(dataset)
    return dataset


# =========================================================
# EXPLICIT dataset_id PATH: PRODUCTION ROUTE USES
# check_quality_for_dataset
# =========================================================


def test_quality_by_id_route_uses_check_quality_for_dataset(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_quality(dataset_arg):
        calls.append(dataset_arg)
        return check_quality_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", _spy_quality)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/quality")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0] is dataset


# =========================================================
# DUCKDB-BACKED QUALITY: ZERO to_dataframe() CALLS
# =========================================================


def test_duckdb_backed_quality_by_id_never_materializes_full_dataframe(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/quality")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


def test_duckdb_backed_active_quality_never_materializes_full_dataframe(isolated_manager):
    registry, manager = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage, name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/quality")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


# =========================================================
# PANDAS FALLBACK PATH STILL COMPLETES GRACEFULLY
# =========================================================


def test_pandas_backed_quality_by_id_falls_back_gracefully(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyPandasStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/quality")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == [True]


# =========================================================
# RESPONSE SCHEMA STAYS FULLY INTACT
# =========================================================


def test_quality_by_id_response_schema_unchanged(isolated_manager):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()), name="orders.csv")

    response = client.get(f"/api/dataset/{dataset.dataset_id}/quality")

    assert response.status_code == 200
    body = response.json()

    for key in ("status", "issue_count", "issues"):
        assert key in body

    assert body["status"] in {"healthy", "info", "warning", "error"}
    assert isinstance(body["issues"], list)


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_active_quality_route_response_schema_unchanged(isolated_manager, storage_cls):
    registry, manager = isolated_manager
    dataset = Dataset(storage=storage_cls(_make_dataframe()), name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/quality")

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "issue_count" in body


# =========================================================
# CACHING SEMANTICS PRESERVED
# =========================================================


def test_quality_by_id_route_caches_after_first_call(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_quality(dataset_arg):
        calls.append(dataset_arg)
        return check_quality_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", _spy_quality)

    first = client.get(f"/api/dataset/{dataset.dataset_id}/quality")
    second = client.get(f"/api/dataset/{dataset.dataset_id}/quality")

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()


# =========================================================
# UNHANDLED QUALITY-CHECK FAILURES STILL PROPAGATE UNCHANGED
# =========================================================


def test_quality_failure_still_propagates_unhandled(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    def _boom(dataset_arg):
        raise RuntimeError("simulated quality-check failure")

    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", _boom)

    with pytest.raises(RuntimeError, match="simulated quality-check failure"):
        client.get(f"/api/dataset/{dataset.dataset_id}/quality")


# =========================================================
# 404 WHEN NOTHING IS LOADED (ACTIVE-DATASET ROUTE)
# =========================================================


def test_active_quality_route_404_when_nothing_loaded(isolated_manager):
    response = client.get("/api/dataset/quality")
    assert response.status_code == 404
