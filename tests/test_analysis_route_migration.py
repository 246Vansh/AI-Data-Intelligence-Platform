"""Step 12A: wire backend/routes/analysis.py's execution stage to the
storage-aware ``execute_plan_for_dataset()`` entry point instead of the
legacy ``dataset.storage.to_dataframe()`` + ``execute_plan(df, plan)``
pair.

Verifies, at the FastAPI route level:
  - The production ``/api/analyze`` path calls
    ``execute_plan_for_dataset`` (never the legacy ``execute_plan``
    directly) to run the validated plan.
  - A DuckDB-backed dataset completes a full analysis request with
    zero raw ``to_dataframe()`` buffer calls on its storage.
  - A Pandas-backed dataset still completes successfully via the
    historical engine router path (one ``to_dataframe()`` call, inside
    ``PandasExecutionEngine``).
  - An invalid plan (unknown column) is still rejected by
    ``validate_plan`` *before* ``execute_plan_for_dataset`` is ever
    invoked.
  - The response envelope (visualization + insights + plan + data)
    remains fully intact.

Each test gets its own DatasetRegistry patched into the route module,
so this never touches the process-wide singleton other test modules
(or the running app) rely on. No AI provider is ever invoked - every
plan here is produced by the deterministic ``FastPlanner``.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.routes.analysis as analysis_route
from backend.main import app
from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.plan_executor import execute_plan_for_dataset
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
def isolated_registry(monkeypatch):
    """
    Give /api/analyze a private DatasetRegistry, so this test's
    datasets never touch the process-wide singleton or any dataset
    registered by another test module.
    """
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    return registry


def _register(registry: DatasetRegistry, storage, *, precomputed_metadata=None) -> Dataset:
    dataset = Dataset(storage=storage)

    # Metadata generation (get_cached_on -> get_metadata) is Step 9/10
    # territory, out of scope here - pre-seed the cache so this test's
    # to_dataframe() assertions isolate the *execution* stage this step
    # actually touches, rather than double-counting the pre-existing
    # metadata materialization.
    if precomputed_metadata is not None:
        dataset.cache["metadata"] = precomputed_metadata

    registry.register(dataset)
    return dataset


def _ask(dataset_id: str, question: str):
    return client.post(
        "/api/analyze",
        json={"dataset_id": dataset_id, "question": question},
    )


QUESTION = "total quantity by region"


# =========================================================
# PRODUCTION PATH REDIRECTS VIA execute_plan_for_dataset
# =========================================================


def test_analyze_route_uses_execute_plan_for_dataset(isolated_registry, monkeypatch):
    df = _make_dataframe()
    metadata = get_metadata(df)
    dataset = _register(isolated_registry, PandasStorage(df), precomputed_metadata=metadata)

    calls = []

    def _spy_execute(dataset_arg, plan_arg):
        calls.append((dataset_arg, plan_arg))
        return execute_plan_for_dataset(dataset_arg, plan_arg)

    monkeypatch.setattr(analysis_route, "execute_plan_for_dataset", _spy_execute)

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] is dataset


# =========================================================
# DUCKDB-BACKED PATH: ZERO to_dataframe() CALLS
# =========================================================


def test_duckdb_backed_analyze_never_materializes_full_dataframe(isolated_registry):
    df = _make_dataframe()
    metadata = get_metadata(df)
    storage = _SpyDuckDBStorage(df)
    dataset = _register(isolated_registry, storage, precomputed_metadata=metadata)

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    assert storage.to_dataframe_calls == []

    body = response.json()
    assert body["data"]["columns"] == ["region", "sum_quantity"]
    assert body["data"]["row_count"] == 3


# =========================================================
# PANDAS FALLBACK PATH STILL COMPLETES GRACEFULLY
# =========================================================


def test_pandas_backed_analyze_falls_back_gracefully(isolated_registry):
    df = _make_dataframe()
    metadata = get_metadata(df)
    storage = _SpyPandasStorage(df)
    dataset = _register(isolated_registry, storage, precomputed_metadata=metadata)

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    # The Pandas path is expected to materialize via to_dataframe() -
    # exactly once, inside PandasExecutionEngine - it is only
    # DuckDB-backed datasets that skip it entirely.
    assert storage.to_dataframe_calls == [True]

    body = response.json()
    assert body["data"]["columns"] == ["region", "sum_quantity"]
    assert body["data"]["row_count"] == 3


# =========================================================
# INVALID PLANS ARE STILL REJECTED BEFORE EXECUTION
# =========================================================


def test_invalid_plan_rejected_before_execution(isolated_registry, monkeypatch):
    df = _make_dataframe()
    metadata = get_metadata(df)
    dataset = _register(isolated_registry, PandasStorage(df), precomputed_metadata=metadata)

    # Force the planner to hand back a plan referencing a column that
    # does not exist, bypassing the need to phrase a question that
    # naturally confuses FastPlanner - validate_plan() must still
    # reject it exactly as it did before this step.
    bad_plan = AnalysisPlan(
        filters=[FilterCondition(column="does_not_exist", operator="=", value=1)],
        metric="quantity",
        aggregation="sum",
    )

    monkeypatch.setattr(
        analysis_route.FastPlanner,
        "create_plan",
        lambda self, question, metadata: bad_plan,
    )

    calls = []
    monkeypatch.setattr(
        analysis_route,
        "execute_plan_for_dataset",
        lambda dataset_arg, plan_arg: calls.append(True),
    )

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 400
    assert "Invalid analysis plan" in response.json()["detail"]
    assert calls == []


# =========================================================
# RESPONSE ENVELOPE STAYS INTACT
# =========================================================


def test_response_envelope_unchanged(isolated_registry):
    df = _make_dataframe()
    metadata = get_metadata(df)
    dataset = _register(isolated_registry, PandasStorage(df), precomputed_metadata=metadata)

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    body = response.json()

    for key in (
        "success",
        "question",
        "planner",
        "data",
        "insights",
        "insight_status",
        "insight_source",
        "insight_error",
        "visualization",
        "plan",
        "performance",
    ):
        assert key in body

    assert body["data"]["columns"] == ["region", "sum_quantity"]
    assert body["visualization"]["type"] in {"bar", "table"}
    assert body["plan"]["metric"] == "quantity"
    assert body["plan"]["aggregation"] == "sum"


def test_duckdb_backed_response_envelope_unchanged(isolated_registry):
    df = _make_dataframe()
    metadata = get_metadata(df)
    dataset = _register(isolated_registry, DuckDBStorage(df), precomputed_metadata=metadata)

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    body = response.json()

    for key in (
        "success",
        "question",
        "planner",
        "data",
        "insights",
        "insight_status",
        "insight_source",
        "insight_error",
        "visualization",
        "plan",
        "performance",
    ):
        assert key in body

    assert body["data"]["columns"] == ["region", "sum_quantity"]
    assert body["visualization"]["type"] in {"bar", "table"}
    assert body["plan"]["metric"] == "quantity"
    assert body["plan"]["aggregation"] == "sum"


# =========================================================
# GROUPED ROUTE FLOW - full /api/analyze pipeline, small N
#
# The exact DEFAULT_MAX_RESULT_ROWS cap itself is verified cheaply,
# at the engine level with no insight/visualization involved, by
# tests/test_duckdb_execution_engine.py::
# test_duckdb_engine_caps_unbounded_group_by_at_default_max_result_rows.
#
# Routing a full DEFAULT_MAX_RESULT_ROWS (10,000) row grouped result
# through the real /api/analyze route pays an unrelated ~50s cost
# inside InsightEngine._add_date_coverage() (data_engine/insight_engine.py),
# which does a full-column pd.to_datetime(..., format="mixed") scan over
# every result row. That cost is a function of row count only, not of
# whether the cap logic itself is correct - a much smaller grouped
# result exercises the exact same route/insight/visualization code
# paths for a fraction of the runtime.
# =========================================================


SMALL_GROUP_COUNT = 25


def _make_many_groups_dataframe(group_count: int) -> pd.DataFrame:
    # One row per distinct "region" group - the minimal shape needed to
    # exercise a grouped aggregation with `group_count` output rows,
    # mirroring tests/test_duckdb_execution_engine.py's fixture.
    return pd.DataFrame(
        {
            "region": [f"region_{i}" for i in range(group_count)],
            "quantity": [1] * group_count,
        }
    )


def test_duckdb_backed_analyze_route_flow_with_small_n(isolated_registry, monkeypatch):
    df = _make_many_groups_dataframe(SMALL_GROUP_COUNT)
    metadata = get_metadata(df)
    dataset = _register(isolated_registry, DuckDBStorage(df), precomputed_metadata=metadata)

    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        limit=None,
    )

    monkeypatch.setattr(
        analysis_route.FastPlanner,
        "create_plan",
        lambda self, question, metadata: plan,
    )

    response = _ask(dataset.dataset_id, QUESTION)

    assert response.status_code == 200
    body = response.json()

    for key in (
        "success",
        "question",
        "planner",
        "data",
        "insights",
        "insight_status",
        "insight_source",
        "insight_error",
        "visualization",
        "plan",
        "performance",
    ):
        assert key in body

    assert body["data"]["row_count"] == SMALL_GROUP_COUNT
    assert "rows" in body["data"]
    assert len(body["data"]["rows"]) == SMALL_GROUP_COUNT

    assert body["insight_status"] in {"success", "unavailable"}
    assert "insights" in body["insights"]

    assert "type" in body["visualization"]
    assert body["visualization"]["type"] in {"bar", "table"}
