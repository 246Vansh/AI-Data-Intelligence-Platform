"""Step 56: minimal asynchronous analysis jobs.

Verifies, at the FastAPI route level:
  - POST /api/jobs/analysis queues a job for a dataset the caller owns
    and returns immediately with a job_id.
  - Jobs move queued -> running -> completed/failed, and a completed
    job's result is the unchanged synchronous /api/analyze payload.
  - Ownership: jobs can only be created for the caller's own
    datasets, and a job is invisible to every other user.
  - Internal exceptions never leak through the job status API.
  - The synchronous /api/analyze route is unaffected.

Each test gets its own JobManager and DatasetRegistry patched in, so
nothing touches the process-wide singletons.
"""

import logging
import threading
import time

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from backend.dependencies import DEV_USER_ID_ENV_VAR
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.storage import PandasStorage

client = TestClient(app)

QUESTION = "total quantity by region"

SECRET = "SECRET-internal-detail password=hunter2"


@pytest.fixture
def registry(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    return registry


@pytest.fixture
def manager(monkeypatch):
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)
    yield manager
    manager.shutdown(wait=True)


def _register(registry: DatasetRegistry, owner_id: str = "dev-user") -> Dataset:
    df = pd.DataFrame(
        {
            "region": ["north", "north", "south", "east"],
            "quantity": [10, 20, 30, 40],
        }
    )
    dataset = Dataset(storage=PandasStorage(df), owner_id=owner_id)
    dataset.cache["planning_metadata"] = get_metadata(df)
    registry.register(dataset)
    return dataset


def _create_job(dataset_id: str, question: str = QUESTION):
    return client.post(
        "/api/jobs/analysis",
        json={"dataset_id": dataset_id, "question": question},
    )


def _get_job(job_id: str):
    return client.get(f"/api/jobs/{job_id}")


def _wait_for_status(job_id: str, statuses, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        body = _get_job(job_id).json()
        if body["status"] in statuses:
            return body
        time.sleep(0.01)

    raise AssertionError(f"job {job_id} never reached {statuses}")


def _blocking_analyze(gate: threading.Event, started: threading.Event):
    real = analysis_route.analyze_dataset

    def _analyze(request, user):
        started.set()
        assert gate.wait(timeout=10)
        return real(request, user)

    return _analyze


# =========================================================
# CREATION + SUCCESSFUL RESULT
# =========================================================


def test_create_job_returns_202_with_job_metadata(registry, manager):
    dataset = _register(registry)

    response = _create_job(dataset.dataset_id)

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["owner_id"] == "dev-user"
    assert body["dataset_id"] == dataset.dataset_id
    assert body["status"] in ("queued", "running", "completed")
    assert body["created_at"]
    assert body["updated_at"]


def test_completed_job_result_matches_sync_analyze(registry, manager):
    dataset = _register(registry)

    job_id = _create_job(dataset.dataset_id).json()["job_id"]
    body = _wait_for_status(job_id, ("completed", "failed"))

    assert body["status"] == "completed"
    assert body["error"] is None
    assert body["owner_id"] == "dev-user"
    assert body["dataset_id"] == dataset.dataset_id

    sync = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    ).json()

    result = body["result"]
    assert set(result) == set(sync)
    for key in ("success", "question", "planner", "data", "plan", "visualization"):
        assert result[key] == sync[key]


# =========================================================
# LIFECYCLE: queued -> running -> completed
# =========================================================


def test_job_lifecycle_queued_running_completed(registry, manager, monkeypatch):
    dataset = _register(registry)
    gate = threading.Event()
    started = threading.Event()
    monkeypatch.setattr(
        analysis_route, "analyze_dataset", _blocking_analyze(gate, started)
    )

    # With one worker, the first job occupies it, so the second queues.
    first = _create_job(dataset.dataset_id).json()["job_id"]
    assert started.wait(timeout=10)
    second = _create_job(dataset.dataset_id).json()["job_id"]

    assert _get_job(first).json()["status"] == "running"
    queued = _get_job(second).json()
    assert queued["status"] == "queued"
    assert queued["result"] is None and queued["error"] is None

    gate.set()

    for job_id in (first, second):
        done = _wait_for_status(job_id, ("completed", "failed"))
        assert done["status"] == "completed"
        assert done["updated_at"] >= done["created_at"]


