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
    # Apply time transformation
    # -----------------------------------------

    working_df = apply_time_granularity(
        working_df,
        plan,
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
        sort_by=plan.sort_by,
        limit=plan.limit,
    )

    # -----------------------------------------
    # Return result
    # -----------------------------------------

    return result

def apply_time_granularity(
    df: pd.DataFrame,
    plan: AnalysisPlan,
) -> pd.DataFrame:

    if plan.time_granularity is None:
        return df

    if "Date" not in df.columns:
        raise ValueError(
            "Time analysis requires a Date column."
        )

    result = df.copy()

    granularity = (
        plan.time_granularity
    )

    if granularity == "day":

        result["Date"] = (
            result["Date"]
            .dt.floor("D")
        )

    elif granularity == "week":

        result["Date"] = (
            result["Date"]
            .dt.to_period("W")
            .dt.start_time
        )

    elif granularity == "month":

        result["Date"] = (
            result["Date"]
            .dt.to_period("M")
            .dt.start_time
        )

    elif granularity == "quarter":

        result["Date"] = (
            result["Date"]
            .dt.to_period("Q")
            .dt.start_time
        )

    elif granularity == "year":

        result["Date"] = (
            result["Date"]
            .dt.to_period("Y")
            .dt.start_time
        )

    else:

        raise ValueError(
            f"Unsupported time granularity: "
            f"{granularity}"
        )

    return result