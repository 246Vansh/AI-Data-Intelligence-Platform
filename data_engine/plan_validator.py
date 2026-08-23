import pandas as pd

from data_engine.analysis_plan import (
    AnalysisPlan,
    AGGREGATION_ALIASES,
    CANONICAL_AGGREGATIONS as ALLOWED_AGGREGATIONS,
)


# =========================================================
# ALLOWED OPERATORS
# =========================================================

ALLOWED_OPERATORS = {
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
}


# =========================================================
# VISUALIZATIONS
# =========================================================

ALLOWED_VISUALIZATIONS = {
    "bar",
    "line",
    "pie",
    "scatter",
    "table",
}


# =========================================================
# TIME GRANULARITIES
# =========================================================

ALLOWED_TIME_GRANULARITIES = {
    "day",
    "week",
    "month",
    "quarter",
    "year",
}


# =========================================================
# SORT FIELDS
# =========================================================

ALLOWED_SORT_BY = {
    "metric",
    "time",
}


# =========================================================
# NORMALIZE AGGREGATION
# =========================================================


def normalize_aggregation(
    aggregation,
) -> str:
    """
    Convert an aggregation name into the canonical
    Data Engine representation.

    Examples:

        "sum"       -> "sum"
        "total"     -> "sum"
        "average"   -> "mean"
        "avg"       -> "mean"
        "minimum"   -> "min"
        "maximum"   -> "max"
        "number of" -> "count"
    """

    if aggregation is None:
        raise ValueError("Aggregation cannot be empty.")

    normalized = str(aggregation).strip().lower().replace("-", "_").replace(" ", "_")

    canonical = AGGREGATION_ALIASES.get(normalized)

    if canonical is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")

    return canonical


# =========================================================
# NORMALIZE SORT
# =========================================================


def normalize_sort(
    sort,
) -> str:
    """
    Normalize sort direction.
    """

    if sort is None:
        return "desc"

    normalized = str(sort).strip().lower()

    if normalized not in {
        "asc",
        "desc",
    }:
        raise ValueError(f"Unsupported sort direction: {sort}")

    return normalized


# =========================================================
# NORMALIZE SORT BY
# =========================================================


def normalize_sort_by(
    sort_by,
) -> str:
    """
    Normalize the field used for sorting.
    """

    if sort_by is None:
        return "metric"

    normalized = str(sort_by).strip().lower()

    if normalized not in ALLOWED_SORT_BY:
        raise ValueError(f"Unsupported sort field: {sort_by}")

    return normalized


# =========================================================
# VALIDATE PLAN
# =========================================================


def validate_plan(
    df: pd.DataFrame,
    plan: AnalysisPlan,
    metadata: dict | None = None,
) -> None:

    # =====================================================
    # Validate group-by columns
    # =====================================================

    for column in plan.group_by:
        if column not in df.columns:
            raise ValueError(f"Unknown group-by column: {column}")

    # =====================================================
    # Validate metric
    # =====================================================

    if plan.metric is not None:
        if plan.metric not in df.columns:
            raise ValueError(f"Unknown metric: {plan.metric}")

    # =====================================================
    # Validate aggregation
    #
    # IMPORTANT:
    #
    # Normalize aliases before validation.
    #
    # This protects the Data Engine even if an upstream
    # planner accidentally returns:
    #
    #     average
    #     avg
    #     total
    #     minimum
    #     maximum
    #
    # instead of the canonical values.
    # =====================================================

    plan.aggregation = normalize_aggregation(plan.aggregation)

    # =====================================================
    # Validate filters
    # =====================================================

    for condition in plan.filters:
        if condition.column not in df.columns:
            raise ValueError(f"Unknown filter column: {condition.column}")

        if condition.operator not in ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported operator: {condition.operator}")

    # =====================================================
    # Validate limit
    # =====================================================

    if plan.limit is not None:
        if not isinstance(
            plan.limit,
            int,
        ):
            raise ValueError("Limit must be an integer.")

        if plan.limit <= 0:
            raise ValueError("Limit must be greater than zero.")

    # =====================================================
    # Validate visualization
    # =====================================================

    if plan.visualization is not None:
        visualization = str(plan.visualization).strip().lower()

        if visualization not in ALLOWED_VISUALIZATIONS:
            raise ValueError(f"Unsupported visualization: {plan.visualization}")

        plan.visualization = visualization

    # =====================================================
    # Validate time analysis
    # =====================================================

    if plan.time_granularity is not None:
        # -------------------------------------------------
        # Validate granularity
        # -------------------------------------------------

        if plan.time_granularity not in ALLOWED_TIME_GRANULARITIES:
            raise ValueError(f"Unsupported time granularity: {plan.time_granularity}")

        # -------------------------------------------------
        # Time granularity requires a time column
        # -------------------------------------------------

        if not plan.time_column:
            raise ValueError("Time granularity requires a time column.")

        # -------------------------------------------------
        # Validate time column
        # -------------------------------------------------

        if plan.time_column not in df.columns:
            raise ValueError(f"Unknown time column: {plan.time_column}")

    # =====================================================
    # Validate time column
    # =====================================================

    if plan.time_column is not None:
        if plan.time_column not in df.columns:
            raise ValueError(f"Unknown time column: {plan.time_column}")

        # -------------------------------------------------
        # Metadata validation
        # -------------------------------------------------

        if metadata is not None:
            columns_metadata = metadata.get(
                "columns",
                {},
            )

            column_metadata = columns_metadata.get(plan.time_column)

            if column_metadata is None:
                raise ValueError(
                    f"Time column is missing from metadata: {plan.time_column}"
                )

            if column_metadata.get("role") != "time":
                raise ValueError(
                    f"Column '{plan.time_column}' is not marked as a time column."
                )

    # =====================================================
    # Normalize + validate sort
    # =====================================================

    plan.sort = normalize_sort(plan.sort)

    # =====================================================
    # Normalize + validate sort field
    # =====================================================

    plan.sort_by = normalize_sort_by(plan.sort_by)

    # =====================================================
    # Time sorting requires time analysis
    # =====================================================

    if plan.sort_by == "time":
        if plan.time_granularity is None:
            raise ValueError("Time sorting requires time_granularity.")

        if plan.time_column is None:
            raise ValueError("Time sorting requires time_column.")

        if plan.time_column not in df.columns:
            raise ValueError(f"Unknown time column: {plan.time_column}")

        # -------------------------------------------------
        # Time sorting should use a time group-by column.
        # -------------------------------------------------

        if plan.time_column not in plan.group_by:
            raise ValueError(
                "Time sorting requires the time column to be included in group_by."
            )
