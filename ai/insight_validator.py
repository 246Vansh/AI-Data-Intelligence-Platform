from math import isclose

from ai.insight_models import (
    InsightResponse,
    InsightEvidence,
    MultiRowEvidence,
    CoverageEvidence,
)


ALLOWED_INSIGHT_TYPES = {
    "highest",
    "lowest",
    "trend",
    "pattern",
    "increasing",
    "decreasing",
    "difference",
    "comparison",
    "notable",
    "large_difference",
    "data_coverage",
    "observation",
    "coverage",
}


NUMERIC_TOLERANCE = 1e-6


def validate_insights(
    response: InsightResponse,
    context: dict | None = None,
) -> None:

    # -----------------------------------------
    # Validate number of insights
    # -----------------------------------------

    if len(response.insights) > 10:
        raise ValueError("Insight response contains too many insights.")

    # -----------------------------------------
    # Validate individual insights
    # -----------------------------------------

    for index, insight in enumerate(response.insights):
        # -------------------------------------
        # Validate type
        # -------------------------------------

        if insight.type not in ALLOWED_INSIGHT_TYPES:
            raise ValueError(
                f"Unsupported insight type at index {index}: {insight.type}"
            )

        # -------------------------------------
        # Validate title
        # -------------------------------------

        if not insight.title.strip():
            raise ValueError(f"Insight title cannot be empty at index {index}.")

        # -------------------------------------
        # Validate description
        # -------------------------------------

        if not insight.description.strip():
            raise ValueError(f"Insight description cannot be empty at index {index}.")

        # -------------------------------------
        # Validate evidence
        # -------------------------------------

        if insight.evidence is not None:
            if context is None:
                raise ValueError(
                    f"Insight at index {index} "
                    "contains evidence but no "
                    "validation context was supplied."
                )

            _validate_evidence(
                insight=insight,
                index=index,
                context=context,
            )

        # -------------------------------------
        # Semantic verification
        # -------------------------------------

        if context is not None:
            _validate_semantics(
                insight=insight,
                index=index,
                context=context,
            )


# =========================================================
# EVIDENCE DISPATCH
# =========================================================


def _validate_evidence(
    insight,
    index: int,
    context: dict,
) -> None:

    evidence = insight.evidence

    # -----------------------------------------
    # Single-row evidence
    # -----------------------------------------

    if isinstance(
        evidence,
        InsightEvidence,
    ):
        _validate_single_row_evidence(
            evidence=evidence,
            index=index,
            context=context,
        )

        return

    # -----------------------------------------
    # Multi-row evidence
    # -----------------------------------------

    if isinstance(
        evidence,
        MultiRowEvidence,
    ):
        _validate_multi_row_evidence(
            evidence=evidence,
            index=index,
            context=context,
        )

        return

    # -----------------------------------------
    # Coverage evidence
    # -----------------------------------------

    if isinstance(
        evidence,
        CoverageEvidence,
    ):
        _validate_coverage_evidence(
            evidence=evidence,
            index=index,
            context=context,
        )

        return

    # -----------------------------------------
    # Unknown evidence type
    # -----------------------------------------

    raise ValueError(f"Unsupported evidence structure at index {index}.")


# =========================================================
# SINGLE-ROW EVIDENCE
# =========================================================


def _validate_single_row_evidence(
    evidence: InsightEvidence,
    index: int,
    context: dict,
) -> None:

    expected_column = context.get("metric_column")

    # -----------------------------------------
    # Validate evidence column
    # -----------------------------------------

    if expected_column is not None and evidence.column != expected_column:
        raise ValueError(f"Invalid evidence column at index {index}: {evidence.column}")

    # -----------------------------------------
    # Validate evidence value
    # -----------------------------------------

    if not isinstance(
        evidence.value,
        (int, float),
    ):
        raise ValueError(f"Evidence value must be numeric at index {index}.")

    # -----------------------------------------
    # Validate evidence row
    # -----------------------------------------

    if not isinstance(
        evidence.row,
        dict,
    ):
        raise ValueError(f"Evidence row must be an object at index {index}.")

    row_value = evidence.row.get(evidence.column)

    if row_value is None:
        raise ValueError(
            f"Evidence row does not contain "
            f"column '{evidence.column}' "
            f"at index {index}."
        )

    # -----------------------------------------
    # Compare evidence value with row value
    # -----------------------------------------

    if not _numbers_equal(
        row_value,
        evidence.value,
    ):
        raise ValueError(
            f"Evidence value does not match evidence row at index {index}."
        )


# =========================================================
# MULTI-ROW EVIDENCE
# =========================================================


