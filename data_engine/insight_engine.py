from __future__ import annotations

from typing import Any

import pandas as pd


class InsightEngine:
    """
    Deterministic analytics engine.

    This class calculates analytical facts from an already
    executed analysis result. It does not use an LLM.
    """

    def __init__(
        self,
        result: pd.DataFrame,
        metric_column: str,
        group_by: list[str],
    ):

        self.result = result
        self.metric_column = metric_column
        self.group_by = group_by

    # =====================================================
    # Public API
    # =====================================================

    def generate(self) -> dict[str, Any]:

        context = {
            "row_count": len(self.result),
            "metric_column": self.metric_column,
            "group_by": self.group_by,
        }

        if self.result.empty:
            return context

        if self.metric_column not in self.result.columns:
            return context

        self._add_result_rows(context)
        self._add_extremes(context)
        self._add_difference(context)
        self._add_trend(context)
        self._add_date_coverage(context)

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

        context["highest"] = {
            "value": highest_value,
            "row": self.result.loc[max_index].to_dict(),
        }

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
    ) -> None:

        if len(self.result) < 2:
            context["trend"] = {
                "type": "insufficient_data",
                "direction": None,
            }
            return

        metric = pd.to_numeric(
            self.result[self.metric_column],
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
            "first_value": float(values[0]),
            "last_value": float(values[-1]),
            "change": float(values[-1] - values[0]),
        }

    # =====================================================
    # Date coverage
    # =====================================================

    def _add_date_coverage(
        self,
        context: dict[str, Any],
    ) -> None:

        if not self.group_by:
            return

        # Bounded prefix size used to cheaply reject an obviously
        # non-date column (e.g. thousands of categorical strings)
        # before paying for a full-column parse. See the sampling
        # short-circuit below for why this stays exact, not a
        # heuristic.
        SAMPLE_SIZE = 20

        date_column = None

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
                date_column = column
                dates = parsed
                break

        if date_column is None:
            return

        if dates.isna().any():
            return

        dates = dates.sort_values()

        if len(dates) == 1:
            frequency = "unknown"
            expected_periods = 1
            missing_periods = []

        else:
            month_periods = dates.dt.to_period("M")

            unique_periods = month_periods.drop_duplicates().sort_values()

            expected_range = pd.period_range(
                start=unique_periods.min(),
                end=unique_periods.max(),
                freq="M",
            )

            expected_periods = len(expected_range)

            observed_periods = set(unique_periods)

            missing_periods = [
                str(period)
                for period in expected_range
                if period not in observed_periods
            ]

            frequency = "month"

        context["date_coverage"] = {
            "date_column": date_column,
            "frequency": frequency,
            "min_date": dates.min().isoformat(),
            "max_date": dates.max().isoformat(),
            "observed_periods": len(dates),
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
) -> dict[str, Any]:

    engine = InsightEngine(
        result=result,
        metric_column=metric_column,
        group_by=group_by,
    )

    return engine.generate()
