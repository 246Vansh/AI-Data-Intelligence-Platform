"""Step 83: MetadataEngine.get_planning_metadata() /
planning_metadata_for_dataset().

Verifies:
  - Same keys and value types as exact metadata_for_dataset(), for
    both DuckDB- and Pandas-backed datasets.
  - DuckDB: never computes or populates the storage's memoized exact
    column_statistics(); missing_count/nullable/row_count/roles/
    sample_values match exact metadata; unique_values is a bounded
    estimate (never above the non-null count, NULLs excluded).
  - Pandas fallback stays exact (default delegates to get_metadata()).
  - Exact metadata is unchanged by a prior planning computation.
  - FastPlanner plans and plan validation outcomes are identical when
    planning against planning vs exact metadata.
  - A closed (deleted) storage raises StorageClosedError, which the
    analyze route already maps to 404.
"""

import pandas as pd
import pytest

from ai.fast_planner import FastPlanner
from data_engine.dataset import Dataset
from data_engine.metadata_engine import (
    metadata_for_dataset,
    planning_metadata_for_dataset,
)
from data_engine.plan_validator import validate_plan
from data_engine.storage import DuckDBStorage, PandasStorage, StorageClosedError


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_date": pd.to_datetime(
                ["2024-01-05", "2024-01-20", "2024-02-03", "2024-02-17", "2024-03-01", None]
            ),
            "region": ["north", "north", "south", None, "east", "east"],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, None, 60],
            "price": [1.5, 2.5, 1.5, 3.0, 2.0, 2.5],
        }
    )


def _shape(metadata: dict) -> dict:
    """Keys and value types only - the compatibility contract."""
    return {
        "top": {key: type(value) for key, value in metadata.items()},
        "columns": {
            column: {key: type(value) for key, value in info.items()}
            for column, info in metadata["columns"].items()
        },
    }


@pytest.mark.parametrize("storage_cls", [PandasStorage, DuckDBStorage])
def test_planning_metadata_keys_and_types_match_exact(storage_cls):
    planning = planning_metadata_for_dataset(Dataset(storage=storage_cls(_make_dataframe())))
    exact = metadata_for_dataset(Dataset(storage=storage_cls(_make_dataframe())))

    assert _shape(planning) == _shape(exact)


def test_duckdb_planning_metadata_skips_exact_column_statistics(monkeypatch):
    storage = DuckDBStorage(_make_dataframe())

    def _forbidden(self):
        raise AssertionError("exact column_statistics() ran for planning metadata")

    monkeypatch.setattr(DuckDBStorage, "_compute_column_statistics", _forbidden)

    planning_metadata_for_dataset(Dataset(storage=storage))

    assert storage._column_statistics is None


def test_duckdb_planning_metadata_matches_exact_except_unique_values():
    planning = planning_metadata_for_dataset(Dataset(storage=DuckDBStorage(_make_dataframe())))
    exact = metadata_for_dataset(Dataset(storage=DuckDBStorage(_make_dataframe())))

    for key in ("row_count", "column_count", "time_column", "time_columns"):
        assert planning[key] == exact[key]

    for column, exact_info in exact["columns"].items():
        planning_info = planning["columns"][column]

        for key in (
            "data_type",
            "role",
            "allowed_operations",
            "nullable",
            "missing_count",
            "sample_values",
        ):
            assert planning_info[key] == exact_info[key], (column, key)

        non_null = planning["row_count"] - planning_info["missing_count"]
        assert 0 <= planning_info["unique_values"] <= non_null


def test_duckdb_unique_values_excludes_nulls_and_is_bounded():
    df = pd.DataFrame({"code": [f"c{i % 50}" for i in range(500)] + [None] * 20})
    planning = planning_metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))
    info = planning["columns"]["code"]

    assert info["missing_count"] == 20
    assert info["nullable"] is True
    # HyperLogLog estimate: bounded, close to the exact 50 at this size.
    assert 45 <= info["unique_values"] <= 50


def test_pandas_planning_metadata_stays_exact():
    df = _make_dataframe()

    assert planning_metadata_for_dataset(
        Dataset(storage=PandasStorage(df))
    ) == metadata_for_dataset(Dataset(storage=PandasStorage(df)))


def test_exact_metadata_unchanged_after_planning_metadata():
    shared = Dataset(storage=DuckDBStorage(_make_dataframe()))
    planning_metadata_for_dataset(shared)

    assert metadata_for_dataset(shared) == metadata_for_dataset(
        Dataset(storage=DuckDBStorage(_make_dataframe()))
    )


@pytest.mark.parametrize(
    "question",
    [
        "total quantity by region",
        "average price by category",
        "total quantity in north region",
        "total quantity by month",
        "count of orders by category",
        "top 3 regions by total quantity",
    ],
)
def test_fast_planner_plans_and_validation_unchanged(question):
    df = _make_dataframe()
    planning = planning_metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))
    exact = metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))

    planner = FastPlanner()
    planning_plan = planner.create_plan(question=question, metadata=planning)
    exact_plan = planner.create_plan(question=question, metadata=exact)

    assert planning_plan == exact_plan

    if exact_plan is None:
        return

    outcomes = []

    for metadata in (planning, exact):
        try:
            validate_plan(df, exact_plan, metadata)
            outcomes.append(None)
        except ValueError as exc:
            outcomes.append(str(exc))

    assert outcomes[0] == outcomes[1]


def test_duckdb_planning_metadata_on_closed_storage_raises_storage_closed():
    storage = DuckDBStorage(_make_dataframe())
    storage.close()

    with pytest.raises(StorageClosedError):
        planning_metadata_for_dataset(Dataset(storage=storage))
