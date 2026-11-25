"""
R5: concurrent cache misses for the same dataset and cache key share one
in-flight build on the analysis pool; waiting requests never occupy a
worker. Datasets stay isolated, failures are not remembered, and one
caller going away never cancels the build others are waiting on.
"""

import asyncio
import threading
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
import backend.shared_builds as shared_builds
from backend.main import app
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.metadata import get_metadata
from data_engine.storage import PandasStorage

client = TestClient(app)
# Unhandled route errors become plain 500 responses instead of being
# re-raised into the calling test thread.
lenient_client = TestClient(app, raise_server_exceptions=False)
QUESTION = "total quantity by region"


@pytest.fixture
def registry(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    return registry


@pytest.fixture
def manager(monkeypatch):
    # Two workers, like production: proves waiters don't take the second.
    manager = jobs.JobManager(max_workers=2)
    monkeypatch.setattr(jobs, "job_manager", manager)
    yield manager
    manager.shutdown(wait=True)


def _register(registry) -> Dataset:
    df = pd.DataFrame(
        {"region": ["north", "north", "south", "east"], "quantity": [10, 20, 30, 40]}
    )
    dataset = Dataset(storage=PandasStorage(df), owner_id="dev-user")
    registry.register(dataset)
    return dataset


class _GatedBuilder:
    """Builder that blocks until released and counts its calls."""

    def __init__(self, result=None, fail_first=False):
        self.gate = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self.lock = threading.Lock()
        self.result = result
        self.fail_first = fail_first

    def __call__(self, dataset):
        with self.lock:
            self.calls += 1
            call = self.calls
        self.started.set()
        assert self.gate.wait(timeout=15)
        if self.fail_first and call == 1:
            raise RuntimeError("first build fails")
        return self.result if self.result is not None else {"built_for": dataset.dataset_id}


def _get_concurrently(paths, http=None):
    http = http or client
    responses = [None] * len(paths)

    def _get(index, path):
        responses[index] = http.get(path)

    threads = [
        threading.Thread(target=_get, args=(i, p), daemon=True)
        for i, p in enumerate(paths)
    ]
    for thread in threads:
        thread.start()
    return threads, responses


class _WaiterCounter:
    """
    Wraps backend.shared_builds.await_shared to count requests that have
    reached the point of awaiting a shared build's Future - i.e. are
    waiting on the event loop, not on a worker.
    """

    def __init__(self):
        self._real = shared_builds.await_shared
        self._lock = threading.Lock()
        self.count = 0

    async def __call__(self, future):
        with self._lock:
            self.count += 1
        return await self._real(future)


def _count_waiters(monkeypatch, route_module) -> _WaiterCounter:
    # Routes import await_shared by name, so patch it where it is used.
    counter = _WaiterCounter()
    monkeypatch.setattr(route_module, "await_shared", counter)
    return counter


def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_concurrent_misses_share_one_build_and_one_worker(registry, manager, monkeypatch):
    dataset = _register(registry)
    builder = _GatedBuilder(result={"status": "healthy", "issue_count": 0, "issues": []})
    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", builder)
    waiters = _count_waiters(monkeypatch, dataset_route)

    path = f"/api/dataset/{dataset.dataset_id}/quality"
    threads, responses = _get_concurrently([path] * 4)

    try:
        assert builder.started.wait(timeout=10)
        # Deterministic: all four requests are awaiting the build before
        # the gate opens, so without sharing each would hold a slot.
        assert _wait_until(lambda: waiters.count == 4)
        # Only the one build holds a pool slot; nobody waits on a worker.
        assert manager.pending_count() == 1
        assert shared_builds.inflight_build_count() == 1
        # The second worker is still free for unrelated work.
        assert manager.run(lambda: "free").result(timeout=5) == "free"
    finally:
        builder.gate.set()
        for thread in threads:
            thread.join(timeout=15)

    assert [r.status_code for r in responses] == [200] * 4
    assert len({str(r.json()) for r in responses}) == 1
    assert builder.calls == 1
    assert dataset.cache["quality"] == responses[0].json()
    assert _wait_until(lambda: shared_builds.inflight_build_count() == 0)


def test_different_datasets_never_share_a_build(registry, manager, monkeypatch):
    first = _register(registry)
    second = _register(registry)
    builder = _GatedBuilder()
    monkeypatch.setattr(dataset_route, "metadata_for_dataset", builder)

    threads, responses = _get_concurrently(
        [
            f"/api/dataset/{first.dataset_id}/metadata",
            f"/api/dataset/{second.dataset_id}/metadata",
        ]
    )

    try:
        assert _wait_until(lambda: builder.calls == 2)
    finally:
        builder.gate.set()
        for thread in threads:
            thread.join(timeout=15)

    assert [r.status_code for r in responses] == [200, 200]
    assert {r.json()["built_for"] for r in responses} == {first.dataset_id, second.dataset_id}
    assert first.cache["metadata"]["built_for"] == first.dataset_id
    assert second.cache["metadata"]["built_for"] == second.dataset_id


def test_different_keys_on_one_dataset_build_separately(registry, manager, monkeypatch):
    dataset = _register(registry)
    quality = _GatedBuilder(result={"status": "healthy", "issue_count": 0, "issues": []})
    metadata = _GatedBuilder()
    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", quality)
    monkeypatch.setattr(dataset_route, "metadata_for_dataset", metadata)
    quality.gate.set()
    metadata.gate.set()

    assert client.get(f"/api/dataset/{dataset.dataset_id}/quality").status_code == 200
    assert client.get(f"/api/dataset/{dataset.dataset_id}/metadata").status_code == 200
    assert (quality.calls, metadata.calls) == (1, 1)


def test_failed_build_is_shared_then_forgotten_and_retried(registry, manager, monkeypatch):
    dataset = _register(registry)
    builder = _GatedBuilder(
        result={"status": "healthy", "issue_count": 0, "issues": []}, fail_first=True
    )
    monkeypatch.setattr(dataset_route, "check_quality_for_dataset", builder)
    waiters = _count_waiters(monkeypatch, dataset_route)
    path = f"/api/dataset/{dataset.dataset_id}/quality"

    threads, responses = _get_concurrently([path] * 2, http=lenient_client)
    try:
        assert builder.started.wait(timeout=10)
        # Both requests wait on the one build before it is allowed to fail.
        assert _wait_until(lambda: waiters.count == 2)
        assert shared_builds.inflight_build_count() == 1
    finally:
        builder.gate.set()
        for thread in threads:
            thread.join(timeout=15)

    # Both waiters saw the one failed build; nothing was cached.
    assert [r.status_code for r in responses] == [500, 500]
    assert builder.calls == 1
    assert "quality" not in dataset.cache
    assert _wait_until(lambda: shared_builds.inflight_build_count() == 0)

    # The next request builds again and succeeds.
    assert client.get(path).status_code == 200
    assert builder.calls == 2


def test_analyze_requests_share_planning_metadata_build(registry, manager, monkeypatch):
    dataset = _register(registry)  # no planning_metadata cached
    df = dataset.storage.to_dataframe()
    builder = _GatedBuilder(result=get_metadata(df))
    monkeypatch.setattr(analysis_route, "planning_metadata_for_dataset", builder)
    waiters = _count_waiters(monkeypatch, analysis_route)

    responses = [None, None]

    def _post(index):
        responses[index] = client.post(
            "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
        )

    threads = [threading.Thread(target=_post, args=(i,), daemon=True) for i in range(2)]
    for thread in threads:
        thread.start()

    try:
        assert builder.started.wait(timeout=10)
        # Deterministic: both requests are awaiting the one prewarm build
        # - neither pipeline has taken a worker to block on the dataset's
        # cache lock.
        assert _wait_until(lambda: waiters.count == 2)
        assert manager.pending_count() == 1
        assert shared_builds.inflight_build_count() == 1
    finally:
        builder.gate.set()
        for thread in threads:
            thread.join(timeout=15)

    assert [r.status_code for r in responses] == [200, 200]
    assert all(r.json()["success"] for r in responses)
    assert builder.calls == 1


def test_prewarm_failure_falls_back_to_pipeline_response(registry, manager, monkeypatch):
    dataset = _register(registry)

    def _broken(ds):
        raise RuntimeError("SECRET internal detail")

    monkeypatch.setattr(analysis_route, "planning_metadata_for_dataset", _broken)

    response = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": QUESTION}
    )

    # Exactly the pipeline's own pre-R5 response.
    assert response.status_code == 500
    assert response.json()["detail"] == "Metadata generation failed."
    assert "SECRET" not in response.text


