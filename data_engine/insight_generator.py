from __future__ import annotations
import math
from datetime import datetime
from decimal import Decimal
from typing import Any
import pandas as pd

from ai.insight_models import (
    CoverageEvidence,
    Insight,
    InsightEvidence,
    InsightResponse,
    MultiRowEvidence,
)
from data_engine.metadata import STRONG_TIME_TOKENS, tokenize_column_name


def build_insight_response(
    context: dict[str, Any],
) -> InsightResponse:
    """
    Convert deterministic insight context into a structured
    InsightResponse.

    This function does not perform any AI reasoning.
    It only converts already-verified facts into insights.
    """

    insights: list[Insight] = []

    # Labels time buckets at the plan's own granularity.
    granularity = context.get("time_granularity")

    # =====================================================
    # 1. HIGHEST
    # =====================================================

    highest = context.get("highest")

    if highest is not None and _has_meaningful_range(context):
        row = highest.get("row")
        value = highest.get("value")
        metric_column = context.get("metric_column")

        if isinstance(row, dict) and metric_column and value is not None:
            insights.append(
                Insight(
                    type="highest",
                    title=_build_highest_title(
                        row=row,
                        metric_column=metric_column,
                        granularity=granularity,
                    ),
                    description=_build_highest_description(
                        row=row,
                        value=value,
                        metric_column=metric_column,
                        granularity=granularity,
                    ),
                    evidence=InsightEvidence(
                        column=metric_column,
                        value=value,
                        row=row,
                    ),
                )
            )

    # =====================================================
    # 2. LOWEST
    # =====================================================

    lowest = context.get("lowest")

    if lowest is not None and _has_meaningful_range(context):
        row = lowest.get("row")
        value = lowest.get("value")
        metric_column = context.get("metric_column")

        if isinstance(row, dict) and metric_column and value is not None:
            insights.append(
                Insight(
                    type="lowest",
                    title=_build_lowest_title(
                        row=row,
                        metric_column=metric_column,
                        granularity=granularity,
                    ),
                    description=_build_lowest_description(
                        row=row,
                        value=value,
                        metric_column=metric_column,
                        granularity=granularity,
                    ),
                    evidence=InsightEvidence(
                        column=metric_column,
                        value=value,
                        row=row,
                    ),
                )
            )

    # =====================================================
    # 3. TREND
    # =====================================================

    trend = context.get("trend")

    if trend is not None:
        trend_insight = _build_trend_insight(
            context=context,
            trend=trend,
        )

        if trend_insight is not None:
            insights.append(trend_insight)

    # =====================================================
    # 4. DIFFERENCE
    # =====================================================

    difference = context.get("difference")

    if difference is not None:
        difference_insight = _build_difference_insight(
            context=context,
            difference=difference,
        )

        if difference_insight is not None:
            insights.append(difference_insight)

    # =====================================================
    # 5. COVERAGE
    # =====================================================

    date_coverage = context.get("date_coverage")

    if date_coverage is not None:
        coverage_insight = _build_coverage_insight(
            date_coverage=date_coverage,
        )

        if coverage_insight is not None:
            insights.append(coverage_insight)

    return InsightResponse(
        insights=insights,
    )


# =========================================================
# HIGHEST
# =========================================================


def _build_highest_title(
    row: dict[str, Any],
    metric_column: str,
    granularity: str | None = None,
) -> str:

    date_value = _get_display_dimension(row, granularity)

    if date_value:
        return f"{date_value} records peak {_humanize_metric(metric_column)}"

    return f"Highest {_humanize_metric(metric_column)} observed"


def _build_highest_description(
    row: dict[str, Any],
    value: int | float,
    metric_column: str,
    granularity: str | None = None,
) -> str:

    date_value = _get_display_dimension(row, granularity)

    metric_name = _humanize_metric(metric_column)

    formatted_value = _format_number(value)

    if date_value:
        return (
            f"{date_value} had the highest observed "
            f"{metric_name}, reaching {formatted_value}."
        )

    return f"The highest observed {metric_name} was {formatted_value}."


# =========================================================
# LOWEST
# =========================================================


def _build_lowest_title(
    row: dict[str, Any],
    metric_column: str,
    granularity: str | None = None,
) -> str:

    date_value = _get_display_dimension(row, granularity)

    if date_value:
        return f"{date_value} records lowest {_humanize_metric(metric_column)}"

    return f"Lowest {_humanize_metric(metric_column)} observed"


