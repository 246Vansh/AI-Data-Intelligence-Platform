"""DuckDB-native analytical execution for AnalysisPlan.

Mirrors the semantics of data_engine/plan_executor.py and
data_engine/query_engine.py (filters, time granularity, group-by /
aggregation, sort, limit) but performs every analytical operation -
filtering, time bucketing, grouping, aggregating, sorting, limiting -
as SQL executed directly by the DuckDB engine, instead of loading the
dataset into a pandas DataFrame and running the existing pandas-based
query logic on it.

This is an ADDITIONAL, isolated execution path for DuckDBStorage-backed
datasets. It does not modify, replace, or get called by the existing
pandas execute_plan()/analyze() path - both remain fully functional and
independent. A pandas DataFrame is produced only once, at the very end,
from the already filtered/aggregated/sorted/limited DuckDB result -
the same "compatibility boundary" pattern as DatasetStorage.to_dataframe(),
not a full-dataset materialization used for computation.
"""

from __future__ import annotations

import pandas as pd

from data_engine.analysis_plan import AnalysisPlan
from data_engine.storage.duckdb_storage import DuckDBStorage

ALLOWED_AGGREGATIONS = {
    "sum": "SUM",
    "mean": "AVG",
    "median": "MEDIAN",
    "min": "MIN",
    "max": "MAX",
    "count": "COUNT",
}

ALLOWED_OPERATORS = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}

ALLOWED_SORT_BY = {"metric", "time"}

ALLOWED_TIME_GRANULARITIES = {"day", "week", "month", "quarter", "year"}

# Safety net for the DuckDB analytical execution path only: applied
# solely when a plan reaches here with no explicit limit (plan.limit
# is None), so a high-cardinality GROUP BY can't produce an unbounded
# result that fetchdf() would then materialize into Pandas in full.
# An explicit plan.limit is always honored as-is and never overridden.
DEFAULT_MAX_RESULT_ROWS = 10_000


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def execute_plan_duckdb(
    storage: DuckDBStorage,
    plan: AnalysisPlan,
) -> pd.DataFrame:
    """
    Execute an AnalysisPlan against a DuckDBStorage-backed dataset.

    Filtering, time-bucketing, grouping, aggregation, sorting, and
    limiting are all expressed as SQL and executed by the DuckDB engine
    itself, directly against the dataset's own table - never by pulling
    the raw rows into pandas first and reapplying the pandas-based
    query logic on top of them.
    """

    if not isinstance(storage, DuckDBStorage):
        raise TypeError("execute_plan_duckdb requires a DuckDBStorage instance.")

    dataset_columns = set(storage.column_names())
    params: list = []

    # -----------------------------------------
    # Filters
    # -----------------------------------------

    where_clauses = []

    for condition in plan.filters:
        if condition.column not in dataset_columns:
            raise ValueError(f"Unknown column: {condition.column}")

        if condition.operator not in ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported operator: {condition.operator}")

        where_clauses.append(
            f"{_quote_identifier(condition.column)} "
            f"{ALLOWED_OPERATORS[condition.operator]} ?"
        )
        params.append(condition.value)

    working_sql = f"SELECT * FROM {_quote_identifier(storage.table_name)}"

    if where_clauses:
        working_sql += " WHERE " + " AND ".join(where_clauses)

    # -----------------------------------------
    # Time granularity
    # -----------------------------------------

    time_bucket_column = None

    if plan.time_granularity is not None:
        if plan.time_column is None:
            raise ValueError("Time analysis requires a time column.")

        if plan.time_column not in dataset_columns:
            raise ValueError(
                f"Time column '{plan.time_column}' does not exist in the dataset."
            )

        if plan.time_granularity not in ALLOWED_TIME_GRANULARITIES:
            raise ValueError(f"Unsupported time granularity: {plan.time_granularity}")

        time_bucket_column = plan.time_column
        quoted_time_column = _quote_identifier(plan.time_column)

        bucketed_expr = (
            f"date_trunc('{plan.time_granularity}', "
            f"TRY_CAST({quoted_time_column} AS TIMESTAMP))"
        )

        # Rebuild the time column in place as its bucketed value, and
        # drop rows whose value could not be parsed as a timestamp -
        # mirroring the pandas path's coerce + dropna(subset=[...]).
        working_sql = (
            f"SELECT * EXCLUDE ({quoted_time_column}), "
            f"{bucketed_expr} AS {quoted_time_column} "
            f"FROM ({working_sql})"
        )
        working_sql = (
            f"SELECT * FROM ({working_sql}) WHERE {quoted_time_column} IS NOT NULL"
        )

    # -----------------------------------------
    # Validate metric / aggregation / sort
    # -----------------------------------------

    if plan.metric is None:
        raise ValueError("Analysis plan requires a metric.")

    if plan.metric not in dataset_columns:
        raise ValueError(f"Metric '{plan.metric}' does not exist in the dataset.")

    if plan.aggregation not in ALLOWED_AGGREGATIONS:
        raise ValueError(f"Unsupported aggregation: {plan.aggregation}")

    sort = str(plan.sort or "desc").lower()
    if sort not in {"asc", "desc"}:
        raise ValueError(f"Unsupported sort direction: {plan.sort}")

    sort_by = plan.sort_by or "metric"
    if sort_by not in ALLOWED_SORT_BY:
        raise ValueError(f"Unsupported sort field: {plan.sort_by}")

    if plan.limit is not None:
        if not isinstance(plan.limit, int):
            raise ValueError("Limit must be an integer.")
        if plan.limit <= 0:
            raise ValueError("Limit must be greater than zero.")

    group_by = list(plan.group_by)

    for column in group_by:
        if column not in dataset_columns:
            raise ValueError(f"Unknown columns: [{column}]")

    agg_function = ALLOWED_AGGREGATIONS[plan.aggregation]
    metric_column = f"{plan.aggregation}_{plan.metric}"
    metric_expr = (
        f"{agg_function}({_quote_identifier(plan.metric)}) "
        f"AS {_quote_identifier(metric_column)}"
    )

    # =========================================
    # GLOBAL AGGREGATION
    # =========================================

    if not group_by:
        query = f"SELECT {metric_expr} FROM ({working_sql})"
        result = storage.connection.execute(query, params).fetchdf()
        return result.reset_index(drop=True)

    # =========================================
    # GROUPED AGGREGATION
    # =========================================

    select_columns = ", ".join(_quote_identifier(column) for column in group_by)
    direction = "ASC" if sort == "asc" else "DESC"

    order_clause = ""
    if sort_by == "metric":
        order_clause = f"ORDER BY {_quote_identifier(metric_column)} {direction}"

    elif sort_by == "time":
        if time_bucket_column is None or time_bucket_column not in group_by:
            raise ValueError("Time sorting requires a datetime group-by column.")
        order_clause = f"ORDER BY {_quote_identifier(time_bucket_column)} {direction}"

    effective_limit = plan.limit if plan.limit is not None else DEFAULT_MAX_RESULT_ROWS
    limit_clause = f"LIMIT {int(effective_limit)}"

    query = (
        f"SELECT {select_columns}, {metric_expr} "
        f"FROM ({working_sql}) "
        f"GROUP BY {select_columns} "
        f"{order_clause} "
        f"{limit_clause}"
    ).strip()

    result = storage.connection.execute(query, params).fetchdf()
    return result.reset_index(drop=True)
