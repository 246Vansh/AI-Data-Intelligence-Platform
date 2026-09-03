"""Step 12B: wire backend/routes/dataset.py's GET /profile and
GET /{dataset_id}/profile handlers to the storage-aware
``basic_statistics_for_dataset()`` entry point instead of the legacy
``dataset_manager.get_cached(...)`` / ``get_cached_on(...)`` pair, which
unconditionally materializes a full DataFrame via
``dataset.storage.to_dataframe()`` before calling
``data_engine.profiler.profile_dataset()``.

Verifies, at the FastAPI route level:
  - Both /profile endpoints funnel their computation strictly through
    ``basic_statistics_for_dataset``.
  - A DuckDB-backed dataset's profile completes with zero raw
    ``to_dataframe()`` calls on its storage.
  - A Pandas-backed dataset still completes successfully via the
    historical PandasProfilingEngine fallback (one ``to_dataframe()``
    call).
  - The historical response schema (rows, columns, column_names,
    data_types, missing_values, duplicate_rows, memory_usage_bytes,
    column_details, filename) is fully preserved - no field is
    stripped, even where the Step 9 contract doesn't cover it.
  - An unhandled profiling failure still propagates exactly as it did
    before this step (no new try/except swallowing it into a
    different status code).

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
from data_engine.profiling import basic_statistics_for_dataset
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
    Give the profile routes a private DatasetRegistry/DatasetManager
    pair, so this test's datasets never touch the process-wide
    singletons or any dataset registered by another test module.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)

    # backend.dependencies (require_dataset()/get_current_dataset_name())
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
# basic_statistics_for_dataset
# =========================================================


def test_profile_by_id_route_uses_basic_statistics_for_dataset(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_stats(dataset_arg):
        calls.append(dataset_arg)
        return basic_statistics_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "basic_statistics_for_dataset", _spy_stats)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0] is dataset


# =========================================================
# CACHING SEMANTICS PRESERVED
# =========================================================


def test_profile_by_id_route_caches_after_first_call(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    calls = []

    def _spy_stats(dataset_arg):
        calls.append(dataset_arg)
        return basic_statistics_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "basic_statistics_for_dataset", _spy_stats)

    first = client.get(f"/api/dataset/{dataset.dataset_id}/profile")
    second = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()
    assert "basic_statistics" in dataset.cache


# =========================================================
# DUCKDB-BACKED PROFILE: ZERO to_dataframe() CALLS
# =========================================================


def test_duckdb_backed_profile_by_id_never_materializes_full_dataframe(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


def test_duckdb_backed_active_profile_never_materializes_full_dataframe(isolated_manager):
    registry, manager = isolated_manager
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage, name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/profile")

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []


# =========================================================
# PANDAS FALLBACK PATH STILL COMPLETES GRACEFULLY
# =========================================================


def test_pandas_backed_profile_by_id_falls_back_gracefully(isolated_manager):
    registry, _ = isolated_manager
    storage = _SpyPandasStorage(_make_dataframe())
    dataset = _register(registry, storage)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert response.status_code == 200
    # The Pandas path is expected to materialize via to_dataframe() -
    # exactly once, inside PandasProfilingEngine - it is only
    # DuckDB-backed datasets that skip it entirely.
    assert storage.to_dataframe_calls == [True]


# =========================================================
# RESPONSE SCHEMA STAYS FULLY INTACT
# =========================================================


def test_profile_by_id_response_schema_unchanged(isolated_manager):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()), name="orders.csv")

    response = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert response.status_code == 200
    body = response.json()

    for key in (
        "rows",
        "columns",
        "column_names",
        "data_types",
        "missing_values",
        "duplicate_rows",
        "memory_usage_bytes",
        "column_details",
        "filename",
    ):
        assert key in body

    assert body["rows"] == 6
    assert body["columns"] == 3
    assert set(body["column_names"]) == {"region", "category", "quantity"}
    assert body["filename"] == "orders.csv"
    assert body["duplicate_rows"] == 0
    assert isinstance(body["memory_usage_bytes"], int)

    quantity_details = body["column_details"]["quantity"]
    assert quantity_details["missing_count"] == 0
    assert quantity_details["unique_values"] == 6
    assert "data_type" in quantity_details
    assert "missing_percentage" in quantity_details


def test_duckdb_backed_profile_reports_null_memory_usage(isolated_manager):
    registry, _ = isolated_manager
    dataset = _register(registry, DuckDBStorage(_make_dataframe()))

    response = client.get(f"/api/dataset/{dataset.dataset_id}/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["memory_usage_bytes"] is None
    assert body["duplicate_rows"] == 0


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_active_profile_route_response_schema_unchanged(isolated_manager, storage_cls):
    registry, manager = isolated_manager
    dataset = Dataset(storage=storage_cls(_make_dataframe()), name="active.csv")
    registry.register(dataset)

    with manager._lock:
        manager._active_id = dataset.dataset_id

    response = client.get("/api/dataset/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "active.csv"
    assert body["rows"] == 6
    assert body["columns"] == 3


# =========================================================
# UNHANDLED PROFILING FAILURES STILL PROPAGATE UNCHANGED
# =========================================================


def test_profiling_failure_still_propagates_unhandled(isolated_manager, monkeypatch):
    registry, _ = isolated_manager
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    def _boom(dataset_arg):
        raise RuntimeError("simulated profiling failure")

    monkeypatch.setattr(dataset_route, "basic_statistics_for_dataset", _boom)

    with pytest.raises(RuntimeError, match="simulated profiling failure"):
        client.get(f"/api/dataset/{dataset.dataset_id}/profile")