def _build_lowest_description(
    row: dict[str, Any],
    value: int | float,
    metric_column: str,
    granularity: str | None = None,
) -> str:

    date_value = _get_display_dimension(row, granularity)

    metric_name = _humanize_metric(metric_column)

    formatted_value = _format_number(value)

    if date_value:
        return (
            f"{date_value} had the lowest observed {metric_name}, at {formatted_value}."
        )

    return f"The lowest observed {metric_name} was {formatted_value}."


# =========================================================
# TREND
# =========================================================


def _build_trend_insight(
    context: dict[str, Any],
    trend: dict[str, Any],
) -> Insight | None:

    result_rows = context.get("result_rows")
    metric_column = context.get("metric_column")

    if not isinstance(result_rows, list):
        return None

    if not metric_column:
        return None

    if len(result_rows) < 2:
        return None

    direction = trend.get("direction")
    trend_type = trend.get("type")

    # -----------------------------------------------------
    # Determine supported trend rows
    # -----------------------------------------------------

    # Chronological rows from InsightEngine._add_trend when present;
    # NaN is not None, so it has to be filtered explicitly.
    source_rows = trend.get("rows")
    if not isinstance(source_rows, list):
        source_rows = result_rows

    rows = [
        row
        for row in source_rows
        if isinstance(row, dict) and pd.notna(row.get(metric_column))
    ]

    if len(rows) < 2:
        return None

    # -----------------------------------------------------
    # Stable
    # -----------------------------------------------------

    if trend_type == "stable":
        return Insight(
            type="trend",
            title="Values remained stable",
            description=(
                "The observed values remained stable across the available periods."
            ),
            evidence=MultiRowEvidence(
                rows=rows,
            ),
        )

    # -----------------------------------------------------
    # Increasing
    # -----------------------------------------------------

    if direction == "increasing":
        return Insight(
            type="trend",
            title="Values increased across the observed periods",
            description=(
                "The metric increased consistently across the observed periods."
            ),
            evidence=MultiRowEvidence(
                rows=rows,
            ),
        )

    # -----------------------------------------------------
    # Decreasing
    # -----------------------------------------------------

    if direction == "decreasing":
        return Insight(
            type="trend",
            title="Values decreased across the observed periods",
            description=(
                "The metric decreased consistently across the observed periods."
            ),
            evidence=MultiRowEvidence(
                rows=rows,
            ),
        )

    # -----------------------------------------------------
    # Mixed
    # -----------------------------------------------------

    if trend_type == "mixed":
        return Insight(
            type="trend",
            title="Metric shows a mixed trend",
            description=(
                "The metric moved up and down across "
                "the observed periods, so the overall "
                "pattern is mixed."
            ),
            evidence=MultiRowEvidence(
                rows=rows,
            ),
        )

    return None


# =========================================================
# DIFFERENCE
# =========================================================


def _build_difference_insight(
    context: dict[str, Any],
    difference: int | float,
) -> Insight | None:

    highest = context.get("highest")
    lowest = context.get("lowest")

    if not highest or not lowest:
        return None

    highest_row = highest.get("row")
    lowest_row = lowest.get("row")

    if not isinstance(highest_row, dict):
        return None

    if not isinstance(lowest_row, dict):
        return None

    calculated_difference = abs(
        float(highest.get("value")) - float(lowest.get("value"))
    )
    if abs(calculated_difference - float(difference)) > 1e-6:
        return None

    if abs(float(difference)) <= 1e-6:
        return None

    # -----------------------------------------------------
    # Safety check
    #
    # The context itself is authoritative.
    # We only generate the insight if the values agree.
    # -----------------------------------------------------

    if abs(calculated_difference - float(difference)) > 1e-6:
        return None

    formatted_difference = _format_number(difference)

    highest_date = _get_display_dimension(highest_row, context.get("time_granularity"))
    lowest_date = _get_display_dimension(lowest_row, context.get("time_granularity"))

    if highest_date and lowest_date:
        description = (
            f"The difference between the highest "
            f"({highest_date}) and lowest "
            f"({lowest_date}) observed values is "
            f"{formatted_difference}."
        )
    else:
        description = (
            f"The difference between the highest "
            f"and lowest observed values is "
            f"{formatted_difference}."
        )

    return Insight(
        type="difference",
        # Neutral: no threshold is computed that would justify "large".
        title="Gap between highest and lowest values",
        description=description,
        evidence=MultiRowEvidence(
            rows=[
                lowest_row,
                highest_row,
            ]
        ),
    )


