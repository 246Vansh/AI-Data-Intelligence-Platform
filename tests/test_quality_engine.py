"""Phase 2 / Step 6A: QualityEngine - dataset quality analysis
(duplicate rows, missing values, constant columns, high cardinality,
IQR numeric outliers) natively behind a storage-aware engine boundary,
mirroring data_engine.profiling's ProfilingEngine pattern.

Verifies:
  - QualityEngine is a genuine abstract contract.
  - PandasQualityEngine and DuckDBQualityEngine both satisfy it.
  - select_quality_engine_for()/check_quality_for_dataset() route
    purely on the Dataset's own storage type.
  - Full issue-set parity between the two engines across duplicate
    rows, missing values, constant columns, high cardinality, and IQR
    outliers.
  - The empty-dataset short-circuit response is preserved.
  - DuckDBQualityEngine never calls storage.to_dataframe() - proven
    with a spy storage subclass.
  - data_engine.data_quality (the unmodified Pandas baseline) still
    works standalone.
"""

import pandas as pd
import pytest

from data_engine.data_quality import check_data_quality
from data_engine.dataset import Dataset
from data_engine.quality import (
    DuckDBQualityEngine,
    PandasQualityEngine,
    QualityEngine,
    check_quality_for_dataset,
    select_quality_engine_for,
)
from data_engine.storage import DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    # 24 rows: one duplicate pair, a missing-heavy column, a constant
    # column, a high-cardinality column, and a numeric column with
    # real quartile spread plus one clear IQR outlier - large enough
    # that pandas' and DuckDB's quantile interpolation agree on which
    # rows are outliers.
    n = 24
    amounts = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0] * (n // 6)
    amounts[-1] = 100000.0

    return pd.DataFrame(
        {
            "region": (["north", "south"] * (n // 2)),
            "flag": ["y"] * n,  # constant column
            "notes": [None if i % 3 == 0 else f"note-{i}" for i in range(n)],  # missing
            "customer_id": [f"cust-{i}" for i in range(n)],  # high cardinality
            "amount": amounts,  # one clear outlier against real spread
        }
    )


def _make_duplicate_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1, 1, 2, 3],
            "b": ["x", "x", "y", "z"],
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


def test_quality_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        QualityEngine()


def test_pandas_quality_engine_is_a_quality_engine():
    assert isinstance(PandasQualityEngine(), QualityEngine)


def test_duckdb_quality_engine_is_a_quality_engine():
    assert isinstance(DuckDBQualityEngine(), QualityEngine)


# =========================================================
# SELECTOR - routes by storage type
# =========================================================


def test_selector_picks_duckdb_engine_for_duckdb_storage():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()))
    assert isinstance(select_quality_engine_for(dataset), DuckDBQualityEngine)


def test_selector_picks_pandas_engine_for_pandas_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    assert isinstance(select_quality_engine_for(dataset), PandasQualityEngine)


# =========================================================
# ISSUE-SET PARITY - identical synthetic dataset, both engines
# =========================================================


def _issue_keys(issues):
    return {(issue["type"], issue.get("column")) for issue in issues}


def test_quality_parity_status_and_issue_count():
    df = _make_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_quality["status"] == duckdb_quality["status"]
    assert pandas_quality["issue_count"] == duckdb_quality["issue_count"]


def test_quality_parity_issue_types_and_columns():
    df = _make_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert _issue_keys(pandas_quality["issues"]) == _issue_keys(duckdb_quality["issues"])


def test_quality_parity_detects_each_issue_type():
    df = _make_dataframe()
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    keys = _issue_keys(duckdb_quality["issues"])
    assert ("missing_values", "notes") in keys
    assert ("constant_column", "flag") in keys
    assert ("high_cardinality", "customer_id") in keys
    assert ("numeric_outliers", "amount") in keys


def test_quality_parity_duplicate_rows():
    df = _make_duplicate_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    pandas_dup = next(i for i in pandas_quality["issues"] if i["type"] == "duplicate_rows")
    duckdb_dup = next(i for i in duckdb_quality["issues"] if i["type"] == "duplicate_rows")

    assert pandas_dup["count"] == duckdb_dup["count"] == 1


# =========================================================
# EMPTY-DATASET SHORT-CIRCUIT PRESERVED
# =========================================================


def test_duckdb_quality_empty_dataset_response():
    # DuckDBStorage rejects an empty DataFrame at construction time
    # (like PandasStorage) - build a from_parquet-style zero-row VIEW
    # instead to exercise the empty-result path DuckDBQualityEngine
    # itself must still handle.
    import os
    import tempfile

    df = pd.DataFrame({"a": [1]})
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "empty.parquet")
        df.iloc[0:0].to_parquet(path)
        storage = DuckDBStorage.from_parquet(path)
        dataset = Dataset(storage=storage)

        result = check_quality_for_dataset(dataset)

    assert result["status"] == "invalid"
    assert result["issue_count"] == 1
    assert result["issues"][0]["type"] == "empty_dataset"


# =========================================================
# BOUNDARY DISCIPLINE - zero to_dataframe() for DuckDB quality
# =========================================================


def test_duckdb_quality_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    check_quality_for_dataset(dataset)

    assert storage.to_dataframe_calls == []


def test_duckdb_quality_engine_rejects_non_duckdb_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))

    with pytest.raises(TypeError):
        DuckDBQualityEngine().check_quality(dataset)


# =========================================================
# EXISTING BASELINE MODULE UNTOUCHED
# =========================================================


def test_legacy_data_quality_module_still_works_unmodified():
    df = _make_dataframe()
    quality = check_data_quality(df)

    assert quality["status"] in {"healthy", "info", "warning", "error"}
