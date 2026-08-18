import pandas as pd


ALLOWED_AGGREGATIONS = {
    "sum": "sum",
    "mean": "mean",
    "median": "median",
    "min": "min",
    "max": "max",
    "count": "count",
}


ALLOWED_SORT_BY = {
    "metric",
    "time",
}


def analyze(
    df: pd.DataFrame,
    group_by: list[str],
    metric: str,
    aggregation: str = "sum",
    sort: str = "desc",
    sort_by: str = "metric",
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

    # -----------------------------------------
    # Validate sort
    # -----------------------------------------

    if sort.lower() not in {
        "asc",
        "desc",
    }:

        raise ValueError(
            f"Unsupported sort direction: "
            f"{sort}"
        )

    # -----------------------------------------
    # Validate sort_by
    # -----------------------------------------

    if sort_by not in ALLOWED_SORT_BY:

        raise ValueError(
            f"Unsupported sort field: "
            f"{sort_by}"
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

    metric_column = (
        f"{aggregation}_{metric}"
    )

    result = result.rename(
        columns={
            metric: metric_column
        }
    )

    # -----------------------------------------
    # Sort
    # -----------------------------------------

    ascending = (
        sort.lower() == "asc"
    )

    if sort_by == "metric":

        result = result.sort_values(
            by=metric_column,
            ascending=ascending,
        )

    elif sort_by == "time":

        time_columns = [
            column
            for column in group_by
            if pd.api.types.is_datetime64_any_dtype(
                result[column]
            )
        ]

        if not time_columns:

            raise ValueError(
                "Time sorting requires a "
                "datetime group-by column."
            )

        time_column = time_columns[0]

        result = result.sort_values(
            by=time_column,
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