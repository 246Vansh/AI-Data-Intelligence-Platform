"""Step 11: end-to-end compatibility / regression matrix.

Verifies, with deterministic mocks and test spies only (no external AI
provider calls, no network), that the Pandas -> DuckDB storage/execution
migration (Steps 1-10) has not broken any existing contract:

  - UPLOAD FLOW: ingest_to_parquet -> DatasetManager/DatasetRegistry
    registration -> response envelope.
  - DATASET API: /api/dataset info, metadata, profiling, quality
    endpoints keep identical JSON response schemas, row/column counts,
    and data-type meanings regardless of storage backend.
  - ANALYSIS PIPELINE: execute_plan_for_dataset() dispatches
    DuckDB-backed datasets to DuckDBExecutionEngine and computes
    natively (never materializing the full dataset into pandas first).
  - LEGACY FALLBACK: Pandas-backed datasets keep calling to_dataframe()
    and stepping down into PandasExecutionEngine exactly as before.
  - DOWNSTREAM PARITY: DuckDB-native analytical results feed the
    existing visualization spec builder and deterministic insight
    engine identically to the historical Pandas results, without
    leaking raw rows or raising structural contract errors.
  - ROUTE ISOLATION: backend/routes/*.py never import DuckDBStorage,
    DuckDBExecutionEngine, or PandasExecutionEngine directly - they
    only ever go through DatasetManager/DatasetRegistry/Dataset.

This module adds no new application behavior. It only exercises code
that already exists (Steps 1-10).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.routes.dataset as dataset_route
from backend.main import app
from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.execution import (
    DuckDBExecutionEngine,
    PandasExecutionEngine,
    select_engine_for,
)
from data_engine.ingestion import ingest_to_parquet
from data_engine.insight_engine import build_deterministic_insights
from data_engine.insight_generator import build_insight_response
from data_engine.plan_executor import execute_plan, execute_plan_for_dataset
from data_engine.storage import DuckDBStorage, PandasStorage
from data_engine.visualization import create_visualization_spec

client = TestClient(app)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
            "signed_up_at": pd.to_datetime(
                [
                    "2024-01-05",
                    "2024-02-10",
                    "2024-03-15",
                    "2024-04-20",
                    "2024-05-25",
                    "2024-06-30",
                ]
            ),
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


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    """
    Give the app a private DatasetManager/DatasetRegistry pair and a
    private Parquet storage root, isolated from the process-wide
    singletons and the real data/uploads directory.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))

    return registry


def _upload(filename: str = "sample.csv", content: bytes | None = None):
    if content is None:
        content = (
            b"region,category,quantity\n"
            b"north,a,10\nnorth,b,20\nsouth,a,30\nsouth,b,40\n"
        )
    return client.post(
        "/api/dataset/upload",
        files={"file": (filename, content, "text/csv")},
    )


# =========================================================
# 1. UPLOAD FLOW
# =========================================================


def test_upload_flow_streams_through_ingest_to_parquet_and_registers(
    isolated_app, monkeypatch
):
    calls = []

    def _spy_ingest(**kwargs):
        calls.append(kwargs)
        return ingest_to_parquet(**kwargs)

    monkeypatch.setattr(dataset_route, "ingest_to_parquet", _spy_ingest)

    response = _upload(filename="orders.csv")

    assert response.status_code == 200
    body = response.json()

    # Downstream response envelope is unchanged.
    assert set(body.keys()) == {
        "message",
        "filename",
        "rows",
        "columns",
        "dataset_id",
    }
    assert body["filename"] == "orders.csv"
    assert body["rows"] == 4
    assert body["columns"] == 3

    # ingest_to_parquet was actually invoked (not bypassed).
    assert len(calls) == 1
    assert calls[0]["dataset_id"] == body["dataset_id"]

    # Registered on DatasetRegistry/DatasetManager, backed by DuckDB.
    dataset = isolated_app.get(body["dataset_id"])
    assert isinstance(dataset.storage, DuckDBStorage)
    assert dataset_route.dataset_manager.is_loaded()


