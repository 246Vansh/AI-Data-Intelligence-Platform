from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

from ai.insights import generate_insights

from data_engine.insight_context import (
    build_insight_context,
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

    # =========================================
    # 1. Validate user question
    # =========================================

    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    # =========================================
    # 2. Load dataset
    # =========================================

    df = get_walmart_data()

    # =========================================
    # 3. Generate metadata
    # =========================================

    metadata = get_metadata(df)

    # =========================================
    # 4. Ask AI for analysis plan
    # =========================================

    try:
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
        }

    # =========================================
    # 6. Convert AI plan → Data Engine plan
    # =========================================

    try:
        plan = convert_to_analysis_plan(ai_plan)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # =========================================
    # 7. Validate plan
    # =========================================

    try:
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
    # 8. Execute plan
    # =========================================

    try:
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
    # 8. Insights
    # =========================================

    metric_column = f"{plan.aggregation}_{plan.metric}"

    insight_context = build_insight_context(
        result=result,
        metric_column=metric_column,
        group_by=plan.group_by,
    )

    insight_response = None
    insight_error = None

    try:
        insight_response = generate_insights(
            question=question,
            result=analysis_result,
            context=insight_context,
        )

    except Exception as exc:
        # Insights are an optional enrichment layer.
        # Analysis should still succeed if the AI
        # insight provider fails.

        insight_error = str(exc)

    # =========================================
    # 10. Visualization
    # =========================================

    if not plan.group_by:
        visualization_type = "table"

    else:
        visualization_type = plan.visualization or "table"

    visualization_title = None

    if ai_plan.visualization is not None:
        visualization_title = ai_plan.visualization.title

    try:
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
    # 11. Return final response
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
            "visualization": (plan.visualization),
        },
    }
