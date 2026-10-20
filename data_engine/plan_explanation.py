"""
Deterministic "How this was calculated" explanation for an executed
AnalysisPlan.

Built only from the canonical plan the route actually executed, the
planner that produced it, and the route's execution metadata - never
from the question text or an LLM. Every sentence states what the
execution engines are verified to do:

- filters are ANDed and compared exactly as written
  (duckdb_query_engine.execute_plan_duckdb / plan_executor.apply_filter);
- with a time granularity, rows whose time value is empty or cannot be
  parsed as a date are dropped before grouping, and weeks start on
  Monday (DuckDB date_trunc('week') / pandas to_period("W").start_time);
- COUNT(column) counts non-null values of that column, not rows;
- the default DEFAULT_MAX_RESULT_ROWS cap applies only to grouped
  results without an explicit limit.

Column names and filter values are returned verbatim inside plain
strings; rendering them as text (not markup) is the caller's job.
"""

from __future__ import annotations

import json
from typing import Any

from data_engine.analysis_plan import AnalysisPlan


_AGGREGATION_PHRASES = {
    "sum": ("Sum of {metric}", "sum"),
    "mean": ("Average (mean) of {metric}", "average"),
    "median": ("Median of {metric}", "median"),
    "min": ("Minimum of {metric}", "minimum"),
    "max": ("Maximum of {metric}", "maximum"),
    # COUNT(column): NULLs in that column are not counted.
    "count": ("Number of non-empty {metric} values", "count"),
}

_OPERATOR_PHRASES = {
    "=": "equals",
    "!=": "does not equal",
    ">": "is greater than",
    ">=": "is greater than or equal to",
    "<": "is less than",
    "<=": "is less than or equal to",
}

_GRANULARITY_PHRASES = {
    "day": ("day", "days"),
    "week": ("week", "weeks starting on Monday"),
    "month": ("month", "months"),
    "quarter": ("quarter", "quarters"),
    "year": ("year", "years"),
}

_PLANNER_LABELS = {
    "fast": "rule-based",
    "ai": "ai",
    "follow_up": "follow-up",
}


