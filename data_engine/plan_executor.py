import pandas as pd

from data_engine.analysis_plan import AnalysisPlan
from data_engine.query_engine import analyze


def apply_filter(
    df: pd.DataFrame,
    condition,
) -> pd.DataFrame:

    column = condition.column
    operator = condition.operator
    value = condition.value

    if column not in df.columns:
        raise ValueError(
            f"Unknown column: {column}"
        )

    if operator == "=":
        return df[df[column] == value].copy()

    if operator == "!=":
        return df[df[column] != value].copy()

    if operator == ">":
        return df[df[column] > value].copy()

    if operator == ">=":
        return df[df[column] >= value].copy()

    if operator == "<":
        return df[df[column] < value].copy()

    if operator == "<=":
        return df[df[column] <= value].copy()

    raise ValueError(
        f"Unsupported operator: {operator}"
    )


def execute_plan(
    df: pd.DataFrame,
    plan: AnalysisPlan,
) -> pd.DataFrame:

    working_df = df.copy()

    # -----------------------------------------
    # Apply filters
    # -----------------------------------------

    for condition in plan.filters:

        working_df = apply_filter(
            working_df,
            condition,
        )

    # -----------------------------------------
    # Perform analysis
    # -----------------------------------------

    if plan.metric is None:

        raise ValueError(
            "Analysis plan requires a metric."
        )

    result = analyze(
        df=working_df,
        group_by=plan.group_by,
        metric=plan.metric,
        aggregation=plan.aggregation,
        sort=plan.sort,
        limit=plan.limit,
    )

    # -----------------------------------------
    # Return result
    # -----------------------------------------

    return result