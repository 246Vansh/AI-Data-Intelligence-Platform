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
        raise ValueError(f"Unknown column: {column}")

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

    raise ValueError(f"Unsupported operator: {operator}")


def execute_plan(
    df: pd.DataFrame,
    plan: AnalysisPlan,
) -> pd.DataFrame:

    # Shallow copy: column additions/filters create new
    # objects, the source DataFrame is never mutated.
    working_df = df.copy(deep=False)

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
    # Validate metric
    # -----------------------------------------

    if plan.metric is None:
        raise ValueError("Analysis plan requires a metric.")

    if plan.metric not in working_df.columns:
        raise ValueError(f"Metric '{plan.metric}' does not exist in the dataset.")

    # -----------------------------------------
    # Perform analysis
    # -----------------------------------------

    result = analyze(
        df=working_df,
        group_by=plan.group_by,
        metric=plan.metric,
        aggregation=plan.aggregation,
        sort=plan.sort,
        sort_by=plan.sort_by,
        limit=plan.limit,
    )

    return result


def apply_time_granularity(
    df: pd.DataFrame,
    plan: AnalysisPlan,
) -> pd.DataFrame:

    # -----------------------------------------
    # No time analysis requested
    # -----------------------------------------

    if plan.time_granularity is None:
        return df

    # -----------------------------------------
    # Time analysis requires a time column
    # -----------------------------------------

    if plan.time_column is None:
        raise ValueError("Time analysis requires a time column.")

    time_column = plan.time_column

    # -----------------------------------------
    # Validate time column
    # -----------------------------------------

    if time_column not in df.columns:
        raise ValueError(f"Time column '{time_column}' does not exist in the dataset.")

    result = df.copy(deep=False)

    # -----------------------------------------
    # Convert selected column to datetime
    #
    # IMPORTANT:
    # We use the column selected by the planner.
    # There is NO hardcoded date column name.
    #
    # The parsed column is cached per dataset so
    # repeated time questions do not re-parse the
    # same strings on every request.
    # -----------------------------------------

    if not pd.api.types.is_datetime64_any_dtype(result[time_column]):
        from data_engine.dataset_manager import dataset_manager

        def _parse_time(source_df):
            return pd.to_datetime(
                source_df[time_column],
                errors="coerce",
                format="mixed",
            )

        try:
            parsed = dataset_manager.get_cached(
                f"time_parsed:{time_column}",
                _parse_time,
            )

            # Only reuse the cache when it aligns with the
            # frame being processed (filters may have
            # reduced it).
            if len(parsed) == len(result) and parsed.index.equals(result.index):
                result[time_column] = parsed
            else:
                result[time_column] = pd.to_datetime(
                    result[time_column],
                    errors="coerce",
                    format="mixed",
                )
        except RuntimeError:
            # No managed dataset (e.g. direct engine use in
            # tests): parse without caching.
            result[time_column] = pd.to_datetime(
                result[time_column],
                errors="coerce",
                format="mixed",
            )

    # -----------------------------------------
    # Remove rows where the selected time value
    # could not be converted.
    # -----------------------------------------

    result = result.dropna(subset=[time_column]).copy()

    if result.empty:
        raise ValueError(
            f"Time column '{time_column}' contains no valid datetime values."
        )

    # -----------------------------------------
    # Detect requested granularity
    # -----------------------------------------

    granularity = plan.time_granularity

    # -----------------------------------------
    # Day
    # -----------------------------------------

    if granularity == "day":
        result[time_column] = result[time_column].dt.floor("D")

    # -----------------------------------------
    # Week
    # -----------------------------------------

    elif granularity == "week":
        result[time_column] = result[time_column].dt.to_period("W").dt.start_time

    # -----------------------------------------
    # Month
    # -----------------------------------------

    elif granularity == "month":
        result[time_column] = result[time_column].dt.to_period("M").dt.start_time

    # -----------------------------------------
    # Quarter
    # -----------------------------------------

    elif granularity == "quarter":
        result[time_column] = result[time_column].dt.to_period("Q").dt.start_time

    # -----------------------------------------
    # Year
    # -----------------------------------------

    elif granularity == "year":
        result[time_column] = result[time_column].dt.to_period("Y").dt.start_time

    # -----------------------------------------
    # Unsupported granularity
    # -----------------------------------------

    else:
        raise ValueError(f"Unsupported time granularity: {granularity}")

    return result
