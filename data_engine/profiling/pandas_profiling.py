from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.metadata import detect_data_type
from data_engine.profiling._shared import safe_scalar
from data_engine.profiling.base import ProfilingEngine


class PandasProfilingEngine(ProfilingEngine):
    """
    Pandas-backed adapter satisfying the ProfilingEngine contract.

    Reuses the storage contract's to_dataframe() compatibility
    boundary and plain pandas Series operations - it introduces no new
    statistical logic, only reshapes the same missing/distinct/min/max/
    dtype facts data_engine.profiler and data_engine.metadata already
    compute into the shared basic_statistics() contract, and reuses
    data_engine.metadata.detect_data_type() for the same "basic data
    type" categorization used everywhere else in the codebase, so
    results compare like-for-like with DuckDBProfilingEngine's output.
    """

    def basic_statistics(self, dataset: Dataset) -> dict[str, Any]:
        # Strictly through the storage contract - never
        # dataset.dataframe, never an isinstance check on the concrete
        # storage backend.
        df = dataset.storage.to_dataframe()

        row_count = len(df)
        columns: dict[str, Any] = {}

        for column in df.columns:
            series = df[column]

            missing_count = int(series.isna().sum())
            non_null = series.dropna()

            min_value = None
            max_value = None

            if not non_null.empty:
                try:
                    min_value = safe_scalar(non_null.min())
                    max_value = safe_scalar(non_null.max())
                except TypeError:
                    # Non-orderable values (rare mixed-type columns) -
                    # bounds simply stay unavailable, same as DuckDB
                    # would report for a type it can't MIN/MAX either.
                    min_value = None
                    max_value = None

            columns[str(column)] = {
                "data_type": detect_data_type(series),
                "missing_count": missing_count,
                "missing_percentage": round(
                    (missing_count / row_count) * 100 if row_count else 0.0,
                    2,
                ),
                "distinct_count": int(series.nunique(dropna=True)),
                "min": min_value,
                "max": max_value,
            }

        return {
            "row_count": int(row_count),
            "column_count": int(len(df.columns)),
            "columns": columns,
            # Legacy-only stats (data_engine.profiler.profile_dataset) -
            # not part of the shared min/max/distinct/dtype contract
            # above, but preserved here so callers bridging into that
            # historical shape (e.g. the /profile route) never have to
            # materialize the DataFrame a second time to get them.
            "duplicate_rows": int(df.duplicated().sum()),
            "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
        }
