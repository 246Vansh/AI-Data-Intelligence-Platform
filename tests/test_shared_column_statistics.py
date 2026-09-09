"""Step 35: shared per-column statistics (non-null count, distinct
count, min, max) across DuckDB metadata/profiling/quality consumers.

Step 34 found that DuckDBMetadataEngine.get_metadata(),
DuckDBProfilingEngine.basic_statistics(), and
DuckDBQualityEngine.check_quality() each independently ran their own
`COUNT(col)` / `COUNT(DISTINCT col)` aggregate scan over every column -
three unshared full-table-per-column scans computing overlapping
statistics (see step34_post_step33_scalability_audit.txt).

DuckDBStorage.column_statistics() now memoizes the shared per-column
result once per instance (i.e. once per dataset), guarded by the
instance's existing per-connection lock, exactly like Step 33's
distinct_row_count() - and metadata/profiling/quality all route through
it instead of each running their own copy of the scan.

Verifies:
  - the shared aggregate scan runs exactly once per dataset no matter
    which engine (or order) touches it first, including under
    concurrent first access.
  - two different DuckDBStorage instances never share cached state.
  - non-null and distinct counts stay exactly correct.
  - metadata/profiling/quality response shapes are unchanged.
  - Step 33's duplicate-row sharing keeps working alongside this.
"""

import threading

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.metadata_engine import metadata_for_dataset
from data_engine.profiling import basic_statistics_for_dataset
from data_engine.quality import check_quality_for_dataset
from data_engine.storage import DuckDBStorage
from data_engine.storage.duckdb_storage import ColumnStatistics


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", None],
            "quantity": [10, 20, 30, 40, 50, 60],
            "price": [1.5, 2.5, None, 4.5, 5.5, 6.5],
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that counts how many times it actually runs the
    shared per-column statistics scan (via execute_one), regardless of
    which engine triggered it."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.column_stats_scan_calls: list[str] = []

    def execute_one(self, query: str, params=None):
        if "COUNT(DISTINCT" in query:
            self.column_stats_scan_calls.append(query)
        return super().execute_one(query, params)


# =========================================================
# FIRST CALL COMPUTES AND CACHES
# =========================================================


def test_first_call_computes_statistics():
    storage = _SpyDuckDBStorage(_make_dataframe())

    stats = storage.column_statistics()

    assert len(storage.column_stats_scan_calls) == 1
    assert set(stats.keys()) == {"region", "quantity", "price"}


def test_second_call_on_same_instance_reuses_cache():
    storage = _SpyDuckDBStorage(_make_dataframe())

    first = storage.column_statistics()
    second = storage.column_statistics()

    assert first is second
    assert len(storage.column_stats_scan_calls) == 1


# =========================================================
# CROSS-CONSUMER SHARING
# =========================================================


def test_second_consumer_reuses_cached_statistics_profiling_then_quality():
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage)

    basic_statistics_for_dataset(dataset)
    check_quality_for_dataset(dataset)

    assert len(storage.column_stats_scan_calls) == 1


def test_second_consumer_reuses_cached_statistics_metadata_then_profiling():
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage)

    metadata_for_dataset(dataset)
    basic_statistics_for_dataset(dataset)

    assert len(storage.column_stats_scan_calls) == 1


def test_all_three_consumers_share_a_single_scan():
    storage = _SpyDuckDBStorage(_make_dataframe())
    dataset = Dataset(storage=storage)

    metadata_for_dataset(dataset)
    basic_statistics_for_dataset(dataset)
    check_quality_for_dataset(dataset)

    assert len(storage.column_stats_scan_calls) == 1


# =========================================================
# DATASET ISOLATION
# =========================================================


