from math import isclose

from ai.insight_models import InsightResponse


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
        # Context is required for evidence
        # validation
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
# RAW EVIDENCE VALIDATION
# =========================================================


def _validate_evidence(
    insight,
    index: int,
    context: dict,
) -> None:

    evidence = insight.evidence

    # -----------------------------------------
    # Validate evidence column
    # -----------------------------------------

    expected_column = context.get("metric_column")

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

    if evidence.row is None:
        return

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

    if evidence is None:
        raise ValueError(
            f"{context_key.capitalize()} insight at index {index} requires evidence."
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

    if expected_row is not None and evidence.row is not None:
        if not _rows_match(
            evidence.row,
            expected_row,
        ):
            raise ValueError(
                f"Insight at index {index} "
                f"contains evidence that does not "
                f"match the verified {context_key} row."
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
    # Difference may legitimately have no row
    # -----------------------------------------

    if evidence is None:
        return

    # -----------------------------------------
    # Verify difference value
    # -----------------------------------------

    if not _numbers_equal(
        evidence.value,
        expected_difference,
    ):
        raise ValueError(
            f"Insight at index {index} claims "
            f"a difference of "
            f"{evidence.value}, but the verified "
            f"context says "
            f"{expected_difference}."
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

        # -------------------------------------
        # Numeric values
        # -------------------------------------

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

        # -------------------------------------
        # Non-numeric values
        # -------------------------------------

        else:
            if str(actual_value) != str(expected_value):
                return False

    return True