# =========================================================
# COVERAGE
# =========================================================


def _build_coverage_insight(
    date_coverage: dict[str, Any],
) -> Insight | None:

    frequency = date_coverage.get("frequency")
    observed = date_coverage.get("observed_periods")
    expected = date_coverage.get("expected_periods")
    missing = date_coverage.get("missing_periods", [])
    is_continuous = date_coverage.get("is_continuous")

    if frequency == "unknown":
        return None

    if observed is None or expected is None:
        return None

    if is_continuous is True:
        return None

    if not missing:
        return None

    frequency_name = str(frequency)

    description = (
        f"Only {observed} of the {expected} expected "
        f"{frequency_name} periods are present, with "
        f"{len(missing)} periods missing."
    )

    evidence = CoverageEvidence(
        date_column=date_coverage.get("date_column"),
        frequency=frequency,
        min_date=date_coverage.get("min_date"),
        max_date=date_coverage.get("max_date"),
        observed_periods=observed,
        expected_periods=expected,
        missing_periods=missing,
        is_continuous=is_continuous,
    )

    return Insight(
        type="coverage",
        title="Data coverage is incomplete",
        description=description,
        evidence=evidence,
    )


# =========================================================
# HELPERS
# =========================================================


def _get_display_dimension(
    row: dict[str, Any],
    granularity: str | None = None,
) -> str | None:

    value = None

    # Dataset-agnostic time-column lookup: reuse the same
    # STRONG_TIME_TOKENS check data_engine/metadata.py already uses
    # to identify time columns, instead of hardcoding "Date"/"date".
    # Catches "OrderDate", "Timestamp", "Purchase_Date", etc. too.
    for key in row:
        if STRONG_TIME_TOKENS & tokenize_column_name(key):
            value = row[key]
            break

    if value is None:
        for key, item in row.items():
            if isinstance(item, str):
                return str(item)

        return None

    try:
        parsed = pd.to_datetime(value)

    except (TypeError, ValueError):
        return str(value)

    # Month-only labels would make two daily buckets in the same
    # month indistinguishable ("March 2024" peak and lowest).
    if granularity == "day":
        return parsed.strftime("%d %B %Y")
    if granularity == "week":
        return f"Week of {parsed.strftime('%d %B %Y')}"
    if granularity == "quarter":
        return f"Q{parsed.quarter} {parsed.year}"
    if granularity == "year":
        return str(parsed.year)

    return parsed.strftime("%B %Y")


def _humanize_metric(
    metric_column: str,
) -> str:

    metric = metric_column

    if metric.startswith("sum_"):
        metric = metric[4:]

    metric = metric.replace("_", " ")

    return metric


def _format_number(
    value: int | float,
) -> str:
    """
    Display text only - evidence keeps the exact computed value.

    Non-integers are shown with at most two decimals (trailing zeros
    dropped), which also hides binary float noise such as
    38507381.92000001. Magnitudes below 0.01 would round to 0 at two
    decimals, so they keep two significant digits instead, still in
    plain decimal notation.
    """

    number = float(value)

    if not math.isfinite(number):
        return str(value)

    if number.is_integer():
        return f"{int(number):,}"

    if abs(number) < 0.01:
        # Round to 2 significant digits, then print in fixed-point
        # notation: "{:.2g}" alone gives "1e-07" for 0.0000001.
        return format(Decimal(f"{number:.2g}"), "f")

    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _has_meaningful_range(
    context: dict[str, Any],
) -> bool:

    highest = context.get("highest")
    lowest = context.get("lowest")

    if highest and lowest:
        highest_value = highest.get("value")
        lowest_value = lowest.get("value")

        if highest_value is None or lowest_value is None:
            return False

        return abs(float(highest_value) - float(lowest_value)) > 1e-6

    # A limited result keeps only one extreme (see InsightEngine.
    # _add_extremes); the spread of the returned rows still decides
    # whether that extreme is worth stating.
    value_range = context.get("value_range")

    if value_range is None or not (highest or lowest):
        return False

    return abs(float(value_range)) > 1e-6
