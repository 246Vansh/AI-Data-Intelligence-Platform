import pandas as pd


def profile_dataset(df: pd.DataFrame) -> dict:
    """
    Generate a detailed profile of a Pandas DataFrame.
    """

    columns = {}

    for column in df.columns:
        series = df[column]

        columns[column] = {
            "data_type": str(series.dtype),
            "missing_count": int(series.isna().sum()),
            "missing_percentage": round(
                series.isna().mean() * 100, 2
            ),
            "unique_values": int(series.nunique()),
        }

    profile = {
        "rows": len(df),
        "columns": len(df.columns),

        "column_names": df.columns.tolist(),

        "data_types": {
            column: str(dtype)
            for column, dtype in df.dtypes.items()
        },

        "missing_values": {
            column: int(value)
            for column, value in df.isnull().sum().items()
        },

        "duplicate_rows": int(
            df.duplicated().sum()
        ),

        "memory_usage_bytes": int(
            df.memory_usage(deep=True).sum()
        ),

        "column_details": columns,
    }

    return profile