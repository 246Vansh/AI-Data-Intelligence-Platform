"""Phase 2 / Step 6A: MetadataEngine - dataset metadata generation
(per-column data type, semantic role, allowed operations, nullability,
missing/unique counts, bounded sample_values, plus time_column/
time_columns) natively behind a storage-aware engine boundary,
mirroring data_engine.profiling's ProfilingEngine pattern.

Verifies:
  - MetadataEngine is a genuine abstract contract.
  - PandasMetadataEngine and DuckDBMetadataEngine both satisfy it.
  - select_metadata_engine_for()/metadata_for_dataset() route purely on
    the Dataset's own storage type.
  - Full response parity between the two engines on an identical
    synthetic dataset (<=100 rows, inside DuckDB's LIMIT 100 sample
    window).
  - DuckDBMetadataEngine never calls storage.to_dataframe() - proven
    with a spy storage subclass - even on a dataset larger than the
    100-row sample window.
  - counts (row_count, missing_count, unique_values) stay exact beyond
    the 100-row sample window; only role detection/sample_values are
    sample-bounded.
  - data_engine.metadata (the unmodified Pandas baseline) still works
    standalone.
"""

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.metadata import get_metadata
from data_engine.metadata_engine import (
    DuckDBMetadataEngine,
    MetadataEngine,
    PandasMetadataEngine,
    metadata_for_dataset,
    select_metadata_engine_for,
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


def test_metadata_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        MetadataEngine()


def test_pandas_metadata_engine_is_a_metadata_engine():
    assert isinstance(PandasMetadataEngine(), MetadataEngine)


def test_duckdb_metadata_engine_is_a_metadata_engine():
    assert isinstance(DuckDBMetadataEngine(), MetadataEngine)


# =========================================================
# SELECTOR - routes by storage type
# =========================================================


def test_selector_picks_duckdb_engine_for_duckdb_storage():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()))
    assert isinstance(select_metadata_engine_for(dataset), DuckDBMetadataEngine)


def test_selector_picks_pandas_engine_for_pandas_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    assert isinstance(select_metadata_engine_for(dataset), PandasMetadataEngine)


# =========================================================
# FULL RESPONSE PARITY - identical synthetic dataset, both engines
# =========================================================


def test_metadata_parity_row_and_column_counts():
    df = _make_dataframe()

    pandas_meta = metadata_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_meta = metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_meta["row_count"] == duckdb_meta["row_count"] == 6
    assert pandas_meta["column_count"] == duckdb_meta["column_count"] == 6


def test_metadata_parity_time_column_selection():
    df = _make_dataframe()

    pandas_meta = metadata_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_meta = metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_meta["time_column"] == duckdb_meta["time_column"] == "signed_up_at"
    assert pandas_meta["time_columns"] == duckdb_meta["time_columns"] == ["signed_up_at"]


@pytest.mark.parametrize(
    "column",
    ["region", "category", "quantity", "price", "is_active", "signed_up_at"],
)
def test_metadata_parity_per_column(column):
    df = _make_dataframe()

    pandas_meta = metadata_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_meta = metadata_for_dataset(Dataset(storage=DuckDBStorage(df)))

    pandas_column = pandas_meta["columns"][column]
    duckdb_column = duckdb_meta["columns"][column]

    for key in ("data_type", "role", "allowed_operations", "nullable", "missing_count", "unique_values"):
        assert pandas_column[key] == duckdb_column[key], f"{column}.{key} mismatch"

    assert pandas_column["sample_values"] == duckdb_column["sample_values"]


# =========================================================
# BOUNDARY DISCIPLINE - zero to_dataframe() for DuckDB metadata,
# even beyond the LIMIT 100 sample window
# =========================================================


def test_duckdb_metadata_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    metadata_for_dataset(dataset)

    assert storage.to_dataframe_calls == []


def test_duckdb_metadata_never_calls_to_dataframe_beyond_sample_window():
    df = pd.DataFrame(
        {
            "id": range(250),
            "value": [i % 7 for i in range(250)],
        }
    )
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    metadata = metadata_for_dataset(dataset)

    assert storage.to_dataframe_calls == []
    assert metadata["row_count"] == 250
    assert metadata["columns"]["id"]["unique_values"] == 250
    assert metadata["columns"]["id"]["missing_count"] == 0


def test_duckdb_metadata_engine_rejects_non_duckdb_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))

    with pytest.raises(TypeError):
        DuckDBMetadataEngine().get_metadata(dataset)


def test_duckdb_metadata_sample_values_bounded_to_five():
    df = pd.DataFrame({"category": [f"c{i}" for i in range(50)]})
    dataset = Dataset(storage=DuckDBStorage(df))

    metadata = metadata_for_dataset(dataset)

    assert len(metadata["columns"]["category"]["sample_values"]) == 5


# =========================================================
# EXISTING BASELINE MODULE UNTOUCHED
# =========================================================


def test_legacy_metadata_module_still_works_unmodified():
    df = _make_dataframe()
    metadata = get_metadata(df)

    assert metadata["row_count"] == 6
    assert "signed_up_at" in metadata["time_columns"]