def test_two_instances_do_not_share_cache_state():
    storage_a = _SpyDuckDBStorage(_make_dataframe())
    storage_b = _SpyDuckDBStorage(
        pd.DataFrame({"region": ["north", "south"], "quantity": [1, 2]})
    )

    storage_a.column_statistics()
    storage_b.column_statistics()

    assert len(storage_a.column_stats_scan_calls) == 1
    assert len(storage_b.column_stats_scan_calls) == 1
    assert storage_a.column_statistics()["region"].distinct_count == 3
    assert storage_b.column_statistics()["region"].distinct_count == 2


# =========================================================
# CONCURRENT FIRST ACCESS
# =========================================================


def test_concurrent_first_access_computes_only_once():
    storage = _SpyDuckDBStorage(_make_dataframe())

    start = threading.Barrier(2)
    results = {}

    def _run(name):
        start.wait(timeout=2)
        results[name] = storage.column_statistics()

    t1 = threading.Thread(target=_run, args=("t1",))
    t2 = threading.Thread(target=_run, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results["t1"] is results["t2"]
    assert len(storage.column_stats_scan_calls) == 1


# =========================================================
# EXACT VALUE PRESERVATION
# =========================================================


def test_non_null_counts_are_exact():
    storage = DuckDBStorage(_make_dataframe())

    stats = storage.column_statistics()

    assert stats["region"].non_null_count == 5  # one None
    assert stats["quantity"].non_null_count == 6
    assert stats["price"].non_null_count == 5  # one None


def test_distinct_counts_are_exact():
    storage = DuckDBStorage(_make_dataframe())

    stats = storage.column_statistics()

    assert stats["region"].distinct_count == 3  # north, south, east
    assert stats["quantity"].distinct_count == 6
    assert stats["price"].distinct_count == 5


def test_column_statistics_returns_immutable_entries():
    storage = DuckDBStorage(_make_dataframe())

    stats = storage.column_statistics()

    assert isinstance(stats["quantity"], ColumnStatistics)
    with pytest.raises(Exception):
        stats["quantity"].non_null_count = 999


# =========================================================
# EXISTING RESPONSE SHAPES UNCHANGED
# =========================================================


def test_metadata_response_unchanged_after_sharing():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))

    metadata = metadata_for_dataset(dataset)

    assert metadata["row_count"] == 6
    assert metadata["columns"]["region"]["missing_count"] == 1
    assert metadata["columns"]["region"]["unique_values"] == 3
    assert metadata["columns"]["quantity"]["unique_values"] == 6


def test_profiling_response_unchanged_after_sharing():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))

    stats = basic_statistics_for_dataset(dataset)

    assert stats["row_count"] == 6
    assert stats["columns"]["region"]["missing_count"] == 1
    assert stats["columns"]["region"]["distinct_count"] == 3
    assert stats["columns"]["quantity"]["min"] == 10
    assert stats["columns"]["quantity"]["max"] == 60


def test_quality_response_unchanged_after_sharing():
    df = _make_dataframe()
    dataset = Dataset(storage=DuckDBStorage(df))

    quality = check_quality_for_dataset(dataset)

    missing_issue = next(
        i
        for i in quality["issues"]
        if i["type"] == "missing_values" and i["column"] == "region"
    )
    assert missing_issue["count"] == 1


# =========================================================
# STEP 33 DUPLICATE-ROW SHARING STILL WORKS
# =========================================================


def test_step33_duplicate_row_sharing_still_works_alongside_column_stats():
    df = pd.DataFrame(
        {
            "region": ["north", "south", "north", "east"],
            "quantity": [10, 20, 10, 40],
        }
    )
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    stats = basic_statistics_for_dataset(dataset)
    quality = check_quality_for_dataset(dataset)

    dup_issue = next(i for i in quality["issues"] if i["type"] == "duplicate_rows")
    assert stats["duplicate_rows"] == dup_issue["count"] == 1
    # Column-stat scan still shared exactly once across both engines.
    assert len(storage.column_stats_scan_calls) == 1


def test_close_still_raises_controlled_error_for_column_statistics():
    storage = DuckDBStorage(_make_dataframe())
    storage.close()

    with pytest.raises(RuntimeError):
        storage.column_statistics()