def test_prewarm_skipped_for_requests_the_pipeline_rejects(registry, manager, monkeypatch):
    dataset = _register(registry)
    calls = []
    monkeypatch.setattr(
        analysis_route,
        "planning_metadata_for_dataset",
        lambda ds: calls.append(ds) or {},
    )

    empty = client.post(
        "/api/analyze", json={"dataset_id": dataset.dataset_id, "question": "   "}
    )
    missing = client.post(
        "/api/analyze", json={"dataset_id": "no-such-dataset", "question": QUESTION}
    )

    assert empty.status_code == 400
    assert missing.status_code == 404
    assert calls == []


def test_one_waiter_cancelling_never_cancels_the_shared_build(manager):
    gate = threading.Event()
    future = manager.run(lambda: gate.wait(timeout=15) and "done")

    async def _scenario():
        first = asyncio.ensure_future(shared_builds.await_shared(future))
        second = asyncio.ensure_future(shared_builds.await_shared(future))
        await asyncio.sleep(0.05)
        first.cancel()
        await asyncio.sleep(0.05)
        gate.set()
        return await second, first.cancelled()

    result, first_cancelled = asyncio.run(_scenario())

    assert first_cancelled
    assert result == "done"
    assert not future.cancelled()


def test_queue_full_registers_no_inflight_entry(registry, monkeypatch):
    dataset = _register(registry)
    manager = jobs.JobManager(max_workers=1, max_queue=1)
    monkeypatch.setattr(jobs, "job_manager", manager)
    gate = threading.Event()
    manager.run(lambda: gate.wait(timeout=15))
    manager.run(lambda: None)

    try:
        with pytest.raises(jobs.QueueFullError):
            shared_builds.shared_cache_build(dataset, "quality", lambda ds: {})
        assert shared_builds.inflight_build_count() == 0
    finally:
        gate.set()
        manager.shutdown(wait=True)
