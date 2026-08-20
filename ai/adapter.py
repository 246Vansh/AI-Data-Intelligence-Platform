from data_engine.analysis_plan import (
    AnalysisPlan,
    FilterCondition,
)


def convert_to_analysis_plan(
    ai_plan,
) -> AnalysisPlan:

    # -------------------------------------------------
    # Validate AI response status
    # -------------------------------------------------

    if getattr(ai_plan, "status", None) == "invalid":
        reason = getattr(
            ai_plan,
            "reason",
            None,
        )

        raise ValueError(reason or "AI planner returned an invalid request.")

    # -------------------------------------------------
    # Normalize filters
    # -------------------------------------------------

    filters = []

    for condition in getattr(
        ai_plan,
        "filters",
        [],
    ):
        operator = condition.operator

        # AI may use == while the Data Engine
        # uses = as its canonical equality operator.
        if operator == "==":
            operator = "="

        filters.append(
            FilterCondition(
                column=condition.column,
                operator=operator,
                value=condition.value,
            )
        )

    # -------------------------------------------------
    # Visualization
    # -------------------------------------------------

    visualization = None

    ai_visualization = getattr(
        ai_plan,
        "visualization",
        None,
    )

    if ai_visualization is not None:
        if hasattr(
            ai_visualization,
            "type",
        ):
            visualization = ai_visualization.type

        else:
            visualization = ai_visualization

    # -------------------------------------------------
    # Build canonical Data Engine plan
    # -------------------------------------------------

    return AnalysisPlan(
        filters=filters,
        group_by=list(
            getattr(
                ai_plan,
                "group_by",
                [],
            )
        ),
        metric=getattr(
            ai_plan,
            "metric",
            None,
        ),
        aggregation=getattr(
            ai_plan,
            "aggregation",
            "sum",
        ),
        sort=getattr(
            ai_plan,
            "sort",
            "desc",
        ),
        sort_by=getattr(
            ai_plan,
            "sort_by",
            "metric",
        ),
        limit=getattr(
            ai_plan,
            "limit",
            None,
        ),
        visualization=visualization,
        time_granularity=getattr(
            ai_plan,
            "time_granularity",
            None,
        ),
    )
