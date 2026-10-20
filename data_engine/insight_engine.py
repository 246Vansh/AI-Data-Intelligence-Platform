from __future__ import annotations

from typing import Any

import pandas as pd


# AnalysisPlan.time_granularity -> pandas Period frequency. A plan with
# no granularity keeps the original month-level coverage.
_PERIOD_FREQUENCIES = {
    "day": "D",
    "week": "W",
    "month": "M",
    "quarter": "Q",
    "year": "Y",
}


class InsightEngine:
    """
    Deterministic analytics engine.

    This class calculates analytical facts from an already
    executed analysis result. It does not use an LLM.

    ``row_limit_reached`` marks a result that may have been cut off by
    the plan's LIMIT (or the DEFAULT_MAX_RESULT_ROWS safety cap): only
    facts that still hold for the whole grouped result are computed
    from it - see _add_extremes/_add_trend/_add_date_coverage.
    """

    def __init__(
        self,
        result: pd.DataFrame,
        metric_column: str,
        group_by: list[str],
        row_limit_reached: bool = False,
        sort: str | None = "desc",
        sort_by: str | None = "metric",
        time_granularity: str | None = None,
    ):

        self.result = result
        self.metric_column = metric_column
        self.group_by = group_by
        self.row_limit_reached = row_limit_reached
        self.sort = str(sort or "desc").lower()
        self.sort_by = sort_by or "metric"
        self.time_granularity = time_granularity

    # =====================================================
    # Public API
    # =====================================================

    def generate(self) -> dict[str, Any]:

        context = {
            "row_count": len(self.result),
            "metric_column": self.metric_column,
            "group_by": self.group_by,
            "row_limit_reached": self.row_limit_reached,
            "time_granularity": self.time_granularity,
        }

        if self.result.empty:
            return context

        if self.metric_column not in self.result.columns:
            return context

        self._add_result_rows(context)
        self._add_extremes(context)
        self._add_difference(context)

        date_column, dates = self._find_date_column()

        self._add_trend(context, date_column, dates)
        self._add_date_coverage(context, date_column, dates)

        return context

    # =====================================================
    # Result rows
    # =====================================================

    def _add_result_rows(
        self,
        context: dict[str, Any],
    ) -> None:

        context["result_rows"] = self.result.to_dict(orient="records")

    # =====================================================
    # Highest / Lowest
    # =====================================================

    def _add_extremes(
        self,
        context: dict[str, Any],
    ) -> None:

        metric = pd.to_numeric(
            self.result[self.metric_column],
            errors="coerce",
        )

        valid_metric = metric.dropna()

        if valid_metric.empty:
            return

        max_index = valid_metric.idxmax()
        min_index = valid_metric.idxmin()

        highest_value = float(
            self.result.loc[
                max_index,
                self.metric_column,
            ]
        )

        lowest_value = float(
            self.result.loc[
                min_index,
                self.metric_column,
            ]
        )

        # Spread across the returned rows only - used to decide whether
        # an extreme is worth reporting at all, never as a claim.
        context["value_range"] = highest_value - lowest_value

        # A limited result sorted by the metric still contains the
        # global extreme at its sorted end (DuckDB orders NULLs last
        # either way), but not the opposite one; any other ordering
        # guarantees neither.
        keep_highest = not self.row_limit_reached or (
            self.sort_by == "metric" and self.sort == "desc"
        )
        keep_lowest = not self.row_limit_reached or (
            self.sort_by == "metric" and self.sort == "asc"
        )

        if keep_highest:
            context["highest"] = {
                "value": highest_value,
                "row": self.result.loc[max_index].to_dict(),
            }

        if keep_lowest:
            context["lowest"] = {
                "value": lowest_value,
                "row": self.result.loc[min_index].to_dict(),
            }

    # =====================================================
    # Difference
    # =====================================================

    def _add_difference(
        self,
        context: dict[str, Any],
    ) -> None:

        if "highest" not in context or "lowest" not in context:
            return

        highest = context["highest"]["value"]
        lowest = context["lowest"]["value"]

        context["difference"] = highest - lowest

    # =====================================================
    # Trend
    # =====================================================

    def _add_trend(
        self,
        context: dict[str, Any],
        date_column: str | None,
        dates: pd.Series | None,
    ) -> None:

        # A trend is only meaningful along time. Row order alone is
        # not time order (results default to metric-descending), a
        # categorical grouping has no "periods", several group_by
        # columns interleave separate series, and a limited result may
        # be missing periods in between - none of those gets a trend.
        if (
            date_column is None
            or len(self.group_by) != 1
            or self.row_limit_reached
        ):
            return

        if len(self.result) < 2:
            context["trend"] = {
                "type": "insufficient_data",
                "direction": None,
            }
            return

        ordered = self.result.loc[dates.sort_values(kind="stable").index]

        metric = pd.to_numeric(
            ordered[self.metric_column],
            errors="coerce",
        )

        valid = metric.dropna()

        if len(valid) < 2:
            context["trend"] = {
                "type": "insufficient_data",
                "direction": None,
            }
            return

        values = valid.tolist()

        changes = [current - previous for previous, current in zip(values, values[1:])]

        has_increase = any(change > 0 for change in changes)

        has_decrease = any(change < 0 for change in changes)

        if not has_increase and not has_decrease:
            direction = "stable"

        elif has_increase and not has_decrease:
            direction = "increasing"

        elif has_decrease and not has_increase:
            direction = "decreasing"

        else:
            direction = "mixed"

        context["trend"] = {
            "type": (
                "stable"
                if direction == "stable"
                else "monotonic"
                if direction
                in {
                    "increasing",
                    "decreasing",
                }
                else "mixed"
            ),
            "direction": direction,
            "date_column": date_column,
            "first_value": float(values[0]),
            "last_value": float(values[-1]),
            "change": float(values[-1] - values[0]),
            # Evidence rows in chronological order, metric present.
            "rows": ordered.loc[valid.index].to_dict(orient="records"),
        }

    # =====================================================
    # Date coverage
    # =====================================================

    def _find_date_column(self) -> tuple[str | None, pd.Series | None]:
        """
        The first group_by column whose every value parses as a date,
        with its parsed values - shared by _add_trend and
        _add_date_coverage. Numeric/boolean columns are never treated
        as dates: pandas would otherwise read integers such as years
        or IDs as nanosecond epoch timestamps.
        """

        if not self.group_by:
            return None, None

        # Bounded prefix size used to cheaply reject an obviously
        # non-date column (e.g. thousands of categorical strings)
        # before paying for a full-column parse. See the sampling
        # short-circuit below for why this stays exact, not a
        # heuristic.
        SAMPLE_SIZE = 20

        for column in self.group_by:
            if column not in self.result.columns:
                continue

            series = self.result[column]

            # -----------------------------------------
            # Fast path: already a datetime dtype.
            #
            # pd.to_datetime() on a series that is already
            # datetime64 is a no-op (existing values, including
            # any NaT, pass through unchanged) - so the column can
            # be treated as parsed directly, with no reparsing
            # cost, and the exact same notna().all() acceptance
            # check below still applies.
            # -----------------------------------------

            if pd.api.types.is_datetime64_any_dtype(series):
                parsed = series

            elif pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(
                series
            ):
                continue

            else:
                # -----------------------------------------
                # Exact short-circuit via a small prefix sample.
                #
                # The acceptance condition below requires EVERY
                # value in the column to parse successfully, so a
                # single failure (including a null, which coerces
                # to NaT and fails notna()) anywhere in the sample
                # already proves the full column would fail too -
                # reject immediately without a full format="mixed"
                # scan over a purely categorical column. If the
                # sample fully parses, fall through to the existing
                # full-column parse to confirm the rest of the
                # column (e.g. a null appearing after the sampled
                # prefix).
                # -----------------------------------------

                sample = series.head(SAMPLE_SIZE)

                sample_parsed = pd.to_datetime(
                    sample,
                    errors="coerce",
                    format="mixed",
                )

                if not sample_parsed.notna().all():
                    continue

                parsed = pd.to_datetime(
                    series,
                    errors="coerce",
                    format="mixed",
                )

            if parsed.notna().all():
                return column, parsed

        return None, None

    def _add_date_coverage(
        self,
        context: dict[str, Any],
        date_column: str | None,
        dates: pd.Series | None,
    ) -> None:

        # Missing periods in a limited result are usually just rows
        # past the LIMIT, not gaps in the data.
        if date_column is None or self.row_limit_reached:
            return

        if dates.isna().any():
            return

        dates = dates.sort_values()

        frequency_name = (
            self.time_granularity
            if self.time_granularity in _PERIOD_FREQUENCIES
            else "month"
        )
        period_freq = _PERIOD_FREQUENCIES[frequency_name]

        unique_periods = (
            dates.dt.to_period(period_freq).drop_duplicates().sort_values()
        )

        if len(unique_periods) == 1:
            frequency = "unknown"
            expected_periods = 1
            missing_periods = []

        else:
            expected_range = pd.period_range(
                start=unique_periods.min(),
                end=unique_periods.max(),
                freq=period_freq,
            )

            expected_periods = len(expected_range)

            observed_periods = set(unique_periods)

            missing_periods = [
                str(period)
                for period in expected_range
                if period not in observed_periods
            ]

            frequency = frequency_name

        context["date_coverage"] = {
            "date_column": date_column,
            "frequency": frequency,
            "min_date": dates.min().isoformat(),
            "max_date": dates.max().isoformat(),
            # Distinct periods, not rows: a date x category grouping
            # repeats each period once per category.
            "observed_periods": len(unique_periods),
            "expected_periods": expected_periods,
            "missing_periods": missing_periods,
            "is_continuous": (
                len(missing_periods) == 0 if frequency != "unknown" else None
            ),
        }


def build_deterministic_insights(
    result: pd.DataFrame,
    metric_column: str,
    group_by: list[str],
    row_limit_reached: bool = False,
    sort: str | None = "desc",
    sort_by: str | None = "metric",
    time_granularity: str | None = None,
) -> dict[str, Any]:

    engine = InsightEngine(
        result=result,
        metric_column=metric_column,
        group_by=group_by,
        row_limit_reached=row_limit_reached,
        sort=sort,
        sort_by=sort_by,
        time_granularity=time_granularity,
    )

    return engine.generate()
