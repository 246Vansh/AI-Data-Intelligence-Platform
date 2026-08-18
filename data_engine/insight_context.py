import pandas as pd


def build_insight_context(
    result: pd.DataFrame,
    metric_column: str,
    group_by: list[str],
) -> dict:

    context = {
        "row_count": len(result),
        "metric_column": metric_column,
        "group_by": group_by,
        # -----------------------------------------
        # Full computed result
        # -----------------------------------------
        "result_rows": result.to_dict(orient="records"),
    }

    # -----------------------------------------
    # Empty result
    # -----------------------------------------

    if result.empty:
        return context

    # -----------------------------------------
    # Validate metric column
    # -----------------------------------------

    if metric_column not in result.columns:
        return context

    metric = result[metric_column]

    # -----------------------------------------
    # Highest
    # -----------------------------------------

    max_index = metric.idxmax()

    context["highest"] = {
        "value": float(
            result.loc[
                max_index,
                metric_column,
            ]
        ),
        "row": (result.loc[max_index].to_dict()),
    }

    # -----------------------------------------
    # Lowest
    # -----------------------------------------

    min_index = metric.idxmin()

    context["lowest"] = {
        "value": float(
            result.loc[
                min_index,
                metric_column,
            ]
        ),
        "row": (result.loc[min_index].to_dict()),
    }

    # -----------------------------------------
    # Difference
    # -----------------------------------------

    context["difference"] = float(metric.max() - metric.min())

    # -----------------------------------------
    # Date coverage
    # -----------------------------------------

    date_column = _find_date_column(
        result=result,
        group_by=group_by,
    )

    if date_column is not None:
        date_coverage = _build_date_coverage(
            result=result,
            date_column=date_column,
        )

        context["date_coverage"] = date_coverage

    return context


# =========================================================
# FIND DATE COLUMN
# =========================================================


def _find_date_column(
    result: pd.DataFrame,
    group_by: list[str],
) -> str | None:

    # -----------------------------------------
    # Prefer explicitly grouped date column
    # -----------------------------------------

    for column in group_by:
        if column not in result.columns:
            continue

        # Already datetime
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            return column

        # Try parsing string/object values
        parsed = pd.to_datetime(
            result[column],
            errors="coerce",
        )

        if parsed.notna().all():
            return column

    # -----------------------------------------
    # Fallback: inspect all columns
    # -----------------------------------------

    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            return column

        parsed = pd.to_datetime(
            result[column],
            errors="coerce",
        )

        if parsed.notna().all():
            return column

    return None


# =========================================================
# DATE COVERAGE
# =========================================================


def _build_date_coverage(
    result: pd.DataFrame,
    date_column: str,
) -> dict:

    dates = pd.to_datetime(
        result[date_column],
        errors="coerce",
    )

    dates = dates.dropna()

    if dates.empty:
        return {}

    dates = dates.sort_values().drop_duplicates()

    min_date = dates.min()
    max_date = dates.max()

    # -----------------------------------------
    # Determine frequency
    # -----------------------------------------

    frequency = _infer_frequency(dates)

    coverage = {
        "date_column": date_column,
        "frequency": frequency,
        "min_date": min_date.isoformat(),
        "max_date": max_date.isoformat(),
        "observed_periods": len(dates),
    }

    # -----------------------------------------
    # Detect missing periods
    # -----------------------------------------

    if frequency == "month":
        expected_dates = pd.date_range(
            start=min_date.to_period("M").start_time,
            end=max_date.to_period("M").start_time,
            freq="MS",
        )

        observed_dates = set(dates.dt.to_period("M"))

        missing_periods = []

        for expected_date in expected_dates:
            period = expected_date.to_period("M")

            if period not in observed_dates:
                missing_periods.append(str(period))

        coverage["expected_periods"] = len(expected_dates)

        coverage["missing_periods"] = missing_periods

        coverage["is_continuous"] = len(missing_periods) == 0

    elif frequency == "year":
        expected_dates = pd.date_range(
            start=min_date.to_period("Y").start_time,
            end=max_date.to_period("Y").start_time,
            freq="YS",
        )

        observed_dates = set(dates.dt.to_period("Y"))

        missing_periods = []

        for expected_date in expected_dates:
            period = expected_date.to_period("Y")

            if period not in observed_dates:
                missing_periods.append(str(period))

        coverage["expected_periods"] = len(expected_dates)

        coverage["missing_periods"] = missing_periods

        coverage["is_continuous"] = len(missing_periods) == 0

    else:
        coverage["is_continuous"] = None

    return coverage


# =========================================================
# FREQUENCY INFERENCE
# =========================================================


def _infer_frequency(
    dates: pd.Series,
) -> str:

    if len(dates) < 2:
        return "unknown"

    normalized = pd.to_datetime(dates).dt.normalize()

    # -----------------------------------------
    # Monthly
    # -----------------------------------------
    #
    # A monthly aggregated result normally uses
    # the first day of each month.
    #
    # Missing months do NOT matter here.
    # We only care about the representation of
    # the observed periods.

    if set(normalized.dt.day) == {1}:
        # If multiple months are represented
        # within the same year or across years,
        # treat the data as monthly.

        unique_months = normalized.dt.to_period("M").nunique()

        if unique_months == len(normalized.drop_duplicates()):
            return "month"

    # -----------------------------------------
    # Yearly
    # -----------------------------------------

    if set(normalized.dt.month) == {1} and set(normalized.dt.day) == {1}:
        unique_years = normalized.dt.to_period("Y").nunique()

        if unique_years == len(normalized.drop_duplicates()):
            return "year"

    return "unknown"