def explain_plan(
    plan: AnalysisPlan,
    *,
    planner_type: str | None,
    row_limit: int | None,
    row_limit_reached: bool,
    follow_up_change: str | None = None,
) -> dict[str, Any]:
    """
    Return ``{"interpreted_by", "steps", "limitations"}`` for an
    executed plan. Raises ValueError for anything it cannot describe
    accurately (unknown aggregation/operator/granularity) rather than
    guessing - the route treats the explanation as optional.
    """

    if plan.metric is None:
        raise ValueError("Cannot explain a plan without a metric.")

    if plan.aggregation not in _AGGREGATION_PHRASES:
        raise ValueError(f"Cannot explain aggregation: {plan.aggregation!r}")

    if (
        plan.time_granularity is not None
        and plan.time_granularity not in _GRANULARITY_PHRASES
    ):
        raise ValueError(f"Cannot explain time granularity: {plan.time_granularity!r}")

    calculation, result_noun = _AGGREGATION_PHRASES[plan.aggregation]
    calculation = calculation.format(metric=plan.metric)

    group_by = list(plan.group_by)
    time_bucketed = (
        plan.time_granularity is not None and plan.time_column in group_by
    )

    steps: list[str] = []
    limitations: list[str] = []

    # The one edit ai.follow_up applied to the previous plan; every
    # step below still describes the full plan that actually ran.
    if follow_up_change:
        steps.append(f"Follow-up to the previous analysis: {follow_up_change}.")

    # -----------------------------------------
    # What was calculated, per what
    # -----------------------------------------

    if not group_by:
        steps.append(f"{calculation}, calculated as a single value (no grouping).")
    else:
        labels = [_group_label(column, plan) for column in group_by]

        if len(labels) == 1:
            steps.append(f"{calculation} for each {labels[0]}.")
        else:
            steps.append(
                f"{calculation} for each combination of "
                f"{_join(labels)}."
            )

    # -----------------------------------------
    # Filters
    # -----------------------------------------

    if not plan.filters:
        steps.append("No filters were applied.")
    elif any(condition.operator == "!=" for condition in plan.filters):
        # Engines disagree on empty values for "!=": DuckDB's
        # `column != ?` drops NULLs, the pandas executor keeps NaN rows.
        # State the condition as written, without claiming either.
        expressions = [_filter_expression(condition) for condition in plan.filters]

        if len(expressions) == 1:
            steps.append(f"Filter condition: {expressions[0]}.")
        else:
            steps.append(
                "Filter conditions (all must hold): "
                + "; ".join(expressions)
                + "."
            )
    else:
        conditions = [_describe_filter(condition) for condition in plan.filters]

        if len(conditions) == 1:
            steps.append(f"Only rows where {conditions[0]} were included.")
        else:
            steps.append(
                "Only rows matching all of these conditions were included: "
                + "; ".join(conditions)
                + "."
            )

    # -----------------------------------------
    # Time bucketing
    # -----------------------------------------

    if plan.time_granularity is not None and plan.time_column is not None:
        _, plural = _GRANULARITY_PHRASES[plan.time_granularity]

        if time_bucketed:
            steps.append(f"Dates in {plan.time_column} were grouped into {plural}.")

        # Applies whether or not the time column is grouped on: both
        # engines rebuild and null-filter it whenever a granularity is set.
        limitations.append(
            f"Rows where {plan.time_column} is empty or could not be read "
            "as a date were excluded."
        )

    # -----------------------------------------
    # Sort and limit (grouped results only)
    # -----------------------------------------

    if group_by:
        descending = str(plan.sort or "desc").lower() != "asc"
        sort_by = plan.sort_by or "metric"

        if sort_by == "time" and plan.time_column is not None:
            steps.append(
                f"Sorted by {plan.time_column}, "
                f"{'latest' if descending else 'earliest'} first."
            )
        else:
            steps.append(
                f"Sorted by the calculated {result_noun}, "
                f"{'highest' if descending else 'lowest'} first."
            )

        # "Limited to", not "Showing": fewer groups than the limit may exist.
        if plan.limit is not None:
            if sort_by == "time":
                steps.append(f"Limited to the first {plan.limit:,} groups in this order.")
            elif descending:
                steps.append(f"Limited to the top {plan.limit:,} groups.")
            else:
                steps.append(f"Limited to the bottom {plan.limit:,} groups.")

        if row_limit_reached and row_limit is not None:
            # The engines do not report true truncation; the route only
            # knows the result filled its limit, so "may" is all it can say.
            if plan.limit is not None:
                limitations.append(
                    f"The result reached the requested limit of {row_limit:,} "
                    "groups, so more groups may exist."
                )
            else:
                limitations.append(
                    f"The result reached the default cap of {row_limit:,} "
                    "groups, so more groups may exist."
                )

    return {
        "interpreted_by": _PLANNER_LABELS.get(planner_type, "unknown"),
        "steps": steps,
        "limitations": limitations,
    }


def _group_label(column: str, plan: AnalysisPlan) -> str:
    if plan.time_granularity is not None and column == plan.time_column:
        singular, _ = _GRANULARITY_PHRASES[plan.time_granularity]
        return f"{singular} of {column}"

    return column


def _describe_filter(condition) -> str:
    if condition.operator not in _OPERATOR_PHRASES:
        raise ValueError(f"Cannot explain filter operator: {condition.operator!r}")

    return (
        f"{condition.column} {_OPERATOR_PHRASES[condition.operator]} "
        f"{_format_value(condition.value)}"
    )


def _filter_expression(condition) -> str:
    if condition.operator not in _OPERATOR_PHRASES:
        raise ValueError(f"Cannot explain filter operator: {condition.operator!r}")

    return f"{condition.column} {condition.operator} {_format_value(condition.value)}"


def _format_value(value: Any) -> str:
    # JSON literal form keeps the exact value visible and unambiguous:
    # strings stay quoted (inner quotes escaped), numbers/booleans as-is.
    # It is still plain text - nothing here is markup.
    return json.dumps(value, ensure_ascii=False, default=str)


def _join(items: list[str]) -> str:
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"

    return ", ".join(items[:-1]) + f", and {items[-1]}"
