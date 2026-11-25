"""
R5: share in-flight dataset cache builds between concurrent requests.

A cache miss on an expensive per-dataset computation (profile, quality,
exact metadata, planning metadata) runs once on the bounded analysis
pool. Concurrent requests for the same dataset and cache key await that
same Future on the event loop instead of each taking a pool worker just
to block on ``dataset.cache_lock`` until the first build finishes.

Nothing about locking inside the build changes: the shared work is
still ``get_cached_on_dataset()``, with its own cache_lock double-check
and the storage's own lock, so even a build started outside this module
(e.g. by an analysis job on a worker) is never duplicated.

``jobs.job_manager`` is resolved at call time so tests can substitute it.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

import backend.jobs as jobs
from data_engine.dataset import Dataset
from data_engine.dataset_manager import get_cached_on_dataset

# In-flight builds keyed by (Dataset, cache key). Dataset hashes by
# identity (eq=False), so two datasets never share an entry. An entry is
# removed as soon as its build finishes - successfully or not - so a
# failed build is retried by the next request rather than remembered.
# Lock order: _INFLIGHT_LOCK may be held while calling into the
# JobManager (which takes its own lock), never the reverse, and it is
# never held while a build runs.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_BUILDS: dict[tuple[Dataset, str], Future] = {}


def shared_cache_build(dataset: Dataset, key: str, builder) -> Future:
    """
    Return the in-flight Future building `key` for `dataset`, submitting
    one to the analysis pool if none is running. Raises
    jobs.QueueFullError, registering nothing, when the pool rejects it.
    """

    entry = (dataset, key)

    with _INFLIGHT_LOCK:
        future = _INFLIGHT_BUILDS.get(entry)

        if future is not None:
            return future

        future = jobs.job_manager.run(
            lambda: get_cached_on_dataset(dataset, key, builder)
        )
        _INFLIGHT_BUILDS[entry] = future

    def _forget(done: Future) -> None:
        with _INFLIGHT_LOCK:
            if _INFLIGHT_BUILDS.get(entry) is done:
                del _INFLIGHT_BUILDS[entry]

    future.add_done_callback(_forget)
    return future


async def await_shared(future: Future):
    """
    Await a pool Future other requests may also be waiting on.
    shield() keeps this caller's cancellation (e.g. a client disconnect)
    from cancelling the shared work; the outcome is always retrieved so
    an unobserved failure is never logged as "never retrieved".
    """

    inner = asyncio.wrap_future(future)
    inner.add_done_callback(lambda f: f.cancelled() or f.exception())
    return await asyncio.shield(inner)


def inflight_build_count() -> int:
    """Number of builds currently registered (diagnostics/tests)."""

    with _INFLIGHT_LOCK:
        return len(_INFLIGHT_BUILDS)
