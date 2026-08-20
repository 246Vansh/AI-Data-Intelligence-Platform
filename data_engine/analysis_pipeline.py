from dataclasses import dataclass
from typing import Any

import pandas as pd

from data_engine.dataset_intelligence import (
    build_dataset_intelligence,
)

from data_engine.plan_validator import (
    validate_plan,
)

from data_engine.plan_executor import (
    execute_plan,
)

from data_engine.visualization import (
    create_visualization_spec,
)

from data_engine.insight_engine import (
    build_deterministic_insights,
)

from data_engine.insight_generator import (
    build_insight_response,
)

from ai.fast_planner import (
    FastPlanner,
)

from ai.planner import (
    create_analysis_plan,
)

from ai.insight_validator import (
    validate_insights,
)


@dataclass
class AnalysisPipelineResult:
    """
    Result produced by the analysis pipeline.

    This object is independent of FastAPI.
    """

    question: str

    analysis_result: dict[str, Any]

    insights: Any

    insight_status: str

    insight_source: str

    insight_error: str | None

    visualization: dict[str, Any]

    plan: Any

    planner_type: str

    fallback_to_ai: bool

    dataset_intelligence: dict[str, Any]


def run_analysis_pipeline(
    df: pd.DataFrame,
    question: str,
) -> AnalysisPipelineResult:

    # =====================================================
    # 1. Validate question
    # =====================================================

    question = question.strip()

    if not question:
        raise ValueError("Question cannot be empty.")

    # =====================================================
    # 2. Dataset Intelligence
    # =====================================================

    dataset_intelligence = build_dataset_intelligence(df)

    metadata = dataset_intelligence["metadata"]

    # =====================================================
    # 3. Fast Planner
    # =====================================================

    fast_planner = FastPlanner()

    fast_plan = fast_planner.create_plan(
        question=question,
        metadata=metadata,
    )

    # =====================================================
    # 4. Planner Selection
    # =====================================================

    if fast_plan is not None:
        # -----------------------------------------------
        # Deterministic path
        # -----------------------------------------------

        plan = fast_plan

        planner_type = "fast"

        fallback_to_ai = False

        ai_plan = None

    else:
        # -----------------------------------------------
        # AI fallback path
        # -----------------------------------------------

        ai_plan = create_analysis_plan(
            user_question=question,
            metadata=metadata,
        )

        planner_type = "claude"

        fallback_to_ai = True

        # -------------------------------------------------
        # AI planner can return an invalid request.
        #
        # Current planner implementation returns
        # AnalysisPlan directly, so we intentionally
        # do not assume a `.status` attribute here.
        # -------------------------------------------------

        plan = ai_plan

    # =====================================================
    # 5. Validate Plan
    # =====================================================

    validate_plan(
        df,
        plan,
    )

    # =====================================================
    # 6. Execute Analysis
    # =====================================================

    result = execute_plan(
        df,
        plan,
    )

    analysis_result = {
        "columns": result.columns.tolist(),
        "rows": result.to_dict(orient="records"),
        "row_count": len(result),
    }

    # =====================================================
    # 7. Deterministic Insight Context
    # =====================================================

    metric_column = f"{plan.aggregation}_{plan.metric}"

    insight_context = build_deterministic_insights(
        result=result,
        metric_column=metric_column,
        group_by=plan.group_by,
    )

    # =====================================================
    # 8. Deterministic Insights
    # =====================================================

    insight_response = None
    insight_error = None

    try:
        insight_response = build_insight_response(
            context=insight_context,
        )

        validate_insights(
            insight_response,
            insight_context,
        )

    except Exception as exc:
        # Insights are an enrichment layer.
        # Analysis itself remains successful.

        insight_error = str(exc)

    # =====================================================
    # 9. Visualization
    # =====================================================

    if not plan.group_by:
        visualization_type = "table"

    else:
        visualization_type = plan.visualization or "table"

    # AI visualization title is currently available
    # only when the AI planner provides it.
    visualization_title = None

    if (
        ai_plan is not None
        and hasattr(ai_plan, "visualization")
        and ai_plan.visualization is not None
        and hasattr(
            ai_plan.visualization,
            "title",
        )
    ):
        visualization_title = ai_plan.visualization.title

    visualization_spec = create_visualization_spec(
        result=result,
        visualization_type=visualization_type,
        title=visualization_title,
    )

    # =====================================================
    # 10. Return Pipeline Result
    # =====================================================

    return AnalysisPipelineResult(
        question=question,
        analysis_result=analysis_result,
        insights=insight_response,
        insight_status=("success" if insight_response is not None else "unavailable"),
        insight_source="deterministic",
        insight_error=insight_error,
        visualization=visualization_spec,
        plan=plan,
        planner_type=planner_type,
        fallback_to_ai=fallback_to_ai,
        dataset_intelligence=dataset_intelligence,
    )
