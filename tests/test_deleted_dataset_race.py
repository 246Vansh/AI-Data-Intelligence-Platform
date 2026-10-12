"""
Step 77 - consistent 404 for a dataset deleted mid-request.

A request resolves and authorizes its Dataset, then a concurrent
DELETE closes that dataset's storage before the request reads from it.
The read must raise the dedicated StorageClosedError, and every route
that can hit it must answer with the same 404 a missing / unauthorized
dataset gets - while unrelated failures still stay 500s.

The race is simulated deterministically: the route's data-access
function is monkeypatched with a wrapper that deletes the dataset
(closing its storage) and then calls the real function - so the delete
always lands between authorization and the read, with no sleeps.
"""

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.dependencies as dependencies_module
import backend.jobs as jobs
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
import backend.routes.jobs as jobs_route
from backend.dependencies import AuthenticatedUser, dataset_not_found
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.storage import DatasetStorage, DuckDBStorage, StorageClosedError


OWNER = "dev-user"
QUESTION = "total quantity by region"
SECRET = "SECRET-internal-detail"

LEGACY_NOT_FOUND = {"detail": "No dataset has been uploaded yet."}


def _dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "east"],
            "quantity": [10, 20, 30, 40],
        }
    )


def _not_found_body(dataset_id: str) -> dict:
    return {"detail": dataset_not_found(dataset_id).detail}


@pytest.fixture
def registry(monkeypatch):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)

    return registry


@pytest.fixture
def client():
    # Unhandled exceptions become plain 500 responses instead of being
    # re-raised into the test, so "unrelated failure stays 500" is
    # observable the same way a real client would see it.
    return TestClient(app, raise_server_exceptions=False)


def _register(registry: DatasetRegistry, *, make_active: bool = False) -> Dataset:
    dataset = Dataset(
        storage=DuckDBStorage(_dataframe()),
        name="sales.csv",
        owner_id=OWNER,
    )
    registry.register(dataset)

    if make_active:
        # The fixture's DatasetManager, patched into the route module.
        dataset_route.dataset_manager._active_id = dataset.dataset_id

    return dataset


def _delete_then(registry: DatasetRegistry, dataset: Dataset, real):
    """Wrap `real` so the dataset is deleted right before it runs."""

    def _wrapped(*args, **kwargs):
        registry.delete(dataset.dataset_id)
        return real(*args, **kwargs)

    return _wrapped


def _raise(exc: Exception):
    def _wrapped(*args, **kwargs):
        raise exc

    return _wrapped


# =========================================================
# STORAGE: dedicated exception
# =========================================================


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.row_count(),
        lambda s: s.schema_info(),
        lambda s: s.to_dataframe(),
        lambda s: s.relation(),
        lambda s: s.execute_df("SELECT 1"),
        lambda s: s.execute_one("SELECT 1"),
        lambda s: s.column_statistics(),
        lambda s: s.connection,
    ],
)
def test_closed_duckdb_storage_raises_storage_closed_error(operation):
    storage = DuckDBStorage(_dataframe())
    storage.close()

    with pytest.raises(StorageClosedError):
        operation(storage)


def test_storage_closed_error_is_distinct_but_runtime_error_compatible():
    assert issubclass(StorageClosedError, RuntimeError)
    assert not isinstance(RuntimeError("boom"), StorageClosedError)


def test_registry_delete_closes_storage_so_later_reads_raise(registry):
    dataset = _register(registry)

    registry.delete(dataset.dataset_id)

    with pytest.raises(StorageClosedError):
        dataset.row_count


# =========================================================
# SYNCHRONOUS ANALYSIS
# =========================================================


def test_analysis_returns_404_when_deleted_before_metadata(
    registry, client, monkeypatch
):
    dataset = _register(registry)
    monkeypatch.setattr(
        analysis_route,
        "metadata_for_dataset",
        _delete_then(registry, dataset, analysis_route.metadata_for_dataset),
    )

    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert response.status_code == 404
    assert response.json() == _not_found_body(dataset.dataset_id)


def test_analysis_returns_404_when_deleted_before_execution(
    registry, client, monkeypatch
):
    dataset = _register(registry)
    dataset.cache["metadata"] = get_metadata(_dataframe())
    monkeypatch.setattr(
        analysis_route,
        "execute_plan_for_dataset",
        _delete_then(registry, dataset, analysis_route.execute_plan_for_dataset),
    )

    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert response.status_code == 404
    assert response.json() == _not_found_body(dataset.dataset_id)


def test_analysis_404_matches_missing_dataset_404(registry, client, monkeypatch):
    dataset = _register(registry)
    monkeypatch.setattr(
        analysis_route,
        "metadata_for_dataset",
        _delete_then(registry, dataset, analysis_route.metadata_for_dataset),
    )

    raced = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )
    missing = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert raced.status_code == missing.status_code == 404
    assert raced.json() == missing.json()


@pytest.mark.parametrize(
    "attribute", ["metadata_for_dataset", "execute_plan_for_dataset"]
)
def test_analysis_unrelated_runtime_error_stays_500(
    registry, client, monkeypatch, attribute
):
    dataset = _register(registry)
    if attribute == "execute_plan_for_dataset":
        # Pre-seed metadata so the request reaches execution.
        dataset.cache["metadata"] = get_metadata(_dataframe())
    monkeypatch.setattr(analysis_route, attribute, _raise(RuntimeError(SECRET)))

    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert response.status_code == 500
    assert SECRET not in response.text


# =========================================================
# PROFILE / PREVIEW / QUALITY / METADATA / SUMMARY
# =========================================================


