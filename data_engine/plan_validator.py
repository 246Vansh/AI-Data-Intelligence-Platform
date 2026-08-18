import pandas as pd

from data_engine.analysis_plan import AnalysisPlan


ALLOWED_OPERATORS = {
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
}

ALLOWED_AGGREGATIONS = {
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "count",
}

ALLOWED_VISUALIZATIONS = {
    "bar",
    "line",
    "pie",
    "scatter",
    "table",
}


def validate_plan(
    df: pd.DataFrame,
    plan: AnalysisPlan,
) -> None:

    # -----------------------------------------
    # Validate group-by columns
    # -----------------------------------------

    for column in plan.group_by:

        if column not in df.columns:
            raise ValueError(
                f"Unknown group-by column: {column}"
            )

    # -----------------------------------------
    # Validate metric
    # -----------------------------------------

    if plan.metric not in df.columns:
        raise ValueError(
            f"Unknown metric: {plan.metric}"
        )

    # -----------------------------------------
    # Validate aggregation
    # -----------------------------------------

    if plan.aggregation not in ALLOWED_AGGREGATIONS:
        raise ValueError(
            f"Unsupported aggregation: "
            f"{plan.aggregation}"
        )

    # -----------------------------------------
    # Validate filters
    # -----------------------------------------

    for condition in plan.filters:

        if condition.column not in df.columns:
            raise ValueError(
                f"Unknown filter column: "
                f"{condition.column}"
            )

        if condition.operator not in ALLOWED_OPERATORS:
            raise ValueError(
                f"Unsupported operator: "
                f"{condition.operator}"
            )

    # -----------------------------------------
    # Validate limit
    # -----------------------------------------

    if plan.limit is not None:

        if plan.limit <= 0:
            raise ValueError(
                "Limit must be greater than zero."
            )

    # -----------------------------------------
    # Validate visualization
    # -----------------------------------------

    if (
        plan.visualization is not None
        and plan.visualization
        not in ALLOWED_VISUALIZATIONS
    ):
        raise ValueError(
            f"Unsupported visualization: "
            f"{plan.visualization}"
        )