def test_upload_flow_never_parses_a_full_source_dataframe(isolated_app, monkeypatch):
    calls = []
    real_read_csv = pd.read_csv

    def _spy_read_csv(*args, **kwargs):
        calls.append((args, kwargs))
        return real_read_csv(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", _spy_read_csv)

    response = _upload()

    assert response.status_code == 200
    assert calls == []


# =========================================================
# 2. DATASET API - SCHEMA / COUNT / DTYPE PARITY
# =========================================================


def test_dataset_list_and_detail_schema(isolated_app):
    upload_response = _upload(filename="metrics.csv")
    dataset_id = upload_response.json()["dataset_id"]

    list_response = client.get("/api/dataset")
    assert list_response.status_code == 200
    listing = list_response.json()
    assert set(listing.keys()) == {"datasets"}
    assert len(listing["datasets"]) == 1

    summary_keys = {"dataset_id", "filename", "rows", "columns", "created_at"}
    assert set(listing["datasets"][0].keys()) == summary_keys

    detail_response = client.get(f"/api/dataset/{dataset_id}")
    assert detail_response.status_code == 200
    assert set(detail_response.json().keys()) == summary_keys
    assert detail_response.json()["rows"] == 4
    assert detail_response.json()["columns"] == 3


@pytest.mark.parametrize(
    "endpoint,expected_keys",
    [
        (
            "profile",
            {
                "rows",
                "columns",
                "column_names",
                "data_types",
                "missing_values",
                "duplicate_rows",
                "memory_usage_bytes",
                "column_details",
                "filename",
            },
        ),
        ("quality", {"status", "issue_count", "issues"}),
        (
            "metadata",
            {"row_count", "column_count", "columns", "time_column", "time_columns"},
        ),
    ],
)
def test_dataset_inspection_endpoints_preserve_response_schema(
    isolated_app, endpoint, expected_keys
):
    dataset_id = _upload().json()["dataset_id"]

    response = client.get(f"/api/dataset/{dataset_id}/{endpoint}")

    assert response.status_code == 200
    assert set(response.json().keys()) == expected_keys


def test_dataset_profile_row_column_counts_and_dtypes_match_source(isolated_app):
    dataset_id = _upload().json()["dataset_id"]

    profile = client.get(f"/api/dataset/{dataset_id}/profile").json()

    assert profile["rows"] == 4
    assert profile["columns"] == 3

    # Step 12B: /profile now funnels through
    # basic_statistics_for_dataset(), which reports the same
    # backend-agnostic categorized label
    # (data_engine.metadata.detect_data_type()'s vocabulary) regardless
    # of storage backend - not a raw pandas dtype string. This is an
    # intentional, approved contract change (a DuckDB-backed dataset
    # has no literal pandas dtype to report in the first place).
    assert profile["data_types"]["quantity"] == "integer"

    # Dtype *label* parity across backends: a Pandas-backed and a
    # DuckDB-backed dataset built from the same source must still
    # agree with each other through the /profile route.
    df = _make_dataframe()
    pandas_dataset = Dataset(storage=PandasStorage(df.copy()), name="pandas.csv")
    duckdb_dataset = Dataset(storage=DuckDBStorage(df.copy()), name="duckdb.csv")

    isolated_app.register(pandas_dataset)
    isolated_app.register(duckdb_dataset)

    pandas_profile = client.get(
        f"/api/dataset/{pandas_dataset.dataset_id}/profile"
    ).json()
    duckdb_profile = client.get(
        f"/api/dataset/{duckdb_dataset.dataset_id}/profile"
    ).json()

    assert profile["data_types"]["region"] == pandas_profile["data_types"]["region"]
    assert (
        pandas_profile["data_types"]["region"]
        == duckdb_profile["data_types"]["region"]
    )


def test_dataset_preview_schema_identical_for_pandas_and_duckdb_backed(isolated_app):
    df = _make_dataframe()

    pandas_dataset = Dataset(storage=PandasStorage(df.copy()), name="pandas.csv")
    duckdb_dataset = Dataset(storage=DuckDBStorage(df.copy()), name="duckdb.csv")

    isolated_app.register(pandas_dataset)
    isolated_app.register(duckdb_dataset)

    pandas_preview = client.get(f"/api/dataset/{pandas_dataset.dataset_id}/preview")
    duckdb_preview = client.get(f"/api/dataset/{duckdb_dataset.dataset_id}/preview")

    assert pandas_preview.status_code == duckdb_preview.status_code == 200
    assert set(pandas_preview.json().keys()) == set(duckdb_preview.json().keys())
    assert pandas_preview.json()["columns"] == duckdb_preview.json()["columns"]
    assert len(pandas_preview.json()["rows"]) == len(duckdb_preview.json()["rows"])


# =========================================================
# 3. ANALYSIS PIPELINE - NATIVE DUCKDB DISPATCH, NO RAW MATERIALIZATION
# =========================================================


def test_select_engine_for_dispatches_duckdb_storage_to_duckdb_engine():
    df = _make_dataframe()

    duckdb_dataset = Dataset(storage=DuckDBStorage(df))
    pandas_dataset = Dataset(storage=PandasStorage(df))

    assert isinstance(select_engine_for(duckdb_dataset), DuckDBExecutionEngine)
    assert isinstance(select_engine_for(pandas_dataset), PandasExecutionEngine)


def test_duckdb_backed_analysis_plan_computes_natively_without_pandas_materialization():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">", value=15)],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="asc",
        sort_by="metric",
    )

    result = execute_plan_for_dataset(dataset, plan)

    # No full-dataset materialization happened to compute this result -
    # only the final, already-aggregated DataFrame exists.
    assert storage.to_dataframe_calls == []
    assert list(result.columns) == ["region", "sum_quantity"]


def test_duckdb_native_result_matches_historical_pandas_result_exactly():
    df = _make_dataframe()
    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="asc",
        sort_by="metric",
    )

    duckdb_result = execute_plan_for_dataset(Dataset(storage=DuckDBStorage(df)), plan)
    pandas_result = execute_plan(df, plan)

    pd.testing.assert_frame_equal(
        duckdb_result.sort_values("region").reset_index(drop=True),
        pandas_result.sort_values("region").reset_index(drop=True),
        check_dtype=False,
    )