# (route suffix, module attribute the route calls to read the storage)
_DATASET_ROUTES = [
    ("profile", "basic_statistics_for_dataset"),
    ("preview", "preview_dataset"),
    ("quality", "check_quality_for_dataset"),
    ("metadata", "metadata_for_dataset"),
]


@pytest.mark.parametrize("suffix,attribute", _DATASET_ROUTES)
def test_dataset_id_route_returns_404_when_deleted_mid_request(
    registry, client, monkeypatch, suffix, attribute
):
    dataset = _register(registry)
    real = getattr(dataset_route, attribute)
    monkeypatch.setattr(
        dataset_route, attribute, _delete_then(registry, dataset, real)
    )

    response = client.get(f"/api/dataset/{dataset.dataset_id}/{suffix}")

    assert response.status_code == 404
    assert response.json() == _not_found_body(dataset.dataset_id)


@pytest.mark.parametrize("suffix,attribute", _DATASET_ROUTES)
def test_legacy_route_returns_404_when_deleted_mid_request(
    registry, client, monkeypatch, suffix, attribute
):
    dataset = _register(registry, make_active=True)
    real = getattr(dataset_route, attribute)
    monkeypatch.setattr(
        dataset_route, attribute, _delete_then(registry, dataset, real)
    )

    response = client.get(f"/api/dataset/{suffix}")

    assert response.status_code == 404
    assert response.json() == LEGACY_NOT_FOUND


@pytest.mark.parametrize("suffix,attribute", _DATASET_ROUTES)
def test_dataset_route_unrelated_runtime_error_stays_500(
    registry, client, monkeypatch, suffix, attribute
):
    dataset = _register(registry)
    monkeypatch.setattr(dataset_route, attribute, _raise(RuntimeError(SECRET)))

    response = client.get(f"/api/dataset/{dataset.dataset_id}/{suffix}")

    assert response.status_code == 500
    assert SECRET not in response.text


def test_dataset_summary_returns_404_when_storage_closed(registry, client):
    dataset = _register(registry)
    # Registry entry still resolvable, storage already closed: the
    # window between authorize_dataset() and the row-count read.
    dataset.storage.close()

    response = client.get(f"/api/dataset/{dataset.dataset_id}")

    assert response.status_code == 404
    assert response.json() == _not_found_body(dataset.dataset_id)


# =========================================================
# DATASET LISTING
# =========================================================


class _FailingRowCountStorage(DatasetStorage):
    def __init__(self, exc: Exception):
        self._exc = exc

    def to_dataframe(self):
        raise self._exc

    def row_count(self):
        raise self._exc

    def column_count(self):
        return 2

    def column_names(self):
        return ["region", "quantity"]

    def close(self):
        pass


def test_listing_skips_dataset_closed_after_registry_snapshot(registry, client):
    gone = _register(registry)
    kept = _register(registry)
    # Still in the registry snapshot, but its storage is already closed.
    gone.storage.close()

    response = client.get("/api/dataset")

    assert response.status_code == 200
    ids = [entry["dataset_id"] for entry in response.json()["datasets"]]
    assert ids == [kept.dataset_id]


def test_listing_unrelated_row_count_failure_stays_500(registry, client):
    registry.register(
        Dataset(
            storage=_FailingRowCountStorage(RuntimeError(SECRET)),
            owner_id=OWNER,
        )
    )

    response = client.get("/api/dataset")

    assert response.status_code == 500
    assert SECRET not in response.text


# =========================================================
# ASYNC ANALYSIS JOBS
# =========================================================


def _run_job_synchronously(dataset: Dataset) -> dict:
    """Run one analysis job body inline, without the thread pool."""

    manager = jobs.JobManager(max_workers=1)
    try:
        request = analysis_route.AnalysisRequest(
            dataset_id=dataset.dataset_id, question=QUESTION
        )
        user = AuthenticatedUser(user_id=OWNER)
        job = jobs.Job(job_id="job-1", owner_id=OWNER, dataset_id=dataset.dataset_id)

        manager._run(job, lambda: jobs_route._run_analysis(request, user))

        return job.to_dict()
    finally:
        manager.shutdown(wait=True)


def test_job_reports_404_when_dataset_deleted_mid_run(registry, monkeypatch):
    dataset = _register(registry)
    monkeypatch.setattr(
        analysis_route,
        "metadata_for_dataset",
        _delete_then(registry, dataset, analysis_route.metadata_for_dataset),
    )

    job = _run_job_synchronously(dataset)

    assert job["status"] == jobs.JOB_FAILED
    assert job["error"] == {
        "status_code": 404,
        "detail": dataset_not_found(dataset.dataset_id).detail,
    }


def test_job_unrelated_runtime_error_is_not_reported_as_missing(
    registry, monkeypatch
):
    dataset = _register(registry)
    monkeypatch.setattr(
        analysis_route, "metadata_for_dataset", _raise(RuntimeError(SECRET))
    )

    job = _run_job_synchronously(dataset)

    assert job["status"] == jobs.JOB_FAILED
    assert job["error"]["status_code"] == 500
    assert SECRET not in str(job["error"])


def test_run_analysis_translates_closed_storage_404_into_job_error(
    registry, monkeypatch
):
    dataset = _register(registry)
    monkeypatch.setattr(
        analysis_route,
        "metadata_for_dataset",
        _delete_then(registry, dataset, analysis_route.metadata_for_dataset),
    )
    request = analysis_route.AnalysisRequest(
        dataset_id=dataset.dataset_id, question=QUESTION
    )

    with pytest.raises(jobs.JobError) as info:
        jobs_route._run_analysis(request, AuthenticatedUser(user_id=OWNER))

    assert info.value.status_code == 404
    assert isinstance(info.value.__cause__, HTTPException)
