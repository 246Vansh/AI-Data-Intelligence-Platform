"""Step 37: Dataset.cache concurrent first-computation race.

get_cached_on() and get_cached_on_dataset() (data_engine/dataset_manager.py)
memoize an expensive builder's result on Dataset.cache. Before this fix,
the check -> build -> set sequence was unsynchronized, so concurrent
first requests for the same Dataset/key could each observe a cache miss
and run the (potentially expensive) builder more than once.

Dataset now carries an instance-local `cache_lock` (RLock), and both
helpers re-check the cache inside that lock before calling builder(),
so a given Dataset/key is computed at most once even under concurrent
first access. These tests exercise that guarantee directly against the
two helpers - no HTTP layer involved.
"""

import threading
import time

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.dataset_manager import get_cached_on, get_cached_on_dataset
from data_engine.storage import PandasStorage


def _make_dataset() -> Dataset:
    df = pd.DataFrame({"a": [1, 2, 3]})
    return Dataset(storage=PandasStorage(df))


class _CountingBuilder:
    """
    A builder that counts invocations and can be made to block until a
    barrier releases it, so a race between concurrent first-accessors
    can be forced deterministically instead of relying on timing.

    Each instance is tagged with a unique id at construction, so two
    different _CountingBuilder instances can never produce the same
    return value by coincidence (e.g. two builders both seeing "call
    1" for arguments that happen to share a recycled id()).
    """

    _next_tag = 0

    def __init__(self, release: threading.Event | None = None):
        self.calls = 0
        self._lock = threading.Lock()
        self._release = release
        self.seen_args = []

        self.tag = _CountingBuilder._next_tag
        _CountingBuilder._next_tag += 1

    def __call__(self, arg):
        with self._lock:
            self.calls += 1

        self.seen_args.append(arg)

        if self._release is not None:
            # Hold every concurrent caller here until the test releases
            # them all at once, maximizing the chance any unsynchronized
            # implementation would double-compute.
            self._release.wait(timeout=5)

        return f"value-from-builder-{self.tag}-call-{self.calls}"


