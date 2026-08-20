from __future__ import annotations

from typing import Any

import pandas as pd


def profile_dataset(
    df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Generate a dataset-independent profile.

    This function does not make assumptions about:
    - business domain
    - column names
    - dataset source
    - specific metrics
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    if df.empty:
        raise ValueError("Cannot profile an empty dataset.")

    columns = {}

    for column in df.columns:
        series = df[column]

        columns[column] = _profile_column(series)

    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "memory_usage_bytes": int(
            df.memory_usage(
                index=True,
                deep=True,
            ).sum()
        ),
        "duplicate_row_count": int(df.duplicated().sum()),
        "columns": columns,
    }


def _profile_column(
    series: pd.Series,
) -> dict[str, Any]:
    """
    Profile one column.
    """

    row_count = len(series)

    missing_count = int(series.isna().sum())

    missing_percentage = (missing_count / row_count) * 100 if row_count > 0 else 0.0

    unique_count = int(
        series.nunique(
            dropna=True,
        )
    )

    profile: dict[str, Any] = {
        "data_type": _detect_data_type(series),
        "nullable": bool(missing_count > 0),
        "missing_count": missing_count,
        "missing_percentage": round(
            missing_percentage,
            2,
        ),
        "unique_count": unique_count,
        "unique_percentage": round(
            ((unique_count / row_count) * 100 if row_count > 0 else 0.0),
            2,
        ),
        "sample_values": (series.dropna().head(5).tolist()),
    }

    # -----------------------------------------
    # Numeric statistics
    # -----------------------------------------

    if pd.api.types.is_numeric_dtype(series):
        numeric = series.dropna()

        if not numeric.empty:
            profile["statistics"] = {
                "min": _safe_value(numeric.min()),
                "max": _safe_value(numeric.max()),
                "mean": _safe_value(numeric.mean()),
                "median": _safe_value(numeric.median()),
                "std": _safe_value(numeric.std()),
            }

    # -----------------------------------------
    # Categorical statistics
    # -----------------------------------------

    if (
        pd.api.types.is_object_dtype(series)
        or pd.api.types.is_string_dtype(series)
        or pd.api.types.is_categorical_dtype(series)
    ):
        value_counts = series.dropna().value_counts().head(10)

        profile["top_values"] = [
            {
                "value": _safe_value(value),
                "count": int(count),
            }
            for value, count in value_counts.items()
        ]

    return profile


def _detect_data_type(
    series: pd.Series,
) -> str:

    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    if pd.api.types.is_bool_dtype(series):
        return "boolean"

    if pd.api.types.is_integer_dtype(series):
        return "integer"

    if pd.api.types.is_float_dtype(series):
        return "float"

    if pd.api.types.is_numeric_dtype(series):
        return "numeric"

    return "string"


def _safe_value(
    value: Any,
) -> Any:

    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass

    return value
