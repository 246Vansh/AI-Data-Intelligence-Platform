"""Step 33: shared duplicate-row computation.

Step 32 found that DuckDBProfilingEngine.basic_statistics() and
DuckDBQualityEngine.check_quality() each independently run the same
expensive exact scan - `SELECT COUNT(*) FROM (SELECT DISTINCT * FROM
table)` - to get the same scalar (duplicate_rows / duplicate_count).

DuckDBStorage.distinct_row_count() now memoizes that scalar once per
instance (i.e. once per dataset), guarded by the instance's existing
per-connection lock, and both engines route through it instead of each
running their own copy of the scan.

Step 38 replaced the scan itself (single full-table `SELECT DISTINCT
*`) with one-pass physical hash partitioning - see
DuckDBStorage._compute_distinct_row_count_partitioned() - but left
distinct_row_count()'s memoization/locking contract, and both engines'
call sites, unchanged. The "runs exactly once" tests below now spy on
that private computation method directly (rather than counting
`SELECT DISTINCT *` occurrences in executed SQL, which now legitimately
runs once per non-empty partition instead of once per dataset), and the
"builder" tests are updated to reflect that the `compute` callable
callers still pass in is accepted only for call-site compatibility and
is never actually invoked any more.

Verifies:
  - profiling's duplicate_rows stays exactly correct.
  - quality's duplicate_rows count stays exactly correct.
  - the expensive partitioned computation runs exactly once per
    dataset no matter which engine (or order) touches it first,
    including under concurrent first access.
  - the existing dataset.cache / get_cached_on_dataset behavior for
    the full basic_statistics/quality results is untouched.
"""

import threading

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.dataset_manager import get_cached_on_dataset
from data_engine.profiling import basic_statistics_for_dataset
from data_engine.quality import check_quality_for_dataset
from data_engine.storage import DuckDBStorage


def _make_dataframe_with_duplicates() -> pd.DataFrame:
    # 2 exact duplicate rows (rows 0 and 2 are identical), 4 unique.
    return pd.DataFrame(
        {
            "region": ["north", "south", "north", "east", "west", "south"],
            "quantity": [10, 20, 10, 40, 50, 20],
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that counts how many times it actually runs the
    expensive partitioned distinct-row computation (COPY + per-partition
    `SELECT DISTINCT *` scans), regardless of which engine triggered
    it. Spies on the private computation method itself rather than on
    individual `SELECT DISTINCT *` occurrences, since Step 38 legitimately
    runs one such scan per non-empty partition instead of one per
    dataset."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.distinct_computation_calls = 0

    def _compute_distinct_row_count_partitioned(self):
        self.distinct_computation_calls += 1
        return super()._compute_distinct_row_count_partitioned()


# =========================================================
# CORRECTNESS - profiling and quality each still report the exact
# right duplicate count.
# =========================================================


def test_profiling_reports_correct_duplicate_rows():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe_with_duplicates()))

    stats = basic_statistics_for_dataset(dataset)

    assert stats["duplicate_rows"] == 2


def test_quality_reports_correct_duplicate_rows():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe_with_duplicates()))

    quality = check_quality_for_dataset(dataset)

    dup_issue = next(i for i in quality["issues"] if i["type"] == "duplicate_rows")
    assert dup_issue["count"] == 2


def test_profiling_and_quality_agree_when_both_run_on_the_same_dataset():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe_with_duplicates()))

    stats = basic_statistics_for_dataset(dataset)
    quality = check_quality_for_dataset(dataset)

    dup_issue = next(i for i in quality["issues"] if i["type"] == "duplicate_rows")
    assert stats["duplicate_rows"] == dup_issue["count"] == 2


def test_no_duplicates_reports_zero_for_both_engines():
    df = pd.DataFrame({"region": ["north", "south", "east"], "quantity": [1, 2, 3]})
    dataset = Dataset(storage=DuckDBStorage(df))

    stats = basic_statistics_for_dataset(dataset)
    quality = check_quality_for_dataset(dataset)

    assert stats["duplicate_rows"] == 0
    assert not any(i["type"] == "duplicate_rows" for i in quality["issues"])


# =========================================================
# SHARED COMPUTATION - the expensive scan runs exactly once per
# dataset, whichever engine (or order) touches it first.
# =========================================================


def test_scan_runs_once_when_profiling_then_quality_use_same_dataset():
    storage = _SpyDuckDBStorage(_make_dataframe_with_duplicates())
    dataset = Dataset(storage=storage)

    basic_statistics_for_dataset(dataset)
    check_quality_for_dataset(dataset)

    assert storage.distinct_computation_calls == 1