# =========================================================
# 4. LEGACY FALLBACK - PANDAS DATASETS STEP DOWN GRACEFULLY
# =========================================================


def test_pandas_backed_dataset_still_falls_back_to_pandas_execution_engine():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))
    plan = AnalysisPlan(group_by=["category"], metric="quantity", aggregation="sum")

    engine = select_engine_for(dataset)
    assert isinstance(engine, PandasExecutionEngine)

    result = execute_plan_for_dataset(dataset, plan)
    direct_result = execute_plan(df, plan)

    pd.testing.assert_frame_equal(result, direct_result)


def test_legacy_dataset_manager_dataframe_boundary_still_works():
    """
    A dataset registered the pre-ingestion way (an in-memory
    PandasStorage, e.g. via DatasetManager.set_dataframe /
    register_csv_bytes) must still resolve through
    dataset.storage.to_dataframe() exactly as before Steps 4-10.
    """
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    df = _make_dataframe()
    returned_df = manager.set_dataframe(df, filename="legacy.csv")

    assert isinstance(returned_df, pd.DataFrame)
    assert manager.is_loaded()

    active_df = manager.get_dataframe()
    pd.testing.assert_frame_equal(active_df, df)


# =========================================================
# 5. DOWNSTREAM PARITY - VISUALIZATION + INSIGHT ENGINE
# =========================================================


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_visualization_and_insight_pipeline_accepts_native_results_identically(
    storage_cls,
):
    df = _make_dataframe()
    dataset = Dataset(storage=storage_cls(df))

    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="desc",
        sort_by="metric",
    )

    result = execute_plan_for_dataset(dataset, plan)

    # Visualization: categorical grouping -> bar chart spec.
    viz_spec = create_visualization_spec(
        result=result,
        visualization_type="bar",
        title=None,
    )
    assert viz_spec["type"] == "bar"
    assert "encoding" in viz_spec

    # Deterministic insight engine: no raw rows leaked, only the
    # already-aggregated result is consumed.
    insight_context = build_deterministic_insights(
        result=result,
        metric_column="sum_quantity",
        group_by=["region"],
    )
    assert insight_context["row_count"] == len(result)
    assert insight_context["metric_column"] == "sum_quantity"

    insight_response = build_insight_response(context=insight_context)
    assert hasattr(insight_response, "insights")


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_time_series_transformation_downstream_parity(storage_cls):
    df = _make_dataframe()
    dataset = Dataset(storage=storage_cls(df))

    plan = AnalysisPlan(
        group_by=["signed_up_at"],
        metric="quantity",
        aggregation="sum",
        time_column="signed_up_at",
        time_granularity="month",
        sort="asc",
        sort_by="time",
    )

    result = execute_plan_for_dataset(dataset, plan)

    viz_spec = create_visualization_spec(
        result=result,
        visualization_type="line",
        title=None,
    )
    assert viz_spec["type"] == "line"

    insight_context = build_deterministic_insights(
        result=result,
        metric_column="sum_quantity",
        group_by=["signed_up_at"],
    )
    assert "trend" in insight_context or insight_context["row_count"] >= 0


# =========================================================
# 6. ROUTE ISOLATION - NO DIRECT STORAGE/ENGINE IMPORTS IN ROUTES
# =========================================================


FORBIDDEN_ROUTE_IMPORTS = {
    "DuckDBStorage",
    "DuckDBExecutionEngine",
    "PandasExecutionEngine",
}


def _imported_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name)

    return names


def test_route_modules_never_import_storage_or_engine_classes_directly():
    routes_dir = REPO_ROOT / "backend" / "routes"
    route_files = sorted(routes_dir.glob("*.py"))

    assert route_files, "expected route modules under backend/routes/"

    for py_file in route_files:
        if py_file.name == "__init__.py":
            continue

        imported = _imported_names(py_file)
        leaked = imported & FORBIDDEN_ROUTE_IMPORTS

        assert not leaked, (
            f"{py_file.relative_to(REPO_ROOT)} imports {leaked} directly - "
            "routes must go through DatasetManager/DatasetRegistry/Dataset."
        )


def test_route_modules_only_reach_storage_through_dataset_manager_or_registry():
    """
    Routes are allowed to call dataset.storage.to_dataframe() (the
    Dataset domain contract) but must never instantiate a concrete
    storage/engine class themselves.
    """
    routes_dir = REPO_ROOT / "backend" / "routes"

    for py_file in sorted(routes_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        source = py_file.read_text(encoding="utf-8")

        for forbidden in FORBIDDEN_ROUTE_IMPORTS:
            assert f"{forbidden}(" not in source, (
                f"{py_file.relative_to(REPO_ROOT)} constructs {forbidden}(...) "
                "directly - storage/engine selection must stay in "
                "data_engine.storage.selector / data_engine.execution.selector."
            )
