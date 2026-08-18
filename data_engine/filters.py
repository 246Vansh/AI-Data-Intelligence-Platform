import pandas as pd


def filter_equals(
    df: pd.DataFrame,
    column: str,
    value,
) -> pd.DataFrame:

    if column not in df.columns:
        raise ValueError(
            f"Unknown column: {column}"
        )

    return df[df[column] == value].copy()


def filter_greater_than(
    df: pd.DataFrame,
    column: str,
    value,
) -> pd.DataFrame:

    if column not in df.columns:
        raise ValueError(
            f"Unknown column: {column}"
        )

    return df[df[column] > value].copy()


def filter_less_than(
    df: pd.DataFrame,
    column: str,
    value,
) -> pd.DataFrame:

    if column not in df.columns:
        raise ValueError(
            f"Unknown column: {column}"
        )

    return df[df[column] < value].copy()