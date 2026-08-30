from __future__ import annotations

from typing import Any

import pandas as pd


def safe_scalar(value: Any) -> Any:
    """
    Convert a raw pandas/DuckDB scalar into a plain, JSON-friendly
    Python value shared by every ProfilingEngine implementation, so
    min/max bounds compare equal across engines regardless of which
    numpy/pandas/DuckDB scalar wrapper produced them.

    Handles the known cross-engine edge cases: NaN/NaT/None all
    collapse to None (the same "missing" concept as SQL NULL),
    datetime-like values become ISO-8601 strings, and numpy/pandas
    scalar wrappers unwrap to native Python types.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass

    return value