def _run_concurrently(fn, count: int):
    """
    Run `fn` (no-args) on `count` threads, started as close together as
    possible via a barrier, and return their results in start order.
    """

    barrier = threading.Barrier(count)
    results = [None] * count
    errors = []

    def _target(index):
        try:
            barrier.wait(timeout=5)
            results[index] = fn()
        except Exception as exc:  # pragma: no cover - surfaced via errors
            errors.append(exc)

    threads = [threading.Thread(target=_target, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"worker thread(s) raised: {errors}"
    return results


# =========================================================
# 1. Sequential cache hit still avoids rebuilding.
# =========================================================


@pytest.mark.parametrize("helper", [get_cached_on, get_cached_on_dataset])
def test_sequential_second_call_is_a_cache_hit(helper):
    dataset = _make_dataset()
    builder = _CountingBuilder()

    first = helper(dataset, "stat", builder)
    second = helper(dataset, "stat", builder)

    assert builder.calls == 1
    assert second == first
    assert dataset.cache["stat"] == first


# =========================================================
# 2. Concurrent first access for the same dataset/key calls
#    builder exactly once.
# =========================================================


@pytest.mark.parametrize("helper", [get_cached_on, get_cached_on_dataset])
def test_concurrent_first_access_builds_exactly_once(helper):
    dataset = _make_dataset()
    release = threading.Event()
    builder = _CountingBuilder(release=release)

    thread_count = 8
    barrier = threading.Barrier(thread_count + 1)
    results = [None] * thread_count
    errors = []

    def _worker(index):
        try:
            barrier.wait(timeout=5)
            results[index] = helper(dataset, "stat", builder)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()

    # Release every worker at (as close to) the same instant.
    barrier.wait(timeout=5)

    # Give the racing threads a moment to all reach the blocking builder
    # call before letting any of them finish, so a broken (unsynchronized)
    # implementation has every opportunity to let more than one thread
    # past the "key in dataset.cache" check.
    time.sleep(0.1)
    release.set()

    for t in threads:
        t.join(timeout=10)

    assert not errors, f"worker thread(s) raised: {errors}"
    assert builder.calls == 1, "builder ran more than once for concurrent first access"

    # Every caller observed the same, single computed value.
    assert all(r == results[0] for r in results)
    assert dataset.cache["stat"] == results[0]


# =========================================================
# 3. Different cache keys remain independently usable.
# =========================================================


@pytest.mark.parametrize("helper", [get_cached_on, get_cached_on_dataset])
def test_different_keys_are_independent(helper):
    dataset = _make_dataset()
    builder_a = _CountingBuilder()
    builder_b = _CountingBuilder()

    value_a = helper(dataset, "a", builder_a)
    value_b = helper(dataset, "b", builder_b)

    assert builder_a.calls == 1
    assert builder_b.calls == 1
    assert value_a != value_b
    assert set(dataset.cache.keys()) == {"a", "b"}

    # Re-fetching one key doesn't touch the other's builder.
    helper(dataset, "a", builder_a)
    assert builder_a.calls == 1
    assert builder_b.calls == 1


# =========================================================
# 4. Different Dataset instances do not share the lock/cache.
# =========================================================


def test_different_datasets_have_independent_locks_and_caches():
    dataset_1 = _make_dataset()
    dataset_2 = _make_dataset()

    assert dataset_1.cache_lock is not dataset_2.cache_lock
    assert dataset_1.cache is not dataset_2.cache

    builder_1 = _CountingBuilder()
    builder_2 = _CountingBuilder()

    get_cached_on(dataset_1, "stat", builder_1)
    get_cached_on(dataset_2, "stat", builder_2)

    assert builder_1.calls == 1
    assert builder_2.calls == 1
    assert dataset_1.cache["stat"] != dataset_2.cache["stat"]

    # A slow, first-access build on dataset_1 must never block a
    # concurrent first-access build on dataset_2.
    release = threading.Event()
    slow_builder = _CountingBuilder(release=release)
    fast_builder = _CountingBuilder()

    fast_result_holder = {}

    def _fast_call():
        fast_result_holder["value"] = get_cached_on(dataset_2, "other", fast_builder)

    slow_thread = threading.Thread(
        target=get_cached_on, args=(dataset_1, "other", slow_builder)
    )
    slow_thread.start()

    # Wait until the slow builder is actually blocked inside its call,
    # confirming dataset_1's lock is held.
    deadline = time.time() + 5
    while slow_builder.calls == 0 and time.time() < deadline:
        time.sleep(0.01)
    assert slow_builder.calls == 1

    fast_thread = threading.Thread(target=_fast_call)
    fast_thread.start()
    fast_thread.join(timeout=5)

    assert "value" in fast_result_holder, "dataset_2's cache build was blocked by dataset_1's lock"
    assert fast_builder.calls == 1

    release.set()
    slow_thread.join(timeout=5)
    assert slow_builder.calls == 1


# =========================================================
# 5. Both get_cached_on() and get_cached_on_dataset() are protected.
# =========================================================


def test_get_cached_on_passes_materialized_dataframe():
    dataset = _make_dataset()
    seen = []

    def builder(df):
        seen.append(df)
        return "profile"

    result = get_cached_on(dataset, "profile", builder)

    assert result == "profile"
    assert len(seen) == 1
    assert seen[0] is not dataset  # received the DataFrame, not the Dataset


def test_get_cached_on_dataset_passes_dataset_itself():
    dataset = _make_dataset()
    seen = []

    def builder(ds):
        seen.append(ds)
        return "metadata"

    result = get_cached_on_dataset(dataset, "metadata", builder)

    assert result == "metadata"
    assert len(seen) == 1
    assert seen[0] is dataset


# =========================================================
# 6. Existing cache behavior remains unchanged.
# =========================================================


def test_cache_is_still_a_plain_dict_after_use():
    dataset = _make_dataset()

    get_cached_on(dataset, "stat", lambda df: "v1")
    get_cached_on_dataset(dataset, "meta", lambda ds: "v2")

    assert isinstance(dataset.cache, dict)
    assert dataset.cache == {"stat": "v1", "meta": "v2"}


def test_returned_value_is_the_exact_cached_object():
    dataset = _make_dataset()
    sentinel = object()

    result = get_cached_on(dataset, "obj", lambda df: sentinel)

    assert result is sentinel
    assert dataset.cache["obj"] is sentinel

    # Second call returns the same object, not a rebuilt one.
    result_2 = get_cached_on(dataset, "obj", lambda df: object())
    assert result_2 is sentinel