def _validate_multi_row_evidence(
    evidence: MultiRowEvidence,
    index: int,
    context: dict,
) -> None:

    rows = evidence.rows

    # -----------------------------------------
    # At least two rows are required
    # -----------------------------------------

    if len(rows) < 2:
        raise ValueError(
            f"Multi-row evidence at index {index} must contain at least two rows."
        )

    # -----------------------------------------
    # Analysis result must be available
    # -----------------------------------------

    result_rows = context.get("result_rows")

    if result_rows is None:
        raise ValueError(
            "Insight context does not contain "
            "result_rows required for "
            "multi-row evidence validation."
        )

    # -----------------------------------------
    # Every evidence row must exist in result
    # -----------------------------------------

    for row_index, evidence_row in enumerate(rows):
        if not isinstance(
            evidence_row,
            dict,
        ):
            raise ValueError(
                f"Multi-row evidence contains an invalid row at index {row_index}."
            )

        if not _row_exists(
            evidence_row,
            result_rows,
        ):
            raise ValueError(
                f"Evidence row at index "
                f"{row_index} does not exist "
                f"in the computed analysis result."
            )


# =========================================================
# SEMANTIC VERIFICATION
# =========================================================


def _validate_semantics(
    insight,
    index: int,
    context: dict,
) -> None:

    insight_type = insight.type

    # -----------------------------------------
    # Highest
    # -----------------------------------------

    if insight_type == "highest":
        _validate_extreme_insight(
            insight=insight,
            index=index,
            context=context,
            context_key="highest",
        )

    # -----------------------------------------
    # Lowest
    # -----------------------------------------

    elif insight_type == "lowest":
        _validate_extreme_insight(
            insight=insight,
            index=index,
            context=context,
            context_key="lowest",
        )

    # -----------------------------------------
    # Difference
    # -----------------------------------------

    elif insight_type in {
        "difference",
        "large_difference",
    }:
        _validate_difference(
            insight=insight,
            index=index,
            context=context,
        )

    # -----------------------------------------
    # Trend
    # -----------------------------------------

    elif insight_type in {
        "trend",
        "increasing",
        "decreasing",
    }:
        _validate_trend(
            insight=insight,
            index=index,
            context=context,
        )

    # -----------------------------------------
    # Coverage
    # -----------------------------------------

    elif insight_type == "coverage":
        _validate_coverage_insight(
            insight=insight,
            index=index,
            context=context,
        )


# =========================================================
# COVERAGE SEMANTIC VALIDATION
# =========================================================


def _validate_coverage_insight(
    insight,
    index: int,
    context: dict,
) -> None:

    date_coverage = context.get("date_coverage")

    if date_coverage is None:
        raise ValueError(
            f"Coverage insight at index {index} "
            "cannot be validated because "
            "date coverage is unavailable."
        )

    evidence = insight.evidence

    if not isinstance(
        evidence,
        CoverageEvidence,
    ):
        raise ValueError(
            f"Coverage insight at index {index} requires CoverageEvidence."
        )

    # -----------------------------------------
    # Ensure the claim isn't saying the
    # opposite of the verified state.
    # -----------------------------------------

    verified_continuous = date_coverage.get("is_continuous")

    if verified_continuous is False:
        if evidence.is_continuous:
            raise ValueError(
                f"Coverage insight at index {index} "
                "claims continuous data even though "
                "the verified context reports gaps."
            )

    # -----------------------------------------
    # If data is continuous, a coverage insight
    # should not claim missing periods.
    # -----------------------------------------

    if verified_continuous is True:
        if evidence.missing_periods:
            raise ValueError(
                f"Coverage insight at index {index} "
                "contains missing periods even though "
                "the verified context reports continuous data."
            )


# =========================================================
# EXTREME VALIDATION
# =========================================================


def _validate_extreme_insight(
    insight,
    index: int,
    context: dict,
    context_key: str,
) -> None:

    expected = context.get(context_key)

    if expected is None:
        return

    expected_value = expected.get("value")

    if expected_value is None:
        return

    evidence = insight.evidence

    if not isinstance(
        evidence,
        InsightEvidence,
    ):
        raise ValueError(
            f"{context_key.capitalize()} insight "
            f"at index {index} requires "
            "single-row evidence."
        )

    # -----------------------------------------
    # Verify value
    # -----------------------------------------

    if not _numbers_equal(
        evidence.value,
        expected_value,
    ):
        raise ValueError(
            f"Insight at index {index} claims "
            f"{context_key} value "
            f"{evidence.value}, but the verified "
            f"context says {expected_value}."
        )

    # -----------------------------------------
    # Verify row
    # -----------------------------------------

    expected_row = expected.get("row")

    if expected_row is not None:
        if not _rows_match(
            evidence.row,
            expected_row,
        ):
            raise ValueError(
                f"Insight at index {index} "
                f"contains evidence that does not "
                f"match the verified "
                f"{context_key} row."
            )


