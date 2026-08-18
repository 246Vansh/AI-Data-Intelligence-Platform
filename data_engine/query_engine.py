import pandas as pd


ALLOWED_AGGREGATIONS = {
    "sum": "sum",
    "mean": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "count": "count",
}


def analyze(
    df: pd.DataFrame,
    group_by: list[str],
    metric: str,
    aggregation: str = "sum",
    sort: str = "desc",
    limit: int | None = None,
) -> pd.DataFrame:

    # -----------------------------------------
    # Validate columns
    # -----------------------------------------

    required_columns = set(
        group_by + [metric]
    )

    missing_columns = (
        required_columns
        - set(df.columns)
    )

    if missing_columns:

        raise ValueError(
            f"Unknown columns: "
            f"{sorted(missing_columns)}"
        )

    # -----------------------------------------
    # Validate aggregation
    # -----------------------------------------

    if aggregation not in ALLOWED_AGGREGATIONS:

        raise ValueError(
            f"Unsupported aggregation: "
            f"{aggregation}"
        )

    aggregation_function = (
        ALLOWED_AGGREGATIONS[
            aggregation
        ]
    )

    # =========================================
    # GLOBAL AGGREGATION
    # =========================================

    if not group_by:

        value = getattr(
            df[metric],
            aggregation_function,
        )()

        result = pd.DataFrame(
            {
                f"{aggregation}_{metric}": [
                    value
                ]
            }
        )

        return result.reset_index(
            drop=True
        )

    # =========================================
    # GROUPED AGGREGATION
    # =========================================

    result = (
        df.groupby(group_by)[metric]
        .agg(aggregation_function)
        .reset_index()
    )

    # -----------------------------------------
    # Rename metric
    # -----------------------------------------

    result = result.rename(
        columns={
            metric: (
                f"{aggregation}_{metric}"
            )
        }
    )

    # -----------------------------------------
    # Sort
    # -----------------------------------------

    ascending = (
        sort.lower() == "asc"
    )

    result = result.sort_values(
        by=f"{aggregation}_{metric}",
        ascending=ascending,
    )

    # -----------------------------------------
    # Limit
    # -----------------------------------------

    if limit is not None:

        result = result.head(
            limit
        )

    return result.reset_index(
        drop=True
    )