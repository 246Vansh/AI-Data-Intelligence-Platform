from __future__ import annotations

import math
from typing import Any

import pandas as pd


# =========================================================
# JSON SAFETY
# =========================================================
#
# Single source of truth for making pandas/numpy values safe for
# JSON serialization. Previously duplicated (with slightly
# different bugs) in backend/routes/analysis.py,
# backend/routes/dataset.py, and data_engine/metadata.py:
#   - the routes' versions caught +/-Infinity but not
#     pd.Timestamp values
#   - the metadata.py version caught Timestamp but not Infinity
#     (pd.isna(float("inf")) is False, so it slipped through)
#
# This version handles both, plus NaT and other pandas "missing"
# markers, in one place.


def make_json_safe(value: Any) -> Any:
    """
    Convert a single scalar value into a JSON-safe representation.

        NaN / NaT                -> None
        +Infinity / -Infinity    -> None
        pandas.Timestamp         -> ISO 8601 string
        anything else            -> unchanged
    """

    try:
        if pd.isna(value):
            return None

    except (TypeError, ValueError):
        # pd.isna() raises for some array-like inputs (e.g. a list
        # or ndarray value). Those are not the scalar case this
        # helper targets, so fall through and return them as-is.
        pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def sanitize_records(records: list[dict]) -> list[dict]:
    """
    Apply make_json_safe to every value in a list of row dicts
    (the shape produced by DataFrame.to_dict(orient="records")).
    """

    return [
        {key: make_json_safe(value) for key, value in row.items()}
        for row in records
    ]


def sanitize_json(value: Any) -> Any:
    """
    Recursively sanitize an arbitrary JSON-like structure.

    Used for response payloads that are not plain DataFrame rows
    (e.g. a Pydantic model's .model_dump()) but can still contain
    NaN/Infinity floats sourced from the dataset.
    """

    if isinstance(value, dict):
        return {key: sanitize_json(val) for key, val in value.items()}

    if isinstance(value, list):
        return [sanitize_json(item) for item in value]

    return make_json_safe(value)
