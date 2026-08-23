from data_engine.analysis_plan import (
    AnalysisPlan,
    FilterCondition,
    AGGREGATION_ALIASES,
    CANONICAL_AGGREGATIONS,
)


# =========================================================
# CANONICAL OPERATORS
# =========================================================

OPERATOR_ALIASES = {
    "==": "=",
}


# =========================================================
# CANONICAL SORT DIRECTIONS
# =========================================================

ALLOWED_SORT_DIRECTIONS = {
    "asc",
    "desc",
}


# =========================================================
# CANONICAL SORT FIELDS
# =========================================================

ALLOWED_SORT_BY = {
    "metric",
    "time",
}


# =========================================================
# CANONICAL VISUALIZATIONS
# =========================================================

ALLOWED_VISUALIZATIONS = {
    "bar",
    "line",
    "pie",
    "scatter",
    "table",
}


# =========================================================
# NORMALIZE AGGREGATION
# =========================================================


def normalize_aggregation(
    aggregation,
) -> str:
    """
    Convert AI aggregation terminology into the canonical
    Data Engine aggregation vocabulary.

    Examples:

        "average"    -> "mean"
        "avg"        -> "mean"
        "mean"       -> "mean"
        "total"      -> "sum"
        "maximum"    -> "max"
        "minimum"    -> "min"
        "number"     -> "count"
    """

    if aggregation is None:
        return "sum"

    normalized = str(aggregation).strip().lower().replace(" ", "_").replace("-", "_")

    canonical = AGGREGATION_ALIASES.get(
        normalized,
    )

    if canonical is None:
        raise ValueError(f"Unsupported AI aggregation: {aggregation}")

    return canonical


# =========================================================
# NORMALIZE OPERATOR
# =========================================================


def normalize_operator(
    operator,
) -> str:
    """
    Convert AI filter operators into the canonical
    Data Engine representation.

    Example:

        "==" -> "="
    """

    if operator is None:
        raise ValueError("Filter operator cannot be empty.")

    normalized = str(operator).strip()

    return OPERATOR_ALIASES.get(
        normalized,
        normalized,
    )


# =========================================================
# NORMALIZE SORT
# =========================================================


def normalize_sort(
    sort,
) -> str:
    """
    Normalize sorting direction.

    Defaults to descending order when the AI does not
    provide a value.
    """

    if sort is None:
        return "desc"

    normalized = str(sort).strip().lower()

    if normalized not in ALLOWED_SORT_DIRECTIONS:
        raise ValueError(f"Unsupported AI sort direction: {sort}")

    return normalized


# =========================================================
# NORMALIZE SORT BY
# =========================================================


def normalize_sort_by(
    sort_by,
) -> str:
    """
    Normalize the field used for sorting.

    Supported values:

        metric
        time
    """

    if sort_by is None:
        return "metric"

    normalized = str(sort_by).strip().lower()

    if normalized not in ALLOWED_SORT_BY:
        raise ValueError(f"Unsupported AI sort field: {sort_by}")

    return normalized


# =========================================================
# NORMALIZE VISUALIZATION
# =========================================================


def normalize_visualization(
    visualization,
):
    """
    Convert the AI visualization representation into
    the canonical Data Engine visualization string.

    Supports both:

        "bar"

    and:

        VisualizationPlan(type="bar", ...)
    """

    if visualization is None:
        return None

    if hasattr(
        visualization,
        "type",
    ):
        visualization = visualization.type

    normalized = str(visualization).strip().lower()

    if normalized not in ALLOWED_VISUALIZATIONS:
        raise ValueError(f"Unsupported AI visualization: {visualization}")

    return normalized


# =========================================================
# NORMALIZE LIMIT
# =========================================================


def normalize_limit(
    limit,
):
    """
    Normalize the AI ranking/result limit.

    None means no limit.
    """

    if limit is None:
        return None

    try:
        normalized = int(limit)

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(f"Invalid AI limit: {limit}") from exc

    if normalized <= 0:
        raise ValueError("AI limit must be greater than zero.")

    return normalized


# =========================================================
# NORMALIZE GROUP BY
# =========================================================


def normalize_group_by(
    group_by,
) -> list[str]:
    """
    Normalize the AI group_by value into a clean list.

    The adapter does not invent or resolve columns here.
    Column existence is validated later by validate_plan().
    """

    if group_by is None:
        return []

    if isinstance(
        group_by,
        str,
    ):
        group_by = [group_by]

    return [str(column).strip() for column in group_by if str(column).strip()]


# =========================================================
# NORMALIZE TIME FIELDS
# =========================================================


def normalize_time_value(
    value,
):
    """
    Normalize optional time-analysis values.

    None remains None.
    """

    if value is None:
        return None

    return str(value).strip().lower()


# =========================================================
# CONVERT AI PLAN → DATA ENGINE PLAN
# =========================================================