# =========================================================
# DIFFERENCE VALIDATION
# =========================================================


def _validate_difference(
    insight,
    index: int,
    context: dict,
) -> None:

    expected_difference = context.get("difference")

    if expected_difference is None:
        return

    evidence = insight.evidence

    # -----------------------------------------
    # No evidence
    # -----------------------------------------

    if evidence is None:
        return

    # -----------------------------------------
    # Multi-row evidence
    # -----------------------------------------

    if isinstance(
        evidence,
        MultiRowEvidence,
    ):
        if len(evidence.rows) != 2:
            raise ValueError(
                f"Difference insight at index "
                f"{index} must contain exactly "
                f"two evidence rows."
            )

        metric_column = context.get("metric_column")

        if not metric_column:
            return

        first_value = evidence.rows[0].get(metric_column)

        second_value = evidence.rows[1].get(metric_column)

        if first_value is None or second_value is None:
            raise ValueError(
                f"Difference evidence at index "
                f"{index} must contain the "
                f"metric column '{metric_column}'."
            )

        try:
            calculated_difference = abs(float(first_value) - float(second_value))

        except (
            TypeError,
            ValueError,
        ):
            raise ValueError(
                f"Difference evidence at index "
                f"{index} contains non-numeric "
                f"metric values."
            )

        # -------------------------------------
        # Compare against verified context
        # -------------------------------------

        if not _numbers_equal(
            calculated_difference,
            expected_difference,
        ):
            raise ValueError(
                f"Difference evidence at index "
                f"{index} does not match the "
                f"verified difference. "
                f"Calculated: "
                f"{calculated_difference}, "
                f"Expected: "
                f"{expected_difference}."
            )

        return

    # -----------------------------------------
    # Single-row evidence
    # -----------------------------------------

    if isinstance(
        evidence,
        InsightEvidence,
    ):
        if not _numbers_equal(
            evidence.value,
            expected_difference,
        ):
            raise ValueError(
                f"Insight at index {index} claims "
                f"a difference of {evidence.value}, "
                f"but the verified context says "
                f"{expected_difference}."
            )

        return

    # -----------------------------------------
    # Unknown evidence
    # -----------------------------------------

    raise ValueError(f"Invalid difference evidence at index {index}.")


# =========================================================
# TREND VALIDATION
# =========================================================


def _validate_trend(
    insight,
    index: int,
    context: dict,
) -> None:

    evidence = insight.evidence

    # -----------------------------------------
    # Trend requires multi-row evidence
    # -----------------------------------------

    if not isinstance(
        evidence,
        MultiRowEvidence,
    ):
        raise ValueError(f"Trend insight at index {index} requires multi-row evidence.")

    rows = evidence.rows

    if len(rows) < 2:
        raise ValueError(
            f"Trend insight at index {index} requires at least two evidence rows."
        )

    metric_column = context.get("metric_column")

    if not metric_column:
        return

    # -----------------------------------------
    # Extract numeric values
    # -----------------------------------------

    values = []

    for row_index, row in enumerate(rows):
        value = row.get(metric_column)

        if value is None:
            raise ValueError(
                f"Trend evidence row "
                f"{row_index} at insight index "
                f"{index} does not contain "
                f"metric column "
                f"'{metric_column}'."
            )

        try:
            values.append(float(value))

        except (
            TypeError,
            ValueError,
        ):
            raise ValueError(
                f"Trend evidence row "
                f"{row_index} at insight index "
                f"{index} contains a non-numeric "
                f"metric value."
            )

    # -----------------------------------------
    # Increasing
    # -----------------------------------------

    if insight.type == "increasing":
        for i in range(len(values) - 1):
            if values[i] > values[i + 1]:
                raise ValueError(
                    f"Increasing trend at "
                    f"index {index} is contradicted "
                    f"by its evidence rows."
                )

    # -----------------------------------------
    # Decreasing
    # -----------------------------------------

    elif insight.type == "decreasing":
        for i in range(len(values) - 1):
            if values[i] < values[i + 1]:
                raise ValueError(
                    f"Decreasing trend at "
                    f"index {index} is contradicted "
                    f"by its evidence rows."
                )

    # -----------------------------------------
    # Generic trend
    # -----------------------------------------

    elif insight.type == "trend":
        # A generic trend can move up and down.
        # Structural multi-row validation is enough
        # at this stage.

        return


