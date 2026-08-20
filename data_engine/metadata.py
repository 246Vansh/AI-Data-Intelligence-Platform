import pandas as pd


def detect_column_role(
    series: pd.Series,
    column_name: str,
) -> str:

    column_lower = column_name.lower()

    # -----------------------------------------
    # Time columns
    # -----------------------------------------

    if (
        pd.api.types.is_datetime64_any_dtype(series)
        or "date" in column_lower
        or "time" in column_lower
    ):
        return "time"

    # -----------------------------------------
    # Known categorical / dimension patterns
    # -----------------------------------------

    if "flag" in column_lower or "id" in column_lower or "store" in column_lower:
        return "dimension"

    # -----------------------------------------
    # Numeric columns
    # -----------------------------------------

    if pd.api.types.is_numeric_dtype(series):
        return "metric"

    # -----------------------------------------
    # Everything else
    # -----------------------------------------

    return "dimension"


def detect_data_type(
    series: pd.Series,
) -> str:

    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    if pd.api.types.is_integer_dtype(series):
        return "integer"

    if pd.api.types.is_float_dtype(series):
        return "float"

    if pd.api.types.is_bool_dtype(series):
        return "boolean"

    return "string"


def get_allowed_operations(
    role: str,
) -> list[str]:

    if role == "metric":
        return [
            "sum",
            "mean",
            "median",
            "min",
            "max",
            "count",
        ]

    if role == "dimension":
        return [
            "group_by",
            "filter",
            "count",
        ]

    if role == "categorical":
        return [
            "group_by",
            "filter",
            "count",
        ]

    if role == "time":
        return [
            "group_by",
            "filter",
            "trend",
        ]

    return []


def get_metadata(
    df: pd.DataFrame,
) -> dict:

    columns = {}

    for column in df.columns:
        series = df[column]

        role = detect_column_role(
            series,
            column,
        )

        data_type = detect_data_type(series)

        columns[column] = {
            "data_type": data_type,
            "role": role,
            "allowed_operations": (get_allowed_operations(role)),
            "nullable": bool(series.isna().any()),
            "missing_count": int(series.isna().sum()),
            "unique_values": int(series.nunique()),
            "sample_values": (series.dropna().head(5).tolist()),
        }

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns,
    }