# =========================================================
# FAILURES
# =========================================================


def test_client_safe_pipeline_error_is_reported(registry, manager, monkeypatch):
    dataset = _register(registry)

    def _reject(request, user):
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    monkeypatch.setattr(analysis_route, "analyze_dataset", _reject)

    job_id = _create_job(dataset.dataset_id).json()["job_id"]
    body = _wait_for_status(job_id, ("completed", "failed"))

    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] == {"status_code": 400, "detail": "Question cannot be empty."}


def test_internal_exception_does_not_leak(registry, manager, monkeypatch, caplog):
    dataset = _register(registry)

    def _explode(request, user):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(analysis_route, "analyze_dataset", _explode)

    with caplog.at_level(logging.ERROR, logger=jobs.logger.name):
        job_id = _create_job(dataset.dataset_id).json()["job_id"]
        body = _wait_for_status(job_id, ("completed", "failed"))
        response = _get_job(job_id)

    assert body["status"] == "failed"
    assert body["error"] == jobs.GENERIC_JOB_ERROR
    assert SECRET not in response.text
    assert "hunter2" not in response.text
    assert SECRET in caplog.text


def test_step55_sanitized_500_is_carried_through(registry, manager, monkeypatch):
    # A real pipeline stage failing: the job reports the same generic
    # detail the sync route would, never the underlying message.
    dataset = _register(registry)

    def _explode(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(analysis_route, "execute_plan_for_dataset", _explode)

    job_id = _create_job(dataset.dataset_id).json()["job_id"]
    body = _wait_for_status(job_id, ("completed", "failed"))

    assert body["status"] == "failed"
    assert body["error"]["status_code"] == 500
    assert SECRET not in str(body)


# =========================================================
# NOT FOUND + OWNERSHIP
# =========================================================


def test_nonexistent_job_returns_404(registry, manager):
    response = _get_job("does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


def test_other_user_cannot_read_job(registry, manager, monkeypatch):
    dataset = _register(registry)
    job_id = _create_job(dataset.dataset_id).json()["job_id"]
    _wait_for_status(job_id, ("completed", "failed"))

    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "mallory")
    response = _get_job(job_id)

    # Identical to a nonexistent job - no existence oracle.
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."
    assert "result" not in response.json()


def test_cannot_create_job_for_other_users_dataset(registry, manager, monkeypatch):
    dataset = _register(registry, owner_id="alice")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "mallory")

    submitted = []
    monkeypatch.setattr(manager, "submit", lambda **kw: submitted.append(kw))

    response = _create_job(dataset.dataset_id)

    assert response.status_code == 404
    assert submitted == []


def test_cannot_create_job_for_nonexistent_dataset(registry, manager):
    response = _create_job("no-such-dataset")

    assert response.status_code == 404


def test_job_keeps_creation_owner_and_dataset(registry, manager, monkeypatch):
    alice_ds = _register(registry, owner_id="alice")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "alice")

    job_id = _create_job(alice_ds.dataset_id).json()["job_id"]
    body = _wait_for_status(job_id, ("completed", "failed"))

    assert body["owner_id"] == "alice"
    assert body["dataset_id"] == alice_ds.dataset_id
    assert body["status"] == "completed"


# =========================================================
# SYNC /api/analyze UNCHANGED
# =========================================================


def test_sync_analyze_still_returns_full_result(registry, manager):
    dataset = _register(registry)

    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "job_id" not in body
    assert body["data"]["row_count"] == 3


