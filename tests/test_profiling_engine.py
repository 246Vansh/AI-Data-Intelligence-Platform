"""Step 9: ProfilingEngine - basic dataset inspection statistics
(row/column counts, missing-value tallies, distinct counts, min/max
bounds, basic data types) natively behind the storage-aware engine
boundary, mirroring data_engine.execution's ExecutionEngine pattern.

Verifies:
  - ProfilingEngine is a genuine abstract contract.
  - PandasProfilingEngine and DuckDBProfilingEngine both satisfy it.
  - Full metric parity between the two engines on an identical
    synthetic dataset covering strings, integers, floats, booleans,
    datetimes, and missing values (NaN vs. NULL).
  - DuckDBProfilingEngine never calls storage.to_dataframe() - proven
    with a spy storage subclass.
  - select_profiling_engine_for()/basic_statistics_for_dataset() route
    purely on the Dataset's own storage type, never a global dataset
    manager lookup.
  - Existing full test suite remains green (no regressions from adding
    this additive, unwired module).
"""

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.profiling import (
    DuckDBProfilingEngine,
    PandasProfilingEngine,
    ProfilingEngine,
    basic_statistics_for_dataset,
    select_profiling_engine_for,
)
from data_engine.storage import DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east", None],
            "category": ["a", "b", "a", "b", "a", "b"],
            "quantity": [10, 20, 30, 40, 50, 60],
            "price": [1.5, 2.5, None, 4.5, 5.5, 6.5],
            "is_active": [True, False, True, True, False, True],
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


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# CONTRACT / ABSTRACTNESS
# =========================================================


def test_profiling_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ProfilingEngine()


def test_pandas_profiling_engine_is_a_profiling_engine():
    engine = PandasProfilingEngine()
    assert isinstance(engine, ProfilingEngine)


def test_duckdb_profiling_engine_is_a_profiling_engine():
    engine = DuckDBProfilingEngine()
    assert isinstance(engine, ProfilingEngine)


# =========================================================
# SELECTOR - routes by storage type, no global dataset lookups
# =========================================================


def test_selector_picks_duckdb_engine_for_duckdb_storage():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()))
    engine = select_profiling_engine_for(dataset)
    assert isinstance(engine, DuckDBProfilingEngine)


def test_selector_picks_pandas_engine_for_pandas_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    engine = select_profiling_engine_for(dataset)
    assert isinstance(engine, PandasProfilingEngine)


# =========================================================
# FULL METRIC PARITY - identical synthetic dataset, both engines
# =========================================================


def test_basic_statistics_parity_row_and_column_counts():
    df = _make_dataframe()

    pandas_stats = basic_statistics_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_stats = basic_statistics_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_stats["row_count"] == duckdb_stats["row_count"] == 6
    assert pandas_stats["column_count"] == duckdb_stats["column_count"] == 6


@pytest.mark.parametrize(
    "column",
    ["region", "category", "quantity", "price", "is_active", "signed_up_at"],
)
def test_basic_statistics_parity_per_column(column):
    df = _make_dataframe()

    pandas_stats = basic_statistics_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_stats = basic_statistics_for_dataset(Dataset(storage=DuckDBStorage(df)))

    pandas_column = pandas_stats["columns"][column]
    duckdb_column = duckdb_stats["columns"][column]

    assert pandas_column == duckdb_column


def test_basic_statistics_handles_nan_vs_null_missing_values_identically():
    df = _make_dataframe()

    pandas_stats = basic_statistics_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_stats = basic_statistics_for_dataset(Dataset(storage=DuckDBStorage(df)))

    # "region" has one pandas NaN/None; "price" has one pandas NaN.
    assert pandas_stats["columns"]["region"]["missing_count"] == 1
    assert duckdb_stats["columns"]["region"]["missing_count"] == 1
    assert pandas_stats["columns"]["price"]["missing_count"] == 1
    assert duckdb_stats["columns"]["price"]["missing_count"] == 1


def test_basic_statistics_datetime_min_max_match_as_iso_strings():
    df = _make_dataframe()

    pandas_stats = basic_statistics_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_stats = basic_statistics_for_dataset(Dataset(storage=DuckDBStorage(df)))

    column = "signed_up_at"
    assert pandas_stats["columns"][column]["data_type"] == "datetime"
    assert duckdb_stats["columns"][column]["data_type"] == "datetime"
    assert (
        pandas_stats["columns"][column]["min"]
        == duckdb_stats["columns"][column]["min"]
        == "2024-01-05T00:00:00"
    )
    assert (
        pandas_stats["columns"][column]["max"]
        == duckdb_stats["columns"][column]["max"]
        == "2024-06-30T00:00:00"
    )


def test_basic_statistics_boolean_min_max_match():
    df = _make_dataframe()

    pandas_stats = basic_statistics_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_stats = basic_statistics_for_dataset(Dataset(storage=DuckDBStorage(df)))

    column = "is_active"
    assert pandas_stats["columns"][column]["data_type"] == "boolean"
    assert duckdb_stats["columns"][column]["data_type"] == "boolean"
    assert pandas_stats["columns"][column]["min"] is False
    assert duckdb_stats["columns"][column]["min"] is False
    assert pandas_stats["columns"][column]["max"] is True
    assert duckdb_stats["columns"][column]["max"] is True


# =========================================================
# BOUNDARY DISCIPLINE - zero to_dataframe() for DuckDB profiling
# =========================================================


def test_duckdb_profiling_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    basic_statistics_for_dataset(dataset)

    assert storage.to_dataframe_calls == []


def test_duckdb_profiling_engine_rejects_non_duckdb_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))

    with pytest.raises(TypeError):
        DuckDBProfilingEngine().basic_statistics(dataset)


# =========================================================
# EXISTING PANDAS PROFILE/QUALITY/METADATA MODULES UNTOUCHED
# =========================================================


def test_legacy_profiler_and_metadata_modules_still_work_unmodified():
    from data_engine.data_quality import check_data_quality
    from data_engine.metadata import get_metadata
    from data_engine.profiler import profile_dataset

    df = _make_dataframe()

    profile = profile_dataset(df)
    metadata = get_metadata(df)
    quality = check_data_quality(df)

    assert profile["rows"] == 6
    assert metadata["row_count"] == 6
    assert quality["status"] in {"healthy", "info", "warning", "error"}
