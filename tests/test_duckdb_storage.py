"""Step 4: DuckDBStorage + DuckDB-native analysis plan execution.

Generic synthetic data only (no domain/Walmart references). Verifies:
  - DuckDBStorage construction and DatasetStorage contract fulfillment.
  - Dataset stays storage-agnostic when backed by DuckDBStorage.
  - Correct row/column counts and schema tracking.
  - DuckDB-native execution of an AnalysisPlan (group-by + aggregation
    + sort), matching the existing pandas execution path's results.
  - Dataset isolation: separate DuckDBStorage instances never share a
    connection or a table name, even for datasets with identical shape.
  - The existing pandas-based path (PandasStorage / plan_executor /
    query_engine) remains fully functional and unaffected.
"""

import inspect
import re
import threading

import pandas as pd
import pytest

import data_engine.storage.duckdb_storage as duckdb_storage_module
from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.dataset import Dataset
from data_engine.duckdb_query_engine import execute_plan_duckdb
from data_engine.plan_executor import execute_plan
from data_engine.storage import DatasetStorage, DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
        }
    )


def _make_dataframe_with_time() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", "east"],
            "quantity": [10, 20, 30, 40, 50, 60],
            "signed_up_at": pd.to_datetime(
                [
                    "2024-01-05",
                    "2024-02-10",
                    "2024-03-15",
                    "2024-04-20",
                    "2024-05-25",
                    "2024-06-30",
                ]
            ),
        }
    )


# =========================================================
# CONSTRUCTION & CONTRACT
# =========================================================


def test_duckdb_storage_implements_dataset_storage_contract():
    storage = DuckDBStorage(_make_dataframe())

    assert isinstance(storage, DatasetStorage)
    assert hasattr(storage, "to_dataframe")
    assert hasattr(storage, "row_count")
    assert hasattr(storage, "column_count")
    assert hasattr(storage, "column_names")


def test_duckdb_storage_rejects_non_dataframe_and_empty_dataframe():
    with pytest.raises(TypeError):
        DuckDBStorage("not a dataframe")

    with pytest.raises(ValueError):
        DuckDBStorage(pd.DataFrame())


def test_dataset_stays_storage_agnostic_with_duckdb_backing():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()), name="synthetic.csv")

    # Dataset itself doesn't know or care which concrete storage backs
    # it - the same properties work regardless of PandasStorage vs
    # DuckDBStorage.
    assert isinstance(dataset.storage, DuckDBStorage)
    assert dataset.row_count == 6
    assert dataset.column_count == 3
    assert dataset.column_names == ["region", "category", "quantity"]


def test_duckdb_storage_row_column_counts_and_schema():
    df = _make_dataframe()
    storage = DuckDBStorage(df)

    assert storage.row_count() == len(df)
    assert storage.column_count() == len(df.columns)
    assert storage.column_names() == list(df.columns)

    schema = storage.schema_info()
    assert set(schema.keys()) == set(df.columns)


def test_duckdb_storage_materializes_equivalent_dataframe():
    df = _make_dataframe()
    storage = DuckDBStorage(df)

    materialized = storage.to_dataframe()
    assert isinstance(materialized, pd.DataFrame)
    assert list(materialized.columns) == list(df.columns)
    assert len(materialized) == len(df)
    assert set(materialized["region"]) == set(df["region"])


# =========================================================
# STEP 10: CONSTRUCTION DIRECTLY FROM A PARQUET FILE
#
# The ingestion-to-registration path (Step 10) never has a DataFrame
# in hand - it only has a Parquet file on disk. DuckDBStorage.from_parquet
# is the alternate constructor that path uses instead of DuckDBStorage(df).
# =========================================================


