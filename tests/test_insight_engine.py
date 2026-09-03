"""Step 12B: InsightEngine._add_date_coverage() sampling short-circuit.

Verifies the dtype fast-path (already-datetime64 columns skip reparsing)
and the bounded-prefix sample short-circuit (a purely categorical
group-by column is rejected without a full-column format="mixed" scan)
introduced in data_engine/insight_engine.py, while preserving the exact
existing date_coverage output for every case that was already handled
correctly - genuine datetime64 columns, string-based date columns,
multiple group_by columns, and columns containing nulls.
"""

import pandas as pd

from data_engine.insight_engine import InsightEngine

METRIC_COLUMN = "sum_quantity"


# =========================================================
# A. CATEGORICAL REGRESSION - 10,000 distinct non-date values
# =========================================================


def test_categorical_group_by_with_10000_rows_has_no_date_coverage():
    group_count = 10_000
    result = pd.DataFrame(
        {
            "region": [f"region_{i}" for i in range(group_count)],
            METRIC_COLUMN: [1] * group_count,
        }
    )

    engine = InsightEngine(
        result=result,
        metric_column=METRIC_COLUMN,
        group_by=["region"],
    )

    context = engine.generate()

    assert "date_coverage" not in context
    assert context["row_count"] == group_count


# =========================================================
# B. GENUINE DATETIME64 COLUMN - dtype fast path
# =========================================================


def test_datetime64_group_by_column_produces_expected_date_coverage():
    result = pd.DataFrame(
        {
            "month": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
            ),
            METRIC_COLUMN: [10, 20, 30, 40],
        }
    )
    assert pd.api.types.is_datetime64_any_dtype(result["month"])

    engine = InsightEngine(
        result=result,
        metric_column=METRIC_COLUMN,
        group_by=["month"],
    )

    context = engine.generate()

    assert context["date_coverage"] == {
        "date_column": "month",
        "frequency": "month",
        "min_date": "2024-01-01T00:00:00",
        "max_date": "2024-04-01T00:00:00",
        "observed_periods": 4,
        "expected_periods": 4,
        "missing_periods": [],
        "is_continuous": True,
    }


# =========================================================
# C. STRING-BASED DATE COLUMN - sample-parse path, not dtype fast path
# =========================================================


def test_string_date_group_by_column_still_detected_via_sample_parse():
    result = pd.DataFrame(
        {
            "month": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
            METRIC_COLUMN: [10, 20, 30, 40],
        }
    )
    assert not pd.api.types.is_datetime64_any_dtype(result["month"])

    engine = InsightEngine(
        result=result,
        metric_column=METRIC_COLUMN,
        group_by=["month"],
    )

    context = engine.generate()

    assert context["date_coverage"] == {
        "date_column": "month",
        "frequency": "month",
        "min_date": "2024-01-01T00:00:00",
        "max_date": "2024-04-01T00:00:00",
        "observed_periods": 4,
        "expected_periods": 4,
        "missing_periods": [],
        "is_continuous": True,
    }


# =========================================================
# EDGE CASE - null after the sampled prefix must still reject the
# column, exactly like the original full-column parse would.
# =========================================================


def test_null_after_sampled_prefix_still_rejects_column():
    # 25 valid date strings (> the ~20-row sample) followed by a null -
    # the sample alone would pass, so the fallback full-column parse
    # must still catch the trailing null and reject the column.
    dates = [f"2024-01-{day:02d}" for day in range(1, 26)] + [None]
    result = pd.DataFrame(
        {
            "signup_day": dates,
            METRIC_COLUMN: list(range(len(dates))),
        }
    )

    engine = InsightEngine(
        result=result,
        metric_column=METRIC_COLUMN,
        group_by=["signup_day"],
    )

    context = engine.generate()

    assert "date_coverage" not in context


# =========================================================
# MULTIPLE GROUP_BY COLUMNS - first column (categorical) is rejected
# via the cheap sample short-circuit, second (genuine date) column is
# still found and used.
# =========================================================


def test_multiple_group_by_columns_falls_through_to_the_date_column():
    result = pd.DataFrame(
        {
            "region": ["north", "south", "east", "west"],
            "month": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
            ),
            METRIC_COLUMN: [10, 20, 30, 40],
        }
    )

    engine = InsightEngine(
        result=result,
        metric_column=METRIC_COLUMN,
        group_by=["region", "month"],
    )

    context = engine.generate()

    assert context["date_coverage"]["date_column"] == "month"
    assert context["date_coverage"]["is_continuous"] is True