# =========================================================
# COVERAGE VALIDATION
# =========================================================


def _validate_coverage_evidence(
    evidence: CoverageEvidence,
    index: int,
    context: dict,
) -> None:

    date_coverage = context.get("date_coverage")

    if date_coverage is None:
        raise ValueError(
            f"Coverage insight at index {index} "
            "requires verified date coverage context."
        )

    # -----------------------------------------
    # Date column
    # -----------------------------------------

    expected_date_column = date_coverage.get("date_column")

    if (
        expected_date_column is not None
        and evidence.date_column != expected_date_column
    ):
        raise ValueError(
            f"Coverage insight at index {index} "
            f"contains date column "
            f"'{evidence.date_column}', but the "
            f"verified context says "
            f"'{expected_date_column}'."
        )

    # -----------------------------------------
    # Frequency
    # -----------------------------------------

    expected_frequency = date_coverage.get("frequency")

    if expected_frequency is not None and evidence.frequency != expected_frequency:
        raise ValueError(
            f"Coverage insight at index {index} "
            f"contains frequency "
            f"'{evidence.frequency}', but the "
            f"verified context says "
            f"'{expected_frequency}'."
        )

    # -----------------------------------------
    # Minimum date
    # -----------------------------------------

    expected_min_date = date_coverage.get("min_date")

    if expected_min_date is not None and evidence.min_date != expected_min_date:
        raise ValueError(
            f"Coverage insight at index {index} contains an incorrect minimum date."
        )

    # -----------------------------------------
    # Maximum date
    # -----------------------------------------

    expected_max_date = date_coverage.get("max_date")

    if expected_max_date is not None and evidence.max_date != expected_max_date:
        raise ValueError(
            f"Coverage insight at index {index} contains an incorrect maximum date."
        )

    # -----------------------------------------
    # Observed periods
    # -----------------------------------------

    expected_observed = date_coverage.get("observed_periods")

    if expected_observed is not None and evidence.observed_periods != expected_observed:
        raise ValueError(
            f"Coverage insight at index {index} "
            f"claims {evidence.observed_periods} "
            f"observed periods, but the verified "
            f"context says {expected_observed}."
        )

    # -----------------------------------------
    # Expected periods
    # -----------------------------------------

    expected_periods = date_coverage.get("expected_periods")

    if expected_periods is not None and evidence.expected_periods != expected_periods:
        raise ValueError(
            f"Coverage insight at index {index} "
            f"claims {evidence.expected_periods} "
            f"expected periods, but the verified "
            f"context says {expected_periods}."
        )

    # -----------------------------------------
    # Missing periods
    # -----------------------------------------

    expected_missing = date_coverage.get(
        "missing_periods",
        [],
    )

    actual_missing = evidence.missing_periods

    if actual_missing != expected_missing:
        raise ValueError(
            f"Coverage insight at index {index} "
            "contains incorrect missing periods.\n"
            f"Expected: {expected_missing}\n"
            f"Received: {actual_missing}"
        )

    # -----------------------------------------
    # Continuity
    # -----------------------------------------

    expected_continuous = date_coverage.get("is_continuous")

    if (
        expected_continuous is not None
        and evidence.is_continuous != expected_continuous
    ):
        raise ValueError(
            f"Coverage insight at index {index} "
            f"claims is_continuous="
            f"{evidence.is_continuous}, but the "
            f"verified context says "
            f"{expected_continuous}."
        )


# =========================================================
# HELPERS
# =========================================================


def _numbers_equal(
    left,
    right,
) -> bool:

    try:
        return isclose(
            float(left),
            float(right),
            rel_tol=NUMERIC_TOLERANCE,
            abs_tol=NUMERIC_TOLERANCE,
        )

    except (
        TypeError,
        ValueError,
    ):
        return False


def _rows_match(
    actual: dict,
    expected: dict,
) -> bool:

    if set(actual.keys()) != set(expected.keys()):
        return False

    for key in actual:
        actual_value = actual[key]
        expected_value = expected[key]

        if isinstance(
            actual_value,
            (int, float),
        ) and isinstance(
            expected_value,
            (int, float),
        ):
            if not _numbers_equal(
                actual_value,
                expected_value,
            ):
                return False

        else:
            if str(actual_value) != str(expected_value):
                return False

    return True


def _row_exists(
    target_row: dict,
    result_rows: list[dict],
) -> bool:

    for result_row in result_rows:
        if _rows_match(
            target_row,
            result_row,
        ):
            return True

    return False