def test_duckdb_storage_from_parquet_builds_storage_without_dataframe(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "sample.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))

    assert isinstance(storage, DatasetStorage)
    assert isinstance(storage, DuckDBStorage)
    assert storage.row_count() == len(df)
    assert storage.column_count() == len(df.columns)
    assert storage.column_names() == list(df.columns)


def test_duckdb_storage_from_parquet_materializes_equivalent_dataframe(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "sample2.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))
    materialized = storage.to_dataframe()

    assert isinstance(materialized, pd.DataFrame)
    assert list(materialized.columns) == list(df.columns)
    assert len(materialized) == len(df)
    assert set(materialized["region"]) == set(df["region"])


def test_duckdb_storage_from_parquet_instances_stay_isolated(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "sample3.parquet"
    df.to_parquet(parquet_path)

    storage_a = DuckDBStorage.from_parquet(str(parquet_path))
    storage_b = DuckDBStorage.from_parquet(str(parquet_path))

    # Same source file, two instances - still separate connections and
    # separate namespaced views, same isolation guarantee as the
    # DataFrame-backed constructor. Each instance's view is registered
    # only on its own private connection, so instance A can never see
    # or address instance B's view (or vice versa) - unlike the
    # physical-table constructor, a view cannot be mutated with DELETE,
    # so isolation here is proven by name/connection separation and
    # cross-connection unresolvability instead.
    assert storage_a.connection is not storage_b.connection
    assert storage_a.table_name != storage_b.table_name
    assert storage_a.row_count() == len(df)
    assert storage_b.row_count() == len(df)

    with pytest.raises(Exception):
        storage_a.connection.execute(f'SELECT * FROM "{storage_b.table_name}"')

    with pytest.raises(Exception):
        storage_b.connection.execute(f'SELECT * FROM "{storage_a.table_name}"')


# =========================================================
# STEP 2: TRUE PARQUET-BACKED (VIEW, NOT PHYSICAL TABLE) STORAGE
#
# from_parquet() now registers a DuckDB VIEW
# (CREATE VIEW ... AS SELECT * FROM read_parquet(?)) instead of a
# physical CREATE TABLE ... AS SELECT copy. Registration therefore
# stores only a query plan - zero rows are scanned or copied into
# DuckDB's in-memory buffer at construction time. Every downstream
# consumer (to_dataframe/row_count/column_count/column_names/
# schema_info/execute_plan_duckdb/profiling) keeps working unmodified,
# since DuckDB queries a view exactly like a table.
# =========================================================


def test_from_parquet_registers_a_view_not_a_base_table(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "view_check.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))

    table_type = storage.connection.execute(
        "SELECT table_type FROM information_schema.tables WHERE table_name = ?",
        [storage.table_name],
    ).fetchone()[0]
    assert table_type == "VIEW"

    view_names = {
        row[0]
        for row in storage.connection.execute(
            "SELECT view_name FROM duckdb_views()"
        ).fetchall()
    }
    assert storage.table_name in view_names

    base_table_names = {
        row[0]
        for row in storage.connection.execute(
            "SELECT table_name FROM duckdb_tables()"
        ).fetchall()
    }
    assert storage.table_name not in base_table_names


def test_from_parquet_source_never_uses_table_ctas_pattern():
    source = inspect.getsource(duckdb_storage_module.DuckDBStorage.from_parquet)

    ctas_from_parquet_pattern = re.compile(
        r"CREATE\s+TABLE.*?AS\s+SELECT\s*\*\s*FROM\s+read_parquet",
        re.IGNORECASE | re.DOTALL,
    )

    assert ctas_from_parquet_pattern.search(source) is None
    assert re.search(r"CREATE\s+VIEW", source) is not None
    assert "read_parquet(" in source


def test_from_parquet_retains_source_parquet_path(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "path_retention.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))

    assert storage._parquet_path == str(parquet_path)


def test_from_parquet_schema_info_reflects_view_columns(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "schema_check.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))
    schema = storage.schema_info()

    assert set(schema.keys()) == set(df.columns)
    assert all(isinstance(dtype, str) for dtype in schema.values())


def test_from_parquet_never_reads_pandas_or_materializes_dataframe(tmp_path, monkeypatch):
    df = _make_dataframe()
    parquet_path = tmp_path / "zero_copy.parquet"
    df.to_parquet(parquet_path)

    original_read_parquet = pd.read_parquet
    read_parquet_calls = []

    def _spy_read_parquet(*args, **kwargs):
        read_parquet_calls.append((args, kwargs))
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", _spy_read_parquet)

    original_to_dataframe = DuckDBStorage.to_dataframe
    to_dataframe_calls = []

    def _spy_to_dataframe(self):
        to_dataframe_calls.append(True)
        return original_to_dataframe(self)

    monkeypatch.setattr(DuckDBStorage, "to_dataframe", _spy_to_dataframe)

    storage = DuckDBStorage.from_parquet(str(parquet_path))

    # Registration itself never routes through Pandas' own Parquet
    # reader, and never materializes the dataset via to_dataframe() -
    # only the view-creation DDL and a schema-only column lookup run.
    assert read_parquet_calls == []
    assert to_dataframe_calls == []
    assert isinstance(storage, DuckDBStorage)


def test_from_parquet_execution_matches_dataframe_backed_storage_across_full_plan_surface(
    tmp_path,
):
    df = _make_dataframe_with_time()
    parquet_path = tmp_path / "execution_parity.parquet"
    df.to_parquet(parquet_path)

    parquet_storage = DuckDBStorage.from_parquet(str(parquet_path))
    dataframe_storage = DuckDBStorage(df)

    plan = AnalysisPlan(
        filters=[FilterCondition(column="quantity", operator=">", value=15)],
        group_by=["signed_up_at"],
        metric="quantity",
        aggregation="sum",
        time_column="signed_up_at",
        time_granularity="month",
        sort="desc",
        sort_by="time",
        limit=4,
    )

    parquet_result = execute_plan_duckdb(parquet_storage, plan)
    dataframe_result = execute_plan_duckdb(dataframe_storage, plan)

    pd.testing.assert_frame_equal(
        parquet_result.reset_index(drop=True),
        dataframe_result.reset_index(drop=True),
        check_dtype=False,
    )


def test_from_parquet_global_aggregation_matches_expected_sum(tmp_path):
    df = _make_dataframe()
    parquet_path = tmp_path / "global_agg.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))
    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    result = execute_plan_duckdb(storage, plan)

    assert list(result.columns) == ["sum_quantity"]
    assert result["sum_quantity"].iloc[0] == df["quantity"].sum()


def test_from_parquet_instances_from_different_files_stay_isolated(tmp_path):
    df_a = _make_dataframe()
    df_b = pd.DataFrame({"region": ["west", "west"], "quantity": [5, 15]})

    parquet_path_a = tmp_path / "dataset_a.parquet"
    parquet_path_b = tmp_path / "dataset_b.parquet"
    df_a.to_parquet(parquet_path_a)
    df_b.to_parquet(parquet_path_b)

    storage_a = DuckDBStorage.from_parquet(str(parquet_path_a))
    storage_b = DuckDBStorage.from_parquet(str(parquet_path_b))

    # Separate connections, separate namespaced views, separate
    # retained source paths.
    assert storage_a.connection is not storage_b.connection
    assert storage_a.table_name != storage_b.table_name
    assert storage_a._parquet_path == str(parquet_path_a)
    assert storage_b._parquet_path == str(parquet_path_b)

    # Each view resolves only against its own source file.
    assert storage_a.row_count() == len(df_a)
    assert storage_b.row_count() == len(df_b)
    assert set(storage_a.to_dataframe()["region"]) == set(df_a["region"])
    assert set(storage_b.to_dataframe()["region"]) == set(df_b["region"])

    # Cross-pollution is impossible: instance A's connection has never
    # heard of instance B's view name, and vice versa.
    with pytest.raises(Exception):
        storage_a.connection.execute(f'SELECT * FROM "{storage_b.table_name}"')

    with pytest.raises(Exception):
        storage_b.connection.execute(f'SELECT * FROM "{storage_a.table_name}"')

    # Independent plan execution against each never leaks the other's
    # rows into the result.
    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")
    result_a = execute_plan_duckdb(storage_a, plan)
    result_b = execute_plan_duckdb(storage_b, plan)

    assert set(result_a["region"]) == {"north", "south", "east"}
    assert set(result_b["region"]) == {"west"}
    assert result_b["sum_quantity"].iloc[0] == 20


def test_pandas_storage_contract_completely_unaffected_by_step2(tmp_path):
    """
    PandasStorage is out of scope for Step 2 (Parquet/DuckDB-only
    change). This pins its full contract to prove it - construction,
    counts, names, and to_dataframe() - stayed byte-for-byte identical
    in behavior.
    """
    df = _make_dataframe()
    storage = PandasStorage(df)

    assert isinstance(storage, DatasetStorage)
    assert storage.to_dataframe() is df
    assert storage.row_count() == len(df)
    assert storage.column_count() == len(df.columns)
    assert storage.column_names() == df.columns.tolist()

    with pytest.raises(TypeError):
        PandasStorage("not a dataframe")

    with pytest.raises(ValueError):
        PandasStorage(pd.DataFrame())


# =========================================================
# ANALYSIS PLAN EXECUTION (DUCKDB ENGINE-NATIVE)
# =========================================================


def test_duckdb_execution_group_by_and_sort_matches_pandas_path():
    df = _make_dataframe()

    plan = AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="desc",
        sort_by="metric",
    )

    pandas_result = execute_plan(df, plan)
    duckdb_result = execute_plan_duckdb(DuckDBStorage(df), plan)

    assert list(duckdb_result.columns) == list(pandas_result.columns)

    pandas_sorted = pandas_result.sort_values("region").reset_index(drop=True)
    duckdb_sorted = duckdb_result.sort_values("region").reset_index(drop=True)

    pd.testing.assert_frame_equal(
        duckdb_sorted,
        pandas_sorted,
        check_dtype=False,
    )

    # Sort order itself (descending by summed metric) must also match.
    # north=10+20=30, south=30+40=70, east=50+60=110
    assert list(duckdb_result["region"]) == list(pandas_result["region"])
    assert list(duckdb_result["sum_quantity"]) == [110, 70, 30]


def test_duckdb_execution_applies_filter_before_aggregation():
    df = _make_dataframe()

    plan = AnalysisPlan(
        filters=[FilterCondition(column="category", operator="=", value="a")],
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        sort="asc",
        sort_by="metric",
    )

    result = execute_plan_duckdb(DuckDBStorage(df), plan)

    assert set(result["region"]) == {"north", "south", "east"}
    assert list(result["sum_quantity"]) == sorted([10, 30, 50])


def test_duckdb_execution_global_aggregation_without_group_by():
    df = _make_dataframe()

    plan = AnalysisPlan(metric="quantity", aggregation="sum")

    result = execute_plan_duckdb(DuckDBStorage(df), plan)

    assert list(result.columns) == ["sum_quantity"]
    assert result["sum_quantity"].iloc[0] == df["quantity"].sum()


def test_duckdb_execution_rejects_unknown_metric_and_group_column():
    df = _make_dataframe()

    with pytest.raises(ValueError):
        execute_plan_duckdb(
            DuckDBStorage(df),
            AnalysisPlan(metric="does_not_exist"),
        )

    with pytest.raises(ValueError):
        execute_plan_duckdb(
            DuckDBStorage(df),
            AnalysisPlan(group_by=["does_not_exist"], metric="quantity"),
        )


# =========================================================
# DATASET ISOLATION
# =========================================================


def test_duckdb_storage_instances_are_isolated():
    df_a = pd.DataFrame({"col": [1, 2, 3]})
    df_b = pd.DataFrame({"col": [1, 2, 3]})  # identical shape/columns

    storage_a = DuckDBStorage(df_a)
    storage_b = DuckDBStorage(df_b)

    # Distinct connections and distinct, uniquely namespaced tables -
    # no global table-name collision even for identically shaped data.
    assert storage_a.connection is not storage_b.connection
    assert storage_a.table_name != storage_b.table_name

    # Writing/reading through one instance never becomes visible on
    # the other.
    storage_a.connection.execute(f'DELETE FROM "{storage_a.table_name}"')
    assert storage_a.row_count() == 0
    assert storage_b.row_count() == 3

    # Instance A cannot see instance B's table at all.
    with pytest.raises(Exception):
        storage_a.connection.execute(f'SELECT * FROM "{storage_b.table_name}"')


def test_two_datasets_execute_independently_without_cross_contamination():
    df_a = _make_dataframe()
    df_b = pd.DataFrame({"region": ["west", "west"], "quantity": [5, 15]})

    dataset_a = Dataset(storage=DuckDBStorage(df_a))
    dataset_b = Dataset(storage=DuckDBStorage(df_b))

    plan_a = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")
    plan_b = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")

    result_a = execute_plan_duckdb(dataset_a.storage, plan_a)
    result_b = execute_plan_duckdb(dataset_b.storage, plan_b)

    assert set(result_a["region"]) == {"north", "south", "east"}
    assert set(result_b["region"]) == {"west"}
    assert result_b["sum_quantity"].iloc[0] == 20


# =========================================================
# PANDAS PATH REMAINS FULLY FUNCTIONAL
# =========================================================


def test_pandas_storage_path_still_works_unaffected():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))

    plan = AnalysisPlan(group_by=["region"], metric="quantity", aggregation="sum")
    result = execute_plan(dataset.storage.to_dataframe(), plan)

    assert isinstance(result, pd.DataFrame)
    assert set(result["region"]) == {"north", "south", "east"}


# =========================================================
# STEP 17B: execute_df() / execute_one() LOCK-LIFETIME SAFETY
#
# The connection property only ever guarded the *handoff* of the raw
# connection - the lock was released before a caller's .execute(...)
# ran, so a concurrent close() could invalidate the connection
# mid-query. execute_df()/execute_one() hold storage._lock across the
# entire query lifetime instead. These tests exercise the lock
# mechanism directly (via storage._lock) rather than trying to
# intercept DuckDB's C-extension connection object, and use
# threading.Event + bounded joins instead of sleeps for determinism.
# =========================================================


def test_execute_df_blocks_while_storage_lock_is_externally_held():
    storage = DuckDBStorage(_make_dataframe())

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def _hold_lock():
        with storage._lock:
            lock_acquired.set()
            release_lock.wait(timeout=2)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    assert lock_acquired.wait(timeout=2)

    result_holder = {}

    def _run_execute_df():
        result_holder["df"] = storage.execute_df(
            f'SELECT COUNT(*) AS n FROM "{storage.table_name}"'
        )

    waiter = threading.Thread(target=_run_execute_df)
    waiter.start()

    # The lock is still held externally, so execute_df() must still be
    # blocked trying to acquire it - it must not have run its query.
    waiter.join(timeout=0.3)
    assert waiter.is_alive()
    assert "df" not in result_holder

    release_lock.set()
    waiter.join(timeout=2)
    assert not waiter.is_alive()
    assert result_holder["df"]["n"].iloc[0] == 6

    holder.join(timeout=2)


def test_close_waits_for_in_flight_protected_operation_then_closes():
    storage = DuckDBStorage(_make_dataframe())

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def _hold_lock():
        with storage._lock:
            lock_acquired.set()
            release_lock.wait(timeout=2)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    assert lock_acquired.wait(timeout=2)

    closer = threading.Thread(target=storage.close)
    closer.start()

    # close() must block behind the same lock a live query would be
    # holding for its entire execute-and-materialize lifetime.
    closer.join(timeout=0.3)
    assert closer.is_alive()

    release_lock.set()
    closer.join(timeout=2)
    assert not closer.is_alive()
    assert storage._closed is True

    holder.join(timeout=2)


def test_execute_df_and_execute_one_raise_controlled_error_after_close():
    storage = DuckDBStorage(_make_dataframe())
    table = storage.table_name
    storage.close()

    with pytest.raises(RuntimeError):
        storage.execute_df(f'SELECT * FROM "{table}"')

    with pytest.raises(RuntimeError):
        storage.execute_one(f'SELECT COUNT(*) FROM "{table}"')


def test_execute_df_different_instances_never_block_each_other():
    storage_a = DuckDBStorage(_make_dataframe())
    storage_b = DuckDBStorage(pd.DataFrame({"col": [1, 2, 3]}))

    a_lock_acquired = threading.Event()
    release_a_lock = threading.Event()

    def _hold_a_lock():
        with storage_a._lock:
            a_lock_acquired.set()
            release_a_lock.wait(timeout=2)

    holder = threading.Thread(target=_hold_a_lock)
    holder.start()
    assert a_lock_acquired.wait(timeout=2)

    try:
        # storage_b has its own independent lock - execute_df() against
        # it must succeed immediately even while storage_a's lock is
        # held by another thread.
        result_b = storage_b.execute_df(
            f'SELECT COUNT(*) AS n FROM "{storage_b.table_name}"'
        )
        assert result_b["n"].iloc[0] == 3
    finally:
        release_a_lock.set()
        holder.join(timeout=2)
