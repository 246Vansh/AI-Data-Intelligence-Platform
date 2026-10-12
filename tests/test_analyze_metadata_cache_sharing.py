"""Step 83 (supersedes Phase 2 / Step 6A's shared-entry contract):
POST /api/analyze plans against ``dataset.cache["planning_metadata"]``
(``planning_metadata_for_dataset``), while GET
/api/dataset/{dataset_id}/metadata keeps serving the exact
``dataset.cache["metadata"]`` entry (``metadata_for_dataset``).

Verifies:
  - /api/analyze never calls the exact metadata builder, and on a
    DuckDB-backed dataset never runs the exact column_statistics() scan.
  - Each route computes its own entry exactly once, and repeat calls
    reuse it - regardless of call order.
  - /metadata's payload is the exact metadata whichever route ran
    first, for both DuckDB- and Pandas-backed datasets, and for the
    implicit active-dataset route.

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
from data_engine.metadata_engine import (
    metadata_for_dataset,
    planning_metadata_for_dataset,
)
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
    dataset = Dataset(storage=storage, owner_id="dev-user")
    registry.register(dataset)
    return dataset


def _spy_builders(monkeypatch):
    """Record every exact and planning metadata computation."""
    calls = {"exact": [], "planning": []}

    def _exact(dataset_arg):
        calls["exact"].append(dataset_arg)
        return metadata_for_dataset(dataset_arg)

    def _planning(dataset_arg):
        calls["planning"].append(dataset_arg)
        return planning_metadata_for_dataset(dataset_arg)

    monkeypatch.setattr(dataset_route, "metadata_for_dataset", _exact)
    monkeypatch.setattr(analysis_route, "planning_metadata_for_dataset", _planning)

    # /api/analyze must not reach the exact builder under either name.
    assert not hasattr(analysis_route, "metadata_for_dataset")

    return calls


def _ask(dataset_id: str):
    return client.post(
        "/api/analyze",
        json={"dataset_id": dataset_id, "question": QUESTION},
    )


# =========================================================
# /api/analyze NEVER RUNS THE EXACT COLUMN-STATISTICS SCAN
# =========================================================


def test_analyze_never_runs_exact_column_statistics(isolated, monkeypatch):
    registry, _ = isolated
    dataset = _register(registry, DuckDBStorage(_make_dataframe()))

    def _forbidden(self):
        raise AssertionError("exact column_statistics() ran on the /analyze path")

    monkeypatch.setattr(DuckDBStorage, "_compute_column_statistics", _forbidden)

    response = _ask(dataset.dataset_id)

    assert response.status_code == 200
    assert "planning_metadata" in dataset.cache
    assert "metadata" not in dataset.cache
    assert dataset.storage._column_statistics is None


# =========================================================
# /metadata FIRST, THEN /api/analyze
# =========================================================


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_metadata_route_then_analyze_use_separate_entries(isolated, monkeypatch, storage_cls):
    registry, _ = isolated
    dataset = _register(registry, storage_cls(_make_dataframe()))
    calls = _spy_builders(monkeypatch)

    metadata_response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")
    assert metadata_response.status_code == 200
    assert (len(calls["exact"]), len(calls["planning"])) == (1, 0)

    assert _ask(dataset.dataset_id).status_code == 200
    assert _ask(dataset.dataset_id).status_code == 200

    # Planning metadata computed once and reused; exact never recomputed.
    assert (len(calls["exact"]), len(calls["planning"])) == (1, 1)
    assert dataset.cache["metadata"] == metadata_response.json()


# =========================================================
# /api/analyze FIRST, THEN /metadata
# =========================================================


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_analyze_then_metadata_route_use_separate_entries(isolated, monkeypatch, storage_cls):
    registry, _ = isolated
    dataset = _register(registry, storage_cls(_make_dataframe()))
    calls = _spy_builders(monkeypatch)

    assert _ask(dataset.dataset_id).status_code == 200
    assert (len(calls["exact"]), len(calls["planning"])) == (0, 1)
    assert "metadata" not in dataset.cache

    metadata_response = client.get(f"/api/dataset/{dataset.dataset_id}/metadata")
    assert metadata_response.status_code == 200
    assert (len(calls["exact"]), len(calls["planning"])) == (1, 1)

    # /metadata serves the exact computation, not the planning entry.
    assert metadata_response.json() == dataset.cache["metadata"]
    assert metadata_response.json() == metadata_for_dataset(dataset)


# =========================================================
# ACTIVE-DATASET /metadata (NO dataset_id) STAYS EXACT
# =========================================================


def test_active_metadata_route_stays_exact_and_separate(isolated, monkeypatch):
    registry, manager = isolated
    dataset = _register(registry, PandasStorage(_make_dataframe()))

    with manager._lock:
        manager._active_id = dataset.dataset_id

    calls = _spy_builders(monkeypatch)

    active_metadata_response = client.get("/api/dataset/metadata")
    assert active_metadata_response.status_code == 200

    assert _ask(dataset.dataset_id).status_code == 200

    assert (len(calls["exact"]), len(calls["planning"])) == (1, 1)
    assert dataset.cache["metadata"] == active_metadata_response.json()
