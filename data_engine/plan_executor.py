import pandas as pd

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
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
    # Parsed directly from the `df` this function was given -
    # not via dataset_manager's global "active dataset" cache,
    # which could silently resolve to a DIFFERENT dataset than
    # the one actually being analyzed once multiple datasets
    # can be active in the registry at once.
    # -----------------------------------------

    if not pd.api.types.is_datetime64_any_dtype(result[time_column]):
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


def execute_plan_for_dataset(
    dataset: Dataset,
    plan: AnalysisPlan,
) -> "ExecutionResult":
    """
    Execute an already-validated AnalysisPlan against a specific
    Dataset, using whichever ExecutionEngine matches that Dataset's
    own storage backend.

    Returns an ExecutionResult (data_engine.execution.result) - the
    engine-neutral columns/rows/row_count/truncated boundary type, not
    a raw pandas DataFrame.

    This is the storage-aware entry point: a DuckDB-backed dataset no
    longer needs a full storage.to_dataframe() materialization just to
    apply raw filters (=, !=, >, >=, <, <=) or time-bucketing (day,
    week, month, quarter, year) - those operations are pushed down
    natively via DuckDBExecutionEngine -> execute_plan_duckdb(), with
    only the final, already filtered/aggregated result ever becoming a
    DataFrame.

    apply_filter() / apply_time_granularity() / execute_plan() above
    are untouched and keep serving as the fallback pipeline for
    Pandas-backed datasets (via PandasExecutionEngine) exactly as
    before - no filtering, grouping, or aggregation logic is
    duplicated here.

    `dataset` must always be the specific Dataset instance to execute
    against - this function never resolves a "current" dataset through
    a global dataset manager, so multiple datasets can be active at
    once without any risk of cross-dataset crosstalk.

    `plan` must already have passed data_engine.plan_validator.
    validate_plan() - this function performs no plan validation of its
    own, matching the ExecutionEngine contract's `validated_plan`.
    """

    # Imported lazily: data_engine.execution imports execute_plan from
    # this module (for its Pandas adapter), so importing the execution
    # package back at module load time would create a circular import.
    from data_engine.execution import select_engine_for

    engine = select_engine_for(dataset)

    return engine.execute(dataset, plan)
