"""Step 55: API error handling and security hardening.

Verifies, at the FastAPI route level:
  - Unexpected internal exceptions in /api/analyze and
    /api/dataset/upload never leak their message through the HTTP
    response, but are still recorded in server-side logs.
  - Intentional client-facing errors (422 clarification, 503 missing
    AI API key) keep their existing behavior.
  - The uploaded filename is treated as untrusted metadata: directory
    components and control characters are stripped before it is
    stored or echoed back.
"""

import logging

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from ai.adapter import AnalysisClarificationError
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.storage import PandasStorage

client = TestClient(app)

SECRET = "SECRET-internal-detail /var/lib/app/db.sqlite password=hunter2"

QUESTION = "total quantity by region"

VALID_CSV = b"id,name,amount\n1,alice,10.5\n2,bob,20.0\n"


def _raise_secret(*args, **kwargs):
    raise RuntimeError(SECRET)


@pytest.fixture
def analysis_dataset(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)

    df = pd.DataFrame(
        {
            "region": ["north", "south", "east"],
            "quantity": [10, 20, 30],
        }
    )
    dataset = Dataset(storage=PandasStorage(df), owner_id="dev-user")
    dataset.cache["metadata"] = get_metadata(df)
    registry.register(dataset)
    return dataset


@pytest.fixture
def force_ai_planner(monkeypatch):
    """Make the fast planner decline so the AI planner path runs."""

    class _DecliningFastPlanner:
        def create_plan(self, **kwargs):
            return None

    monkeypatch.setattr(analysis_route, "FastPlanner", _DecliningFastPlanner)


@pytest.fixture
def upload_registry(tmp_path, monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path))
    return registry


def _ask(dataset_id: str, question: str = QUESTION):
    return client.post(
        "/api/analyze",
        json={"dataset_id": dataset_id, "question": question},
    )


def _upload(filename: str = "sample.csv", content: bytes = VALID_CSV):
    return client.post(
        "/api/dataset/upload",
        files={"file": (filename, content, "text/csv")},
    )


def _assert_not_leaked(response):
    assert SECRET not in response.text
    assert "hunter2" not in response.text


# =========================================================
# /api/analyze: UNEXPECTED 500s DO NOT LEAK
# =========================================================


@pytest.mark.parametrize(
    "target",
    [
        "get_cached_on_dataset",
        "validate_plan",
        "execute_plan_for_dataset",
        "create_visualization_spec",
    ],
)
def test_analyze_unexpected_error_is_generic_and_logged(
    analysis_dataset, monkeypatch, caplog, target
):
    monkeypatch.setattr(analysis_route, target, _raise_secret)

    with caplog.at_level(logging.ERROR, logger=analysis_route.logger.name):
        response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 500
    _assert_not_leaked(response)
    assert response.json()["detail"]
    assert SECRET in caplog.text


def test_analyze_dataset_loading_error_is_generic(analysis_dataset, monkeypatch):
    monkeypatch.setattr(analysis_route, "authorize_dataset", _raise_secret)

    response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 500
    _assert_not_leaked(response)


def test_ai_planner_unexpected_error_is_generic(
    analysis_dataset, force_ai_planner, monkeypatch, caplog
):
    monkeypatch.setattr(analysis_route, "create_analysis_plan", _raise_secret)

    with caplog.at_level(logging.ERROR, logger=analysis_route.logger.name):
        response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 500
    _assert_not_leaked(response)
    assert SECRET in caplog.text


@pytest.mark.parametrize(
    "target",
    ["build_deterministic_insights", "build_insight_response"],
)
def test_insight_failure_does_not_leak_in_success_response(
    analysis_dataset, monkeypatch, target
):
    monkeypatch.setattr(analysis_route, target, _raise_secret)

    response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 200
    _assert_not_leaked(response)
    assert response.json()["insight_error"]


# =========================================================
# /api/analyze: INTENTIONAL CLIENT ERRORS PRESERVED
# =========================================================


def test_missing_ai_api_key_still_returns_503(
    analysis_dataset, force_ai_planner, monkeypatch
):
    def _missing_key(**kwargs):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(analysis_route, "create_analysis_plan", _missing_key)

    response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 503
    assert "API key" in response.json()["detail"]


def test_clarification_still_returns_422_with_message(
    analysis_dataset, force_ai_planner, monkeypatch
):
    def _clarify(**kwargs):
        raise AnalysisClarificationError("Which date column should be used?")

    monkeypatch.setattr(analysis_route, "create_analysis_plan", _clarify)

    response = _ask(analysis_dataset.dataset_id)

    assert response.status_code == 422
    assert response.json()["detail"] == "Which date column should be used?"


# =========================================================
# /api/dataset/upload
# =========================================================


def test_upload_unexpected_error_is_generic_and_logged(
    upload_registry, monkeypatch, caplog
):
    monkeypatch.setattr("data_engine.connectors.csv_connector.ingest_to_parquet", _raise_secret)

    with caplog.at_level(logging.ERROR, logger=dataset_route.logger.name):
        response = _upload()

    assert response.status_code == 400
    _assert_not_leaked(response)
    assert SECRET in caplog.text
    assert upload_registry.list() == []


@pytest.mark.parametrize(
    "raw_filename",
    [
        "../../etc/sales.csv",
        "..\\..\\Windows\\sales.csv",
        "C:\\Users\\victim\\sales.csv",
        "sal\x1bes.csv",
    ],
)
def test_upload_filename_is_normalized(upload_registry, raw_filename):
    response = _upload(filename=raw_filename)

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "sales.csv"
    assert upload_registry.get(body["dataset_id"]).name == "sales.csv"


def test_sanitize_filename_strips_control_characters():
    # Checked directly: the HTTP client percent-encodes some control
    # bytes (e.g. NUL) in multipart headers before they reach the route.
    assert dataset_route._sanitize_filename("sal\x00es\x1b\x7f\n.csv") == "sales.csv"


def test_upload_overlong_filename_is_truncated(upload_registry):
    response = _upload(filename="a" * 1000 + ".csv")

    assert response.status_code == 200
    filename = response.json()["filename"]
    assert len(filename) == dataset_route.FILENAME_MAX_LENGTH
    assert filename.endswith(".csv")


def test_upload_filename_that_normalizes_to_empty_is_rejected(upload_registry):
    response = _upload(filename="../")

    assert response.status_code in (400, 422)
    assert upload_registry.list() == []