def test_scan_runs_once_when_quality_then_profiling_use_same_dataset():
    storage = _SpyDuckDBStorage(_make_dataframe_with_duplicates())
    dataset = Dataset(storage=storage)

    check_quality_for_dataset(dataset)
    basic_statistics_for_dataset(dataset)

    assert storage.distinct_computation_calls == 1


def test_repeated_calls_to_the_same_engine_do_not_rerun_the_scan():
    storage = _SpyDuckDBStorage(_make_dataframe_with_duplicates())
    dataset = Dataset(storage=storage)

    basic_statistics_for_dataset(dataset)
    basic_statistics_for_dataset(dataset)
    check_quality_for_dataset(dataset)

    assert storage.distinct_computation_calls == 1


def test_distinct_row_count_is_isolated_per_dataset():
    storage_a = _SpyDuckDBStorage(_make_dataframe_with_duplicates())
    storage_b = _SpyDuckDBStorage(
        pd.DataFrame({"region": ["north", "south"], "quantity": [1, 2]})
    )

    dataset_a = Dataset(storage=storage_a)
    dataset_b = Dataset(storage=storage_b)

    stats_a = basic_statistics_for_dataset(dataset_a)
    stats_b = basic_statistics_for_dataset(dataset_b)

    assert stats_a["duplicate_rows"] == 2
    assert stats_b["duplicate_rows"] == 0
    assert storage_a.distinct_computation_calls == 1
    assert storage_b.distinct_computation_calls == 1


def test_distinct_row_count_ignores_supplied_compute_and_uses_internal_computation():
    """
    Step 38: `compute` is accepted only so existing call sites
    (profiling/quality) don't have to change how they call
    distinct_row_count() - it is never actually invoked, on the first
    call or any later one, since the real computation is always the
    internal partitioned scan.
    """
    storage = DuckDBStorage(_make_dataframe_with_duplicates())

    calls = []

    def _builder():
        calls.append(True)
        return storage.execute_one(
            f'SELECT COUNT(*) FROM (SELECT DISTINCT * FROM "{storage.table_name}") '
            "AS distinct_rows"
        )[0]

    first = storage.distinct_row_count(_builder)
    second = storage.distinct_row_count(lambda: (_ for _ in ()).throw(
        AssertionError("builder should never run - Step 38 always uses the "
                       "internal partitioned computation")
    ))

    assert first == second == 4
    assert calls == []


def test_scan_runs_exactly_once_under_concurrent_first_access():
    """Two threads racing to compute the shared value for a fresh
    instance must serialize on the existing per-instance lock rather
    than both running the expensive scan."""
    storage = _SpyDuckDBStorage(_make_dataframe_with_duplicates())
    dataset = Dataset(storage=storage)

    start = threading.Barrier(2)
    results = {}

    def _run(name):
        start.wait(timeout=2)
        results[name] = basic_statistics_for_dataset(dataset)["duplicate_rows"]

    t1 = threading.Thread(target=_run, args=("t1",))
    t2 = threading.Thread(target=_run, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results["t1"] == results["t2"] == 2
    assert storage.distinct_computation_calls == 1


# =========================================================
# EXISTING CACHE BEHAVIOR - the higher-level dataset.cache /
# get_cached_on_dataset mechanism for full basic_statistics/quality
# results is untouched by this change.
# =========================================================


def test_get_cached_on_dataset_still_memoizes_basic_statistics():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe_with_duplicates()))

    build_calls = []

    def _builder(ds):
        build_calls.append(True)
        return basic_statistics_for_dataset(ds)

    first = get_cached_on_dataset(dataset, "basic_statistics", _builder)
    second = get_cached_on_dataset(dataset, "basic_statistics", _builder)

    assert first == second
    assert len(build_calls) == 1
    assert dataset.cache["basic_statistics"] == first


def test_get_cached_on_dataset_still_memoizes_quality():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe_with_duplicates()))

    build_calls = []

    def _builder(ds):
        build_calls.append(True)
        return check_quality_for_dataset(ds)

    first = get_cached_on_dataset(dataset, "quality", _builder)
    second = get_cached_on_dataset(dataset, "quality", _builder)

    assert first == second
    assert len(build_calls) == 1
    assert dataset.cache["quality"] == first


def test_close_still_raises_controlled_error_for_distinct_row_count():
    storage = DuckDBStorage(_make_dataframe_with_duplicates())
    storage.close()

    with pytest.raises(RuntimeError):
        storage.distinct_row_count(lambda: 0)
