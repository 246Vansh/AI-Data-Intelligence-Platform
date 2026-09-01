"""Phase 2 / Step 6A: preview_dataset() - the {columns, rows} preview
payload, natively bounded to PREVIEW_ROW_LIMIT (10) rows regardless of
storage backend, never materializing a DuckDB-backed dataset's full
contents into pandas to get there.

Verifies:
  - Row/column shape matches the historical `df.head(10)` behavior for
    both storage backends, on datasets both smaller and larger than
    the limit.
  - A DuckDB-backed dataset is read via a single bounded LIMIT query -
    proven with a spy storage subclass recording to_dataframe() calls.
  - A Pandas-backed dataset still goes through to_dataframe() once
    (the existing compatibility boundary).
  - Output rows are JSON-safe (NaN/Infinity -> None, Timestamp -> ISO
    string), matching data_engine.json_safety.sanitize_records().
  - Column order is preserved.
"""

import math

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.preview import PREVIEW_ROW_LIMIT, preview_dataset
from data_engine.storage import DuckDBStorage, PandasStorage


def _make_small_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "south", "east"],
            "quantity": [10, 20, 30],
        }
    )


def _make_large_dataframe(n: int = 25) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(n),
            "value": [i * 1.5 for i in range(n)],
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


class _SpyPandasStorage(PandasStorage):
    """PandasStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# ROW/COLUMN SHAPE PARITY
# =========================================================


def test_preview_small_dataset_returns_all_rows_both_backends():
    df = _make_small_dataframe()

    pandas_preview = preview_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_preview = preview_dataset(Dataset(storage=DuckDBStorage(df)))

    assert len(pandas_preview["rows"]) == len(duckdb_preview["rows"]) == 3
    assert pandas_preview["columns"] == duckdb_preview["columns"] == ["region", "quantity"]


def test_preview_large_dataset_bounded_to_row_limit_both_backends():
    df = _make_large_dataframe(25)

    pandas_preview = preview_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_preview = preview_dataset(Dataset(storage=DuckDBStorage(df)))

    assert len(pandas_preview["rows"]) == len(duckdb_preview["rows"]) == PREVIEW_ROW_LIMIT
    assert [row["id"] for row in pandas_preview["rows"]] == list(range(PREVIEW_ROW_LIMIT))
    assert [row["id"] for row in duckdb_preview["rows"]] == list(range(PREVIEW_ROW_LIMIT))


def test_preview_respects_custom_limit():
    df = _make_large_dataframe(25)

    pandas_preview = preview_dataset(Dataset(storage=PandasStorage(df)), limit=5)
    duckdb_preview = preview_dataset(Dataset(storage=DuckDBStorage(df)), limit=5)

    assert len(pandas_preview["rows"]) == len(duckdb_preview["rows"]) == 5


# =========================================================
# BOUNDARY DISCIPLINE
# =========================================================


def test_duckdb_preview_never_calls_to_dataframe():
    df = _make_large_dataframe(25)
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    preview_dataset(dataset)

    assert storage.to_dataframe_calls == []


def test_pandas_preview_calls_to_dataframe_once():
    df = _make_large_dataframe(25)
    storage = _SpyPandasStorage(df)
    dataset = Dataset(storage=storage)

    preview_dataset(dataset)

    assert storage.to_dataframe_calls == [True]


def test_preview_not_cached_on_dataset():
    df = _make_small_dataframe()
    dataset = Dataset(storage=PandasStorage(df))

    preview_dataset(dataset)

    assert "preview" not in dataset.cache


# =========================================================
# JSON SAFETY
# =========================================================


def test_preview_sanitizes_nan_and_infinity_both_backends():
    df = pd.DataFrame({"value": [1.0, float("nan"), float("inf"), float("-inf")]})

    pandas_preview = preview_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_preview = preview_dataset(Dataset(storage=DuckDBStorage(df)))

    for preview in (pandas_preview, duckdb_preview):
        values = [row["value"] for row in preview["rows"]]
        assert values[0] == 1.0
        assert values[1] is None
        assert values[2] is None
        assert values[3] is None


def test_preview_sanitizes_timestamps_to_iso_strings_both_backends():
    df = pd.DataFrame({"created_at": pd.to_datetime(["2024-01-05", "2024-02-10"])})

    pandas_preview = preview_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_preview = preview_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_preview["rows"][0]["created_at"] == "2024-01-05T00:00:00"
    assert duckdb_preview["rows"][0]["created_at"] == "2024-01-05T00:00:00"