def test_sync_analyze_shares_bounded_analysis_pool(registry, manager, monkeypatch):
    dataset = _register(registry)
    gate = threading.Event()
    started = threading.Event()
    monkeypatch.setattr(
        analysis_route, "analyze_dataset", _blocking_analyze(gate, started)
    )

    # A job occupies the only analysis worker.
    job_id = _create_job(dataset.dataset_id).json()["job_id"]
    assert started.wait(timeout=10)
    started.clear()

    responses = []
    caller = threading.Thread(
        target=lambda: responses.append(
            client.post(
                "/api/analyze",
                json={"dataset_id": dataset.dataset_id, "question": QUESTION},
            )
        )
    )
    caller.start()

    # The sync request waits for the same pool instead of running
    # alongside the job, and other routes stay responsive meanwhile.
    assert not started.wait(timeout=0.5)
    assert _get_job(job_id).json()["status"] == "running"

    gate.set()
    caller.join(timeout=10)

    assert responses and responses[0].status_code == 200
    assert responses[0].json()["success"] is True
    assert _wait_for_status(job_id, ("completed", "failed"))["status"] == "completed"


def test_list_and_preview_respond_while_analysis_pool_is_full(
    registry, manager, monkeypatch
):
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    dataset = _register(registry)

    gate = threading.Event()
    first_started = threading.Event()
    lock = threading.Lock()
    running = 0
    peak = 0
    started_count = 0
    real = analysis_route.analyze_dataset

    def _tracked_analyze(request, user):
        nonlocal running, peak, started_count
        with lock:
            running += 1
            started_count += 1
            peak = max(peak, running)
        first_started.set()
        try:
            assert gate.wait(timeout=10)
            return real(request, user)
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(analysis_route, "analyze_dataset", _tracked_analyze)

    # Signal once the second request has handed its work to the
    # executor. The endpoint resolves jobs.job_manager.run at call
    # time, so wrapping it on this test's manager observes submission
    # without touching production code.
    second_submitted = threading.Event()
    submissions = 0
    real_run = manager.run

    def _observed_run(work):
        nonlocal submissions
        future = real_run(work)
        with lock:
            submissions += 1
            if submissions == 2:
                second_submitted.set()
        return future

    monkeypatch.setattr(manager, "run", _observed_run)

    responses = []

    def _post_analyze():
        responses.append(
            client.post(
                "/api/analyze",
                json={"dataset_id": dataset.dataset_id, "question": QUESTION},
            )
        )

    callers = [threading.Thread(target=_post_analyze) for _ in range(2)]

    try:
        callers[0].start()
        assert first_started.wait(timeout=10)
        callers[1].start()

        # The second analysis is queued on the executor, but cannot
        # start while the gated first one holds the single worker.
        assert second_submitted.wait(timeout=10)
        with lock:
            assert started_count == 1

        # Listing and preview are still served while the pool is full.
        listing = client.get("/api/dataset")
        assert listing.status_code == 200
        assert [d["dataset_id"] for d in listing.json()["datasets"]] == [
            dataset.dataset_id
        ]

        preview = client.get(f"/api/dataset/{dataset.dataset_id}/preview")
        assert preview.status_code == 200

    finally:
        gate.set()
        for caller in callers:
            if caller.ident is not None:
                caller.join(timeout=10)

    assert not any(caller.is_alive() for caller in callers)
    assert [r.status_code for r in responses] == [200, 200]
    assert started_count == 2
    assert peak == 1


def test_sync_analyze_other_users_dataset_still_404(registry, manager, monkeypatch):
    dataset = _register(registry, owner_id="alice")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "mallory")

    response = client.post(
        "/api/analyze",
        json={"dataset_id": dataset.dataset_id, "question": QUESTION},
    )

    assert response.status_code == 404


# =========================================================
# JobManager retention
# =========================================================


def test_finished_jobs_are_evicted_past_retention_cap():
    manager = jobs.JobManager(max_workers=1, max_retained_jobs=2)

    def _submit_and_finish() -> str:
        job_id = manager.submit("u", "d", lambda: 1)["job_id"]
        deadline = time.monotonic() + 10
        while manager.get(job_id, "u")["status"] != "completed":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        return job_id

    try:
        ids = [_submit_and_finish() for _ in range(2)]
        newest = _submit_and_finish()

        assert manager.get(ids[0], "u") is None
        assert manager.get(ids[1], "u") is not None
        assert manager.get(newest, "u")["status"] == "completed"

    finally:
        manager.shutdown(wait=True)
