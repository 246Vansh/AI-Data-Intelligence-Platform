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

import datetime
import re
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


# =========================================================
# STEP 44: FUSED BATCHES OF 4 COLUMNS
# =========================================================


def _make_wide_mixed_type_dataframe() -> pd.DataFrame:
    """7 columns (mixed types, each with at least one null) so a
    batch size of 4 must split this into two fused batches: [name,
    age, score, active] and [signup_date, event_time, all_null]."""
    return pd.DataFrame(
        {
            "name": ["alice", "bob", "carol", "dave", None, "alice"],
            "age": [25, 30, 35, 40, None, 25],
            "score": [1.5, 2.5, 3.5, None, 5.5, 5.5],
            "active": [True, False, True, False, None, True],
            "signup_date": [
                datetime.date(2024, 1, 1),
                datetime.date(2024, 1, 2),
                datetime.date(2024, 1, 3),
                None,
                datetime.date(2024, 1, 1),
                datetime.date(2024, 1, 3),
            ],
            "event_time": [
                datetime.datetime(2024, 1, 1, 10, 0),
                datetime.datetime(2024, 1, 1, 11, 0),
                None,
                datetime.datetime(2024, 1, 1, 10, 0),
                datetime.datetime(2024, 1, 2, 9, 0),
                datetime.datetime(2024, 1, 2, 9, 0),
            ],
            "all_null": [None] * 6,
        }
    )


def _count_select_columns(query: str) -> int:
    return len(re.findall(r"AS non_null_\d+", query))


def test_batching_splits_wide_table_into_fused_queries_of_four_columns():
    storage = _SpyDuckDBStorage(_make_wide_mixed_type_dataframe())

    storage.column_statistics()

    # 7 columns at batch size 4 -> two fused queries, not one query per
    # column and not one query spanning all seven columns.
    assert len(storage.column_stats_scan_calls) == 2
    per_batch_column_counts = [
        _count_select_columns(query) for query in storage.column_stats_scan_calls
    ]
    assert per_batch_column_counts == [4, 3]
    assert all(count <= 4 for count in per_batch_column_counts)


def test_batching_uses_exactly_one_query_at_the_four_column_boundary():
    df = _make_wide_mixed_type_dataframe()[["name", "age", "score", "active"]]
    storage = _SpyDuckDBStorage(df)

    storage.column_statistics()

    assert len(storage.column_stats_scan_calls) == 1
    assert _count_select_columns(storage.column_stats_scan_calls[0]) == 4


def test_batching_splits_five_columns_into_four_plus_one():
    df = _make_wide_mixed_type_dataframe()[
        ["name", "age", "score", "active", "signup_date"]
    ]
    storage = _SpyDuckDBStorage(df)

    storage.column_statistics()

    per_batch_column_counts = [
        _count_select_columns(query) for query in storage.column_stats_scan_calls
    ]
    assert per_batch_column_counts == [4, 1]


def test_exact_statistics_across_mixed_types_and_nulls_with_batching():
    storage = DuckDBStorage(_make_wide_mixed_type_dataframe())

    stats = storage.column_statistics()

    assert stats["name"].non_null_count == 5
    assert stats["name"].distinct_count == 4
    assert stats["name"].min_value == "alice"
    assert stats["name"].max_value == "dave"

    assert stats["age"].non_null_count == 5
    assert stats["age"].distinct_count == 4
    assert stats["age"].min_value == 25
    assert stats["age"].max_value == 40

    assert stats["score"].non_null_count == 5
    assert stats["score"].distinct_count == 4
    assert stats["score"].min_value == 1.5
    assert stats["score"].max_value == 5.5

    assert stats["active"].non_null_count == 5
    assert stats["active"].distinct_count == 2
    assert stats["active"].min_value is False
    assert stats["active"].max_value is True

    assert stats["signup_date"].non_null_count == 5
    assert stats["signup_date"].distinct_count == 3
    assert stats["signup_date"].min_value == datetime.date(2024, 1, 1)
    assert stats["signup_date"].max_value == datetime.date(2024, 1, 3)

    assert stats["event_time"].non_null_count == 5
    assert stats["event_time"].distinct_count == 3
    assert stats["event_time"].min_value == datetime.datetime(2024, 1, 1, 10, 0)
    assert stats["event_time"].max_value == datetime.datetime(2024, 1, 2, 9, 0)

    assert stats["all_null"].non_null_count == 0
    assert stats["all_null"].distinct_count == 0
    assert stats["all_null"].min_value is None
    assert stats["all_null"].max_value is None


def test_batched_statistics_match_single_query_baseline_for_same_data():
    """Cross-checks the batched result against a hand-run single
    all-column aggregate query (the pre-Step-44 approach), proving
    batching didn't change any value, only how many queries compute
    them."""
    df = _make_wide_mixed_type_dataframe()
    storage = DuckDBStorage(df)
    columns = list(df.columns)

    batched = storage.column_statistics()

    select_parts = []
    for index, column in enumerate(columns):
        quoted = f'"{column}"'
        select_parts.append(f"COUNT({quoted}) AS non_null_{index}")
        select_parts.append(f"COUNT(DISTINCT {quoted}) AS distinct_{index}")
        select_parts.append(f"MIN({quoted}) AS min_{index}")
        select_parts.append(f"MAX({quoted}) AS max_{index}")
    row = storage.execute_one(
        f"SELECT {', '.join(select_parts)} FROM {storage.table_name}"
    )

    for index, column in enumerate(columns):
        non_null, distinct, min_value, max_value = row[index * 4 : index * 4 + 4]
        assert batched[column].non_null_count == int(non_null or 0)
        assert batched[column].distinct_count == int(distinct or 0)
        assert batched[column].min_value == min_value
        assert batched[column].max_value == max_value


def test_cache_still_reused_across_calls_with_wide_batched_table():
    storage = _SpyDuckDBStorage(_make_wide_mixed_type_dataframe())

    first = storage.column_statistics()
    second = storage.column_statistics()

    assert first is second
    # Still exactly two batch queries total, not two more on the second call.
    assert len(storage.column_stats_scan_calls) == 2
