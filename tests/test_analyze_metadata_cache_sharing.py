"""Phase 2 / Step 6A: backend/routes/dataset.py's GET
/{dataset_id}/metadata and backend/routes/analysis.py's POST
/api/analyze both key their metadata computation off the same
``dataset.cache["metadata"]`` entry, via ``get_cached_on_dataset(...,
"metadata", metadata_for_dataset)`` in both routes.

Verifies:
  - Whichever route runs first computes metadata exactly once, and the
    other route reuses the cached value - regardless of call order.
  - This holds for both a DuckDB-backed and a Pandas-backed dataset.
  - It also holds when the dataset is reached implicitly (GET
    /api/dataset/metadata, the no-dataset_id "active dataset" route)
    rather than by explicit dataset_id.
  - The metadata payload returned by /metadata is exactly the object
    /api/analyze's planning stage consumed from the shared cache.

Each test gets its own DatasetRegistry patched into both route
modules, so this never touches the process-wide singleton or any
dataset registered by another test module. No AI provider is ever
invoked - every plan here is produced by the deterministic
FastPlanner.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata_engine import metadata_for_dataset
from data_engine.storage import DuckDBStorage, PandasStorage

client = TestClient(app)

QUESTION = "total quantity by region"


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
        }
    )


@pytest.fixture
def isolated(monkeypatch):
    """
    Give both /api/dataset and /api/analyze a shared, private
    DatasetRegistry/DatasetManager pair, so this test's datasets never
    touch the process-wide singletons or any dataset registered by
    another test module.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)

    return registry, manager


def _register(registry: DatasetRegistry, storage) -> Dataset:
    dataset = Dataset(storage=storage)
    registry.register(dataset)
    return dataset


def _spy_metadata_for_dataset(monkeypatch, calls):
    def _wrapped(dataset_arg):
        calls.append(dataset_arg)
        return metadata_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "metadata_for_dataset", _wrapped)
    monkeypatch.setattr(analysis_route, "metadata_for_dataset", _wrapped)


def _ask(dataset_id: str):
    return client.post(
        "/api/analyze",
        json={"dataset_id": dataset_id, "question": QUESTION},
    )


# =========================================================
# /metadata FIRST, THEN /api/analyze
# =========================================================


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_metadata_route_then_analyze_share_one_computation(isolated, monkeypatch, storage_cls):
    registry, _ = isolated
    dataset = _register(registry, storage_cls(_make_dataframe()))

    calls = []
    _spy_metadata_for_dataset(monkeypatch, calls)

    metadata_response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")
    assert metadata_response.status_code == 200
    assert len(calls) == 1

    analyze_response = _ask(dataset.dataset_id)
    assert analyze_response.status_code == 200

    # No new computation - /api/analyze reused dataset.cache["metadata"].
    assert len(calls) == 1
    assert dataset.cache["metadata"] == metadata_response.json()


# =========================================================
# /api/analyze FIRST, THEN /metadata
# =========================================================


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_analyze_then_metadata_route_share_one_computation(isolated, monkeypatch, storage_cls):
    registry, _ = isolated
    dataset = _register(registry, storage_cls(_make_dataframe()))

    calls = []
    _spy_metadata_for_dataset(monkeypatch, calls)

    analyze_response = _ask(dataset.dataset_id)
    assert analyze_response.status_code == 200
    assert len(calls) == 1

    metadata_response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")
    assert metadata_response.status_code == 200

    # No new computation - /metadata reused dataset.cache["metadata"].
    assert len(calls) == 1
    assert metadata_response.json() == dataset.cache["metadata"]


# =========================================================
# ACTIVE-DATASET /metadata (NO dataset_id) SHARES THE SAME CACHE
# =========================================================


def test_active_metadata_route_shares_cache_with_analyze(isolated, monkeypatch):
    registry, manager = isolated
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    with manager._lock:
        manager._active_id = dataset.dataset_id

    calls = []
    _spy_metadata_for_dataset(monkeypatch, calls)

    active_metadata_response = client.get("/api/dataset/metadata")
    assert active_metadata_response.status_code == 200
    assert len(calls) == 1

    analyze_response = _ask(dataset.dataset_id)
    assert analyze_response.status_code == 200

    assert len(calls) == 1
    assert dataset.cache["metadata"] == active_metadata_response.json()