def convert_to_analysis_plan(
    ai_plan,
) -> AnalysisPlan:
    """
    Convert the AI planner's response into the canonical
    Data Engine AnalysisPlan.

    This function is the boundary between:

        AI vocabulary
             ↓
        Data Engine vocabulary

    IMPORTANT:

    Only a successful AI plan may cross this boundary.

    "clarification" and "invalid" responses must be handled
    before an AnalysisPlan is created.
    """

    # =====================================================
    # 1. VALIDATE AI RESPONSE STATUS
    # =====================================================

    status = getattr(
        ai_plan,
        "status",
        None,
    )

    # -----------------------------------------------------
    # INVALID
    # -----------------------------------------------------

    if status == "invalid":
        reason = getattr(
            ai_plan,
            "reason",
            None,
        )

        raise ValueError(reason or "AI planner returned an invalid request.")

    # -----------------------------------------------------
    # CLARIFICATION
    # -----------------------------------------------------
    #
    # This is NOT an executable plan.
    #
    # Example:
    #
    # User:
    #     "show me the best one"
    #
    # AI:
    #     status = "clarification"
    #     clarification_question =
    #         "What would you like to compare?"
    #
    # The adapter must stop here.
    #
    # We deliberately raise a dedicated exception instead
    # of creating a fake/default AnalysisPlan.
    # =====================================================

    if status == "clarification":
        clarification_question = getattr(
            ai_plan,
            "clarification_question",
            None,
        )

        reason = getattr(
            ai_plan,
            "reason",
            None,
        )

        message = (
            clarification_question
            or reason
            or "The question needs clarification before analysis can continue."
        )

        raise AnalysisClarificationError(message)

    # -----------------------------------------------------
    # UNKNOWN STATUS
    # -----------------------------------------------------

    if status != "success":
        raise ValueError(f"Unsupported AI planner status: {status}")

    # =====================================================
    # 2. NORMALIZE FILTERS
    # =====================================================

    filters = []

    for condition in getattr(
        ai_plan,
        "filters",
        [],
    ):
        operator = normalize_operator(
            getattr(
                condition,
                "operator",
                None,
            )
        )

        filters.append(
            FilterCondition(
                column=condition.column,
                operator=operator,
                value=condition.value,
            )
        )

    # =====================================================
    # 3. NORMALIZE GROUP BY
    # =====================================================

    group_by = normalize_group_by(
        getattr(
            ai_plan,
            "group_by",
            [],
        )
    )

    # =====================================================
    # 4. NORMALIZE METRIC
    # =====================================================

    metric = getattr(
        ai_plan,
        "metric",
        None,
    )

    if metric is not None:
        metric = str(metric).strip()

        if not metric:
            metric = None

    # =====================================================
    # 5. NORMALIZE AGGREGATION
    # =====================================================

    aggregation = normalize_aggregation(
        getattr(
            ai_plan,
            "aggregation",
            "sum",
        )
    )

    # =====================================================
    # 6. NORMALIZE SORT
    # =====================================================

    sort = normalize_sort(
        getattr(
            ai_plan,
            "sort",
            "desc",
        )
    )

    # =====================================================
    # 7. NORMALIZE SORT BY
    # =====================================================

    sort_by = normalize_sort_by(
        getattr(
            ai_plan,
            "sort_by",
            "metric",
        )
    )

    # =====================================================
    # 8. NORMALIZE LIMIT
    # =====================================================

    limit = normalize_limit(
        getattr(
            ai_plan,
            "limit",
            None,
        )
    )

    # =====================================================
    # 9. NORMALIZE VISUALIZATION
    # =====================================================

    visualization = normalize_visualization(
        getattr(
            ai_plan,
            "visualization",
            None,
        )
    )

    # =====================================================
    # 10. NORMALIZE TIME ANALYSIS
    # =====================================================

    time_column = getattr(
        ai_plan,
        "time_column",
        None,
    )

    if time_column is not None:
        time_column = str(time_column).strip()

        if not time_column:
            time_column = None

    time_granularity = normalize_time_value(
        getattr(
            ai_plan,
            "time_granularity",
            None,
        )
    )

    # =====================================================
    # 11. BUILD CANONICAL DATA ENGINE PLAN
    # =====================================================

    return AnalysisPlan(
        filters=filters,
        group_by=group_by,
        metric=metric,
        aggregation=aggregation,
        sort=sort,
        sort_by=sort_by,
        limit=limit,
        visualization=visualization,
        time_column=time_column,
        time_granularity=time_granularity,
    )


# =========================================================
# CLARIFICATION EXCEPTION
# =========================================================


class AnalysisClarificationError(Exception):
    """
    Raised when the AI planner understands the user's
    request but needs additional information before a
    safe analysis plan can be created.

    This is intentionally different from ValueError.

    ValueError:
        The request/plan is invalid.

    AnalysisClarificationError:
        The request may be valid, but the user needs to
        clarify their intent.
    """

    pass
