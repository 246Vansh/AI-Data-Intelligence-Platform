"""
R4: query deadlines, interruption, cancellation isolation, lock release,
queue protection, and their HTTP mapping.

Every "slow" query here is CPU-only (a filtered COUNT over DuckDB's
range() table function - no rows are materialised, no memory is
allocated) and is always stopped by a sub-second deadline or interrupt;
test data is a handful of rows. Nothing here benchmarks anything.
"""

import threading
import time

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from ai.planner_models import PlannerTimeoutError
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_manager import get_cached_on_dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.storage import (
    DuckDBStorage,
    PandasStorage,
    QueryTimeoutError,
    StorageClosedError,
    check_deadline,
    query_deadline,
)

client = TestClient(app)

# Runs for many seconds unless interrupted; uses no memory.
SLOW_QUERY = "SELECT count(*) FROM range(100000000000) t(i) WHERE i % 7 = 3"
QUESTION = "total quantity by region"


def _df() -> pd.DataFrame:
    return pd.DataFrame({"region": ["north", "south", "east"], "quantity": [1, 2, 3]})


@pytest.fixture
def storage():
    storage = DuckDBStorage(_df())
    yield storage
    storage.close()


def _run_in_thread(fn):
    """Run fn() in a thread; returns (thread, outcome dict)."""
    outcome = {}

    def _target():
        start = time.monotonic()
        try:
            outcome["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - recorded for asserts
            outcome["error"] = exc
        outcome["elapsed"] = time.monotonic() - start

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread, outcome


# =========================================================
# Deadline primitive
# =========================================================


def test_deadline_nesting_never_extends_outer_deadline():
    with query_deadline(0.05):
        with query_deadline(60):
            time.sleep(0.1)
            with pytest.raises(QueryTimeoutError):
                check_deadline()


def test_no_deadline_means_no_bound():
    check_deadline()  # no active deadline: never raises
    with query_deadline(None):
        check_deadline()


# =========================================================
# Storage: interruption on deadline
# =========================================================


def test_deadline_interrupts_running_query_and_raises_timeout(storage):
    start = time.monotonic()

    with query_deadline(0.3):
        with pytest.raises(QueryTimeoutError) as excinfo:
            storage.execute_one(SLOW_QUERY)

    elapsed = time.monotonic() - start
    # Reported only after DuckDB confirmed the stop.
    assert isinstance(excinfo.value.__cause__, duckdb.InterruptException)
    assert 0.25 <= elapsed < 10

    # Connection usable and storage lock released afterwards.
    assert storage.execute_one("SELECT 42")[0] == 42
    assert storage._active_query_token is None


def test_expired_deadline_never_starts_the_query(storage):
    # A query that would fail if it ran: proves it never reached DuckDB.
    with query_deadline(0):
        with pytest.raises(QueryTimeoutError) as excinfo:
            storage.execute_df("SELECT * FROM no_such_table")

    # Not "cancelled": it never ran, so there is no interrupt cause.
    assert excinfo.value.__cause__ is None
    assert storage._active_query_token is None
    assert storage.execute_one("SELECT 1")[0] == 1


def test_queries_without_deadline_are_unaffected(storage):
    assert storage.execute_one("SELECT count(*) FROM range(1000)")[0] == 1000
    assert len(storage.to_dataframe()) == 3


def test_to_dataframe_honours_deadline(storage):
    with query_deadline(0):
        with pytest.raises(QueryTimeoutError):
            storage.to_dataframe()


def test_stale_interrupt_never_hits_a_later_query(storage):
    # A timer belonging to an earlier query (stale token) fires while a
    # different query runs: that query must keep running until its own
    # deadline, not stop early.
    def _later_query():
        with query_deadline(1.5):
            return storage.execute_one(SLOW_QUERY)

    thread, outcome = _run_in_thread(_later_query)
    time.sleep(0.3)
    storage._interrupt_if_active(object(), set(), "deadline")
    thread.join(timeout=15)

    assert not thread.is_alive()
    assert isinstance(outcome["error"], QueryTimeoutError)
    assert outcome["elapsed"] >= 1.3


def _query_starting_late(storage, delay):
    """
    Register a query as active, then wait `delay` before it actually
    starts executing - the window in which DuckDB silently drops an
    interrupt (its flag is reset when a query starts).
    """
    def _run():
        time.sleep(delay)
        return storage._connection.execute(SLOW_QUERY).fetchone()

    with storage._lock:
        storage._raise_if_closed()
        return storage._run_interruptible(_run)


def test_deadline_interrupt_landing_before_query_start_is_retried(storage):
    def _late():
        with query_deadline(0.1):  # fires during the 0.4s pre-start pause
            return _query_starting_late(storage, 0.4)

    thread, outcome = _run_in_thread(_late)
    thread.join(timeout=15)

    assert not thread.is_alive()
    assert isinstance(outcome["error"], QueryTimeoutError)
    assert outcome["elapsed"] < 5
    assert storage.execute_one("SELECT 1")[0] == 1


def test_close_interrupt_landing_before_query_start_is_retried():
    storage = DuckDBStorage(_df())
    thread, outcome = _run_in_thread(lambda: _query_starting_late(storage, 0.4))
    time.sleep(0.1)  # query registered, not yet executing

    started = time.monotonic()
    storage.close()

    assert time.monotonic() - started < 5
    thread.join(timeout=15)
    assert isinstance(outcome["error"], StorageClosedError)
    assert storage._closed


def test_completed_query_timer_does_not_affect_next_query(storage):
    with query_deadline(0.2):
        assert storage.execute_one("SELECT 1")[0] == 1
    time.sleep(0.4)  # the first query's timer would have fired by now
    assert storage.execute_one("SELECT count(*) FROM range(100000)")[0] == 100000


# =========================================================
# Cancellation isolation between datasets
# =========================================================


def test_timeout_on_one_dataset_never_interrupts_another():
    storage_a = DuckDBStorage(_df())
    storage_b = DuckDBStorage(_df())

    def _query(storage, seconds):
        with query_deadline(seconds):
            return storage.execute_one(SLOW_QUERY)

    try:
        thread_a, outcome_a = _run_in_thread(lambda: _query(storage_a, 0.3))
        thread_b, outcome_b = _run_in_thread(lambda: _query(storage_b, 1.5))
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert isinstance(outcome_a["error"], QueryTimeoutError)
        assert isinstance(outcome_b["error"], QueryTimeoutError)
        assert outcome_a["elapsed"] < 1.2
        # B ran to its own deadline - A's interrupt never reached it.
        assert outcome_b["elapsed"] >= 1.3
    finally:
        storage_a.close()
        storage_b.close()


def test_closing_one_dataset_never_interrupts_another():
    storage_a = DuckDBStorage(_df())
    storage_b = DuckDBStorage(_df())

    try:
        thread_b, outcome_b = _run_in_thread(
            lambda: _deadline_query(storage_b, 1.2)
        )
        time.sleep(0.2)
        storage_a.close()
        thread_b.join(timeout=15)

        assert isinstance(outcome_b["error"], QueryTimeoutError)
        assert outcome_b["elapsed"] >= 1.0
        assert storage_b.execute_one("SELECT 1")[0] == 1
    finally:
        storage_b.close()


def _deadline_query(storage, seconds):
    with query_deadline(seconds):
        return storage.execute_one(SLOW_QUERY)


# =========================================================
# close() interrupts the in-flight query; locks are released
# =========================================================


def test_close_interrupts_running_query_with_storage_closed_error():
    storage = DuckDBStorage(_df())
    temp_dir = storage._temp_dir

    thread, outcome = _run_in_thread(lambda: storage.execute_one(SLOW_QUERY))
    time.sleep(0.3)

    close_started = time.monotonic()
    storage.close()
    close_elapsed = time.monotonic() - close_started
    thread.join(timeout=15)

    assert not thread.is_alive()
    assert isinstance(outcome["error"], StorageClosedError)
    assert close_elapsed < 10
    assert storage._closed

    import os

    assert not os.path.exists(temp_dir)
    with pytest.raises(StorageClosedError):
        storage.execute_one("SELECT 1")


def test_storage_lock_released_after_query_error(storage):
    with pytest.raises(duckdb.Error):
        storage.execute_one("SELECT * FROM no_such_table")

    assert storage._active_query_token is None
    thread, outcome = _run_in_thread(lambda: storage.execute_one("SELECT 7"))
    thread.join(timeout=5)
    assert outcome["result"][0] == 7


def test_storage_lock_released_after_timeout_for_other_threads(storage):
    with query_deadline(0.2):
        with pytest.raises(QueryTimeoutError):
            storage.execute_one(SLOW_QUERY)

    thread, outcome = _run_in_thread(lambda: storage.execute_one("SELECT 9"))
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome["result"][0] == 9


def test_cache_lock_released_and_nothing_cached_after_timeout(storage):
    dataset = Dataset(storage=storage)

    def _builder(ds):
        with query_deadline(0.2):
            return ds.storage.execute_one(SLOW_QUERY)

    with pytest.raises(QueryTimeoutError):
        get_cached_on_dataset(dataset, "slow", _builder)

    assert "slow" not in dataset.cache

    acquired = []

    def _try_lock():
        got = dataset.cache_lock.acquire(timeout=2)
        acquired.append(got)
        if got:
            dataset.cache_lock.release()

    thread = threading.Thread(target=_try_lock)
    thread.start()
    thread.join(timeout=5)
    assert acquired == [True]


# =========================================================
# JobManager: task deadline and queue protection
# =========================================================


def _wait_job(manager, job_id, owner="u", timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id, owner)
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job never finished")


def test_job_exceeding_deadline_fails_with_504_and_frees_worker(storage):
    manager = jobs.JobManager(max_workers=1, task_timeout_seconds=0.3)

    try:
        job_id = manager.submit("u", "d", lambda: storage.execute_one(SLOW_QUERY))["job_id"]
        job = _wait_job(manager, job_id)

        assert job["status"] == "failed"
        assert job["error"] == jobs.TIMEOUT_JOB_ERROR
        assert job["error"]["status_code"] == 504

        # The worker is free again and the dataset still works.
        assert manager.run(lambda: storage.execute_one("SELECT 5")[0]).result(timeout=5) == 5
    finally:
        manager.shutdown(wait=True)


def test_run_future_carries_query_timeout(storage):
    manager = jobs.JobManager(max_workers=1, task_timeout_seconds=0.3)

    try:
        future = manager.run(lambda: storage.execute_one(SLOW_QUERY))
        assert isinstance(future.exception(timeout=15), QueryTimeoutError)
    finally:
        manager.shutdown(wait=True)


def _gated_manager(max_queue):
    manager = jobs.JobManager(max_workers=1, max_queue=max_queue)
    gate = threading.Event()
    started = threading.Event()

    def _hold():
        started.set()
        assert gate.wait(timeout=15)

    manager.run(_hold)
    assert started.wait(timeout=10)
    return manager, gate


def test_queue_saturation_rejects_without_queueing():
    manager, gate = _gated_manager(max_queue=1)

    try:
        try:
            queued = manager.run(lambda: "queued")  # fills the single queue slot

            with pytest.raises(jobs.QueueFullError):
                manager.run(lambda: "rejected")

            with pytest.raises(jobs.QueueFullError):
                manager.submit("u", "d", lambda: "rejected")

            # A rejected job leaves no record behind.
            assert manager._jobs == {}
            assert manager.pending_count() == 2
        finally:
            gate.set()

        assert queued.result(timeout=10) == "queued"

        deadline = time.monotonic() + 5
        while manager.pending_count() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.pending_count() == 0

        # Capacity is restored once work finishes.
        assert manager.run(lambda: "after").result(timeout=5) == "after"
    finally:
        # Releasing the gate first (inner finally) means this never
        # waits on the gated worker, even after a failed assertion.
        manager.shutdown(wait=True)


def test_capacity_released_after_failures():
    manager = jobs.JobManager(max_workers=1, max_queue=1)

    def _boom():
        raise RuntimeError("boom")

    try:
        for _ in range(5):  # would exceed capacity 2 if slots leaked
            assert isinstance(manager.run(_boom).exception(timeout=5), RuntimeError)
        deadline = time.monotonic() + 5
        while manager.pending_count() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.pending_count() == 0
    finally:
        manager.shutdown(wait=True)


# =========================================================
# HTTP mapping: 503 on a full pool, 504 on timeouts
# =========================================================


@pytest.fixture
def registry(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    return registry


def _register(registry, *, with_planning_metadata=True) -> Dataset:
    df = pd.DataFrame(
        {"region": ["north", "north", "south", "east"], "quantity": [10, 20, 30, 40]}
    )
    dataset = Dataset(storage=PandasStorage(df), owner_id="dev-user")
    if with_planning_metadata:
        dataset.cache["planning_metadata"] = get_metadata(df)
    registry.register(dataset)
    return dataset


@pytest.fixture
def full_manager(monkeypatch):
    manager, gate = _gated_manager(max_queue=1)
    manager.run(lambda: None)  # occupy the queue slot too
    monkeypatch.setattr(jobs, "job_manager", manager)
    yield manager
    gate.set()
    manager.shutdown(wait=True)


def test_full_pool_returns_503_for_sync_analyze(registry, full_manager):
    dataset = _register(registry)

    response = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(jobs.QUEUE_FULL_RETRY_AFTER_SECONDS)
    assert "busy" in response.json()["detail"]


def test_full_pool_returns_503_for_job_creation(registry, full_manager):
    dataset = _register(registry)

    response = client.post(
        "/api/jobs/analysis", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    assert response.status_code == 503
    assert "retry-after" in response.headers
    assert full_manager._jobs == {}


@pytest.mark.parametrize("suffix", ["profile", "quality", "metadata"])
def test_full_pool_returns_503_for_cache_miss_routes(registry, full_manager, suffix):
    dataset = _register(registry)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/{suffix}")

    assert response.status_code == 503
    assert "retry-after" in response.headers


def test_full_pool_does_not_affect_cache_hits_or_light_routes(registry, full_manager):
    dataset = _register(registry)
    dataset.cache["quality"] = {"status": "healthy", "issue_count": 0, "issues": []}

    assert client.get(f"/api/dataset/{dataset.dataset_id}/quality").status_code == 200
    assert client.get("/api/dataset").status_code == 200
    assert client.get(f"/api/dataset/{dataset.dataset_id}/preview").status_code == 200


@pytest.fixture
def manager(monkeypatch):
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)
    yield manager
    manager.shutdown(wait=True)


def _timeout_builder(*args, **kwargs):
    raise QueryTimeoutError("The query exceeded its time limit and was stopped.")


def test_metadata_timeout_returns_504_for_sync_analyze(registry, manager, monkeypatch):
    dataset = _register(registry, with_planning_metadata=False)
    monkeypatch.setattr(analysis_route, "planning_metadata_for_dataset", _timeout_builder)

    response = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    assert response.status_code == 504
    assert response.json()["detail"] == jobs.TIMEOUT_JOB_ERROR["detail"]


def test_execution_timeout_returns_504_for_sync_analyze(registry, manager, monkeypatch):
    dataset = _register(registry)
    monkeypatch.setattr(analysis_route, "execute_plan_for_dataset", _timeout_builder)

    response = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    assert response.status_code == 504


def test_execution_timeout_fails_job_with_504(registry, manager, monkeypatch):
    dataset = _register(registry)
    monkeypatch.setattr(analysis_route, "execute_plan_for_dataset", _timeout_builder)

    job_id = client.post(
        "/api/jobs/analysis", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    ).json()["job_id"]
    job = _wait_job(manager, job_id, owner="dev-user")

    assert job["status"] == "failed"
    assert job["error"] == jobs.TIMEOUT_JOB_ERROR


@pytest.mark.parametrize(
    "suffix,builder_name",
    [
        ("profile", "basic_statistics_for_dataset"),
        ("quality", "check_quality_for_dataset"),
        ("metadata", "metadata_for_dataset"),
    ],
)
def test_cache_build_timeout_returns_504(registry, manager, monkeypatch, suffix, builder_name):
    dataset = _register(registry)
    monkeypatch.setattr(dataset_route, builder_name, _timeout_builder)

    response = client.get(f"/api/dataset/{dataset.dataset_id}/{suffix}")

    assert response.status_code == 504


def _force_ai_planner(monkeypatch):
    class _DecliningFastPlanner:
        def create_plan(self, **kwargs):
            return None

    monkeypatch.setattr(analysis_route, "FastPlanner", _DecliningFastPlanner)


def test_ai_planner_timeout_returns_504(registry, manager, monkeypatch):
    dataset = _register(registry)
    _force_ai_planner(monkeypatch)

    def _planner_timeout(**kwargs):
        raise PlannerTimeoutError("The AI planner request timed out.")

    monkeypatch.setattr(analysis_route, "create_analysis_plan", _planner_timeout)

    response = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    assert response.status_code == 504
    assert "AI planner" in response.json()["detail"]


def test_ai_planner_not_called_after_deadline(registry, monkeypatch):
    dataset = _register(registry)
    _force_ai_planner(monkeypatch)
    calls = []
    monkeypatch.setattr(
        analysis_route, "create_analysis_plan", lambda **kw: calls.append(kw)
    )
    manager = jobs.JobManager(max_workers=1, task_timeout_seconds=0.2)
    monkeypatch.setattr(jobs, "job_manager", manager)

    real_fast_planner = analysis_route.FastPlanner

    class _SlowDecliningPlanner(real_fast_planner):
        def create_plan(self, **kwargs):
            time.sleep(0.4)  # burn past the task deadline
            return None

    monkeypatch.setattr(analysis_route, "FastPlanner", _SlowDecliningPlanner)

    try:
        response = client.post(
            "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
        )
    finally:
        manager.shutdown(wait=True)

    assert response.status_code == 504
    assert calls == []


# =========================================================
# AI client settings
# =========================================================


def test_ai_client_settings_defaults_and_validation(monkeypatch):
    from ai.providers import client_settings as settings

    monkeypatch.delenv("AI_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AI_MAX_RETRIES", raising=False)
    assert settings.read_request_timeout() == 60.0
    assert settings.read_max_retries() == 2

    monkeypatch.setenv("AI_REQUEST_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("AI_MAX_RETRIES", "0")
    assert settings.read_request_timeout() == 15.0
    assert settings.read_max_retries() == 0

    for bad_timeout in ("abc", "0", "-5"):
        monkeypatch.setenv("AI_REQUEST_TIMEOUT_SECONDS", bad_timeout)
        assert settings.read_request_timeout() == 60.0

    for bad_retries in ("x", "-1", "99"):
        monkeypatch.setenv("AI_MAX_RETRIES", bad_retries)
        assert settings.read_max_retries() == 2
