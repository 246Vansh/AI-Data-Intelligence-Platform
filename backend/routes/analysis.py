from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data_engine.performance import measure

from backend.dependencies import get_walmart_data

from data_engine.metadata import get_metadata

from data_engine.plan_validator import (
    validate_plan,
)

from data_engine.plan_executor import (
    execute_plan,
)

from data_engine.visualization import (
    create_visualization_spec,
)

from ai.planner import (
    create_analysis_plan,
)

from ai.fast_planner import (
    FastPlanner,
)

from data_engine.insight_engine import (
    build_deterministic_insights,
)

from data_engine.insight_generator import (
    build_insight_response,
)

from ai.insight_validator import (
    validate_insights,
)


router = APIRouter(
    prefix="/api/analyze",
    tags=["Analysis"],
)


class AnalysisRequest(BaseModel):
    question: str


@router.post("")
def analyze_dataset(
    request: AnalysisRequest,
):

    timings = {}

    # =========================================
    # 1. Validate question
    # =========================================

    with measure(
        "question_validation",
        timings,
    ):
        question = request.question.strip()

        if not question:
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty.",
            )

    # =========================================
    # 2. Load dataset
    # =========================================

    with measure(
        "dataset_loading",
        timings,
    ):
        df = get_walmart_data()

    # =========================================
    # 3. Generate metadata
    # =========================================

    with measure(
        "metadata_generation",
        timings,
    ):
        metadata = get_metadata(df)

    # =========================================
    # 4. FAST PLANNER
    # =========================================

    plan = None

    planner_type = None
    planner_fallback = False

    try:
        with measure(
            "fast_planning",
            timings,
        ):
            fast_planner = FastPlanner()

            plan = fast_planner.create_plan(
                question=question,
                metadata=metadata,
            )

    except Exception:
        # Fast Planner failure should never
        # break the complete request.

        plan = None

    # =========================================
    # 5. CLAUDE FALLBACK
    # =========================================

    if plan is not None:
        # -------------------------------------
        # Fast Planner succeeded
        # -------------------------------------

        planner_type = "fast"

        planner_fallback = False

    else:
        # -------------------------------------
        # Fast Planner could not safely
        # understand the question.
        #
        # Fall back to Claude.
        # -------------------------------------

        planner_type = "claude"

        planner_fallback = True

        try:
            with measure(
                "ai_planning",
                timings,
            ):
                # IMPORTANT:
                #
                # create_analysis_plan()
                # already returns AnalysisPlan.
                #
                # It does NOT return
                # AnalysisPlanResponse anymore.

                plan = create_analysis_plan(
                    user_question=question,
                    metadata=metadata,
                )

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"AI planning failed: {exc}",
            ) from exc

    # =========================================
    # 6. SAFETY CHECK
    # =========================================

    if plan is None:
        raise HTTPException(
            status_code=500,
            detail=("Planner could not create an analysis plan."),
        )

    # =========================================
    # 7. VALIDATE FINAL PLAN
    # =========================================
    #
    # BOTH planners reach this point.
    #
    # Fast:
    #
    # FastPlanner
    #     ↓
    # AnalysisPlan
    #     ↓
    # Validator
    #
    # Claude:
    #
    # Claude
    #     ↓
    # Adapter
    #     ↓
    # AnalysisPlan
    #     ↓
    # Validator
    #
    # =========================================

    try:
        with measure(
            "plan_validation",
            timings,
        ):
            validate_plan(
                df,
                plan,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(f"Invalid analysis plan: {exc}"),
        ) from exc

    # =========================================
    # 8. Execute analysis
    # =========================================

    try:
        with measure(
            "data_execution",
            timings,
        ):
            result = execute_plan(
                df,
                plan,
            )

            analysis_result = {
                "columns": result.columns.tolist(),
                "rows": result.to_dict(orient="records"),
                "row_count": len(result),
            }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(f"Analysis execution failed: {exc}"),
        ) from exc

    # =========================================
    # 9. Deterministic insight context
    # =========================================

    metric_column = f"{plan.aggregation}_{plan.metric}"

    with measure(
        "deterministic_insight_context",
        timings,
    ):
        insight_context = build_deterministic_insights(
            result=result,
            metric_column=metric_column,
            group_by=plan.group_by,
        )

    # =========================================
    # 10. Deterministic insights
    # =========================================

    insight_response = None
    insight_error = None

    try:
        with measure(
            "deterministic_insights",
            timings,
        ):
            insight_response = build_insight_response(
                context=insight_context,
            )

            validate_insights(
                insight_response,
                insight_context,
            )

    except Exception as exc:
        # Insight failure must not break
        # the actual analysis.

        insight_error = str(exc)

    # =========================================
    # 11. Visualization
    # =========================================

    if not plan.group_by:
        visualization_type = "table"

    else:
        visualization_type = plan.visualization or "table"

    visualization_title = None

    try:
        with measure(
            "visualization",
            timings,
        ):
            visualization_spec = create_visualization_spec(
                result=result,
                visualization_type=(visualization_type),
                title=visualization_title,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(f"Visualization creation failed: {exc}"),
        ) from exc

    # =========================================
    # 12. Total performance
    # =========================================

    timings["total"] = round(
        sum(
            value
            for value in timings.values()
            if isinstance(
                value,
                (int, float),
            )
        ),
        2,
    )

    # =========================================
    # 13. Return response
    # =========================================

    return {
        "success": True,
        "question": question,
        # -------------------------------------
        # Planner
        # -------------------------------------
        "planner": {
            "type": planner_type,
            "fallback": planner_fallback,
        },
        # -------------------------------------
        # Analysis result
        # -------------------------------------
        "data": analysis_result,
        # -------------------------------------
        # Insights
        # -------------------------------------
        "insights": (
            insight_response.model_dump()
            if insight_response is not None
            else {"insights": []}
        ),
        "insight_status": (
            "success" if insight_response is not None else "unavailable"
        ),
        "insight_source": "deterministic",
        "insight_error": insight_error,
        # -------------------------------------
        # Visualization
        # -------------------------------------
        "visualization": visualization_spec,
        # -------------------------------------
        # Final AnalysisPlan
        # -------------------------------------
        "plan": {
            "filters": [
                {
                    "column": condition.column,
                    "operator": condition.operator,
                    "value": condition.value,
                }
                for condition in plan.filters
            ],
            "group_by": plan.group_by,
            "metric": plan.metric,
            "aggregation": plan.aggregation,
            "sort": plan.sort,
            "sort_by": plan.sort_by,
            "limit": plan.limit,
            "visualization": plan.visualization,
            "time_granularity": (plan.time_granularity),
        },
        # -------------------------------------
        # Performance
        # -------------------------------------
        "performance": timings,
    }
