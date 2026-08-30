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

import pandas as pd
import pytest

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
    # separate namespaced tables, same isolation guarantee as the
    # DataFrame-backed constructor.
    assert storage_a.connection is not storage_b.connection
    assert storage_a.table_name != storage_b.table_name

    storage_a.connection.execute(f'DELETE FROM "{storage_a.table_name}"')
    assert storage_a.row_count() == 0
    assert storage_b.row_count() == len(df)


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
