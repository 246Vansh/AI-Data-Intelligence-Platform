from typing import Any

import pandas as pd

from data_engine.metadata import get_metadata
from data_engine.dataset_profile import profile_dataset
from data_engine.data_quality import check_data_quality


def build_dataset_intelligence(
    df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Build a complete dataset intelligence summary.

    Combines:
        - metadata
        - statistical profile
        - data quality

    This layer is dataset-independent.

    It does not:
        - execute analysis plans
        - contain business-specific logic
        - contain dataset-specific column names
        - call AI
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    # -------------------------------------------------
    # Dataset shape
    # -------------------------------------------------

    shape = {
        "rows": len(df),
        "columns": len(df.columns),
    }

    # -------------------------------------------------
    # Metadata
    # -------------------------------------------------

    metadata = get_metadata(df)

    # -------------------------------------------------
    # Data quality
    #
    # Quality analysis must run even for an empty
    # dataset because it is responsible for identifying
    # the dataset as invalid.
    # -------------------------------------------------

    quality = check_data_quality(df)

    # -------------------------------------------------
    # Empty dataset
    #
    # The profiler intentionally rejects empty datasets.
    # Therefore, do not call it here.
    # -------------------------------------------------

    if df.empty:
        return {
            "shape": shape,
            "metadata": metadata,
            "profile": None,
            "quality": quality,
        }

    # -------------------------------------------------
    # Statistical profile
    # -------------------------------------------------

    profile = profile_dataset(df)

    # -------------------------------------------------
    # Final intelligence object
    # -------------------------------------------------

    return {
        "shape": shape,
        "metadata": metadata,
        "profile": profile,
        "quality": quality,
    }
