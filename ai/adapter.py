from data_engine.analysis_plan import (
    AnalysisPlan,
    FilterCondition,
)

from ai.planner_models import (
    AnalysisPlanResponse,
)


# -----------------------------------------
# AI → Data Engine operator mapping
# -----------------------------------------

OPERATOR_MAP = {
    "==": "=",
    "=": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}


def normalize_operator(
    operator: str,
) -> str:

    normalized = OPERATOR_MAP.get(
        operator.strip()
    )

    if normalized is None:

        raise ValueError(
            f"Unsupported AI filter operator: "
            f"{operator}"
        )

    return normalized


def convert_to_analysis_plan(
    ai_plan: AnalysisPlanResponse,
) -> AnalysisPlan:

    # -----------------------------------------
    # Reject invalid AI plans
    # -----------------------------------------

    if ai_plan.status == "invalid":

        reason = (
            ai_plan.reason
            or "The AI could not create a valid "
               "analysis plan."
        )

        raise ValueError(
            f"Invalid analysis request: {reason}"
        )

    # -----------------------------------------
    # Convert filters
    # -----------------------------------------

    filters = []

    for filter_plan in ai_plan.filters:

        operator = normalize_operator(
            filter_plan.operator
        )

        filters.append(
            FilterCondition(
                column=filter_plan.column,
                operator=operator,
                value=filter_plan.value,
            )
        )

    # -----------------------------------------
    # Convert visualization
    # -----------------------------------------

    visualization = None

    if ai_plan.visualization is not None:

        visualization = (
            ai_plan.visualization.type
        )

    # -----------------------------------------
    # Create engine AnalysisPlan
    # -----------------------------------------

    return AnalysisPlan(
        filters=filters,

        group_by=ai_plan.group_by,

        metric=ai_plan.metric,

        aggregation=(
            ai_plan.aggregation
            or "sum"
        ),

        sort=ai_plan.sort,
        sort_by=ai_plan.sort_by,

        limit=ai_plan.limit,

        visualization=visualization,

        # -------------------------------------
        # Time analysis
        # -------------------------------------

        time_granularity=(
            ai_plan.time_granularity
        ),
    )