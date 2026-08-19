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

from ai.adapter import (
    convert_to_analysis_plan,
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
    # 1. Validate user question
    # =========================================

    with measure("question_validation", timings):
        question = request.question.strip()

        if not question:
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty.",
            )

    # =========================================
    # 2. Load dataset
    # =========================================

    with measure("dataset_loading", timings):
        df = get_walmart_data()

    # =========================================
    # 3. Generate metadata
    # =========================================

    with measure("metadata_generation", timings):
        metadata = get_metadata(df)

    # =========================================
    # 4. AI planning
    # =========================================

    try:
        with measure("ai_planning", timings):
            ai_plan = create_analysis_plan(
                user_question=question,
                metadata=metadata,
            )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI planning failed: {exc}",
        ) from exc

    # =========================================
    # 5. Handle invalid AI request
    # =========================================

    if ai_plan.status == "invalid":
        return {
            "success": False,
            "question": question,
            "error": {
                "type": "invalid_request",
                "message": (
                    ai_plan.reason or "The requested analysis cannot be performed."
                ),
            },
            "ai_plan": ai_plan.model_dump(),
            "performance": timings,
        }

    # =========================================
    # 6. Convert AI plan
    # =========================================

    try:
        with measure("plan_conversion", timings):
            plan = convert_to_analysis_plan(
                ai_plan,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # =========================================
    # 7. Validate plan
    # =========================================

    try:
        with measure("plan_validation", timings):
            validate_plan(
                df,
                plan,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid analysis plan: {exc}",
        ) from exc

    # =========================================
    # 8. Execute analysis
    # =========================================

    try:
        with measure("data_execution", timings):
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
            detail=f"Analysis execution failed: {exc}",
        ) from exc

    # =========================================
    # 9. Build deterministic insight context
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
    # 10. Generate deterministic insights
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

            # -------------------------------------
            # Validate generated insights
            # -------------------------------------

            validate_insights(
                insight_response,
                insight_context,
            )

    except Exception as exc:
        # Insights are an enrichment layer.
        # The underlying analysis should still
        # succeed if insight generation fails.

        insight_error = str(exc)

    # =========================================
    # 11. Visualization
    # =========================================

    if not plan.group_by:
        visualization_type = "table"

    else:
        visualization_type = plan.visualization or "table"

    visualization_title = None

    if ai_plan.visualization is not None:
        visualization_title = ai_plan.visualization.title

    try:
        with measure(
            "visualization",
            timings,
        ):
            visualization_spec = create_visualization_spec(
                result=result,
                visualization_type=visualization_type,
                title=visualization_title,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(f"Visualization creation failed: {exc}"),
        ) from exc

    # =========================================
    # 12. Total request time
    # =========================================

    timings["total"] = round(
        sum(timings.values()),
        2,
    )

    # =========================================
    # 13. Return
    # =========================================

    return {
        "success": True,
        "question": question,
        "data": analysis_result,
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
        "visualization": visualization_spec,
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
            "limit": plan.limit,
            "visualization": plan.visualization,
        },
        "performance": timings,
    }
