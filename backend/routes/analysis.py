import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data_engine.performance import measure

from backend.dependencies import (
    get_current_dataset,
    has_dataset_loaded,
)

from data_engine.dataset_manager import dataset_manager
from data_engine.metadata import get_metadata

from data_engine.plan_validator import validate_plan

from data_engine.plan_executor import execute_plan

from data_engine.visualization import create_visualization_spec

from ai.planner import create_analysis_plan
from ai.adapter import AnalysisClarificationError

from ai.fast_planner import FastPlanner

from data_engine.insight_engine import build_deterministic_insights

from data_engine.insight_generator import build_insight_response

from ai.insight_validator import validate_insights


router = APIRouter(
    prefix="/api/analyze",
    tags=["Analysis"],
)


# =========================================================
# REQUEST MODEL
# =========================================================


class AnalysisRequest(BaseModel):
    question: str


# =========================================================
# JSON SAFETY
# =========================================================


def make_json_safe(value):
    """
    Convert non-JSON-safe floating-point values into None.

    Protects API responses from:
        NaN
        +Infinity
        -Infinity
    """

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


# =========================================================
# ANALYSIS ENDPOINT
# =========================================================


@router.post("")
def analyze_dataset(
    request: AnalysisRequest,
):
    timings = {}

    # =====================================================
    # 1. VALIDATE QUESTION
    # =====================================================

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

    # =====================================================
    # 2. LOAD ACTIVE DATASET
    # =====================================================

    try:
        with measure(
            "dataset_loading",
            timings,
        ):
            if not has_dataset_loaded():
                raise HTTPException(
                    status_code=404,
                    detail="No dataset has been uploaded.",
                )

            df = get_current_dataset()

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset loading failed: {exc}",
        ) from exc

    # =====================================================
    # 3. GENERATE / LOAD METADATA
    # =====================================================

    try:
        with measure(
            "metadata_generation",
            timings,
        ):
            metadata = dataset_manager.get_cached(
                "metadata",
                get_metadata,
            )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Metadata generation failed: {exc}",
        ) from exc

    # =====================================================
    # 4. FAST PLANNER
    # =====================================================

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
        # Fast planner is intentionally conservative.
        #
        # If anything goes wrong, fall back to the AI planner.
        plan = None

    # =====================================================
    # 5. AI PLANNER FALLBACK
    # =====================================================

    if plan is not None:
        planner_type = "fast"
        planner_fallback = False

    else:
        planner_type = "ai"
        planner_fallback = True

        try:
            with measure(
                "ai_planning",
                timings,
            ):
                plan = create_analysis_plan(
                    user_question=question,
                    metadata=metadata,
                )

        except AnalysisClarificationError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        except Exception as exc:
            message = str(exc)

            if "API_KEY" in message.upper():
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "This question requires the AI planner, "
                        "but no AI API key is configured on the "
                        "server. Configure the required AI API key "
                        "in the backend environment."
                    ),
                ) from exc

            raise HTTPException(
                status_code=500,
                detail=f"AI planning failed: {exc}",
            ) from exc

    # =====================================================
    # 6. ENSURE A PLAN EXISTS
    # =====================================================

    if plan is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "The system could not create a valid analysis plan for this question."
            ),
        )

    # =====================================================
    # 7. VALIDATE FINAL PLAN
    # =====================================================

    try:
        with measure(
            "plan_validation",
            timings,
        ):
            validate_plan(
                df,
                plan,
                metadata,
            )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid analysis plan: {exc}",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Plan validation failed: {exc}",
        ) from exc

    # =====================================================
    # 8. EXECUTE ANALYSIS PLAN
    # =====================================================

    try:
        with measure(
            "data_execution",
            timings,
        ):
            result = execute_plan(
                df,
                plan,
            )

            safe_rows = [
                {key: make_json_safe(value) for key, value in row.items()}
                for row in result.to_dict(orient="records")
            ]

            analysis_result = {
                "columns": result.columns.tolist(),
                "rows": safe_rows,
                "row_count": len(result),
            }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis execution failed: {exc}",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected analysis execution error: {exc}",
        ) from exc

    # =====================================================
    # 9. BUILD DETERMINISTIC INSIGHT CONTEXT
    # =====================================================

    metric_column = None

    if plan.metric is not None and plan.aggregation is not None:
        metric_column = f"{plan.aggregation}_{plan.metric}"

    try:
        with measure(
            "deterministic_insight_context",
            timings,
        ):
            insight_context = build_deterministic_insights(
                result=result,
                metric_column=metric_column,
                group_by=plan.group_by,
            )

    except Exception as exc:
        # Insight context is supplementary.
        #
        # Do not fail the actual analysis if it cannot
        # be generated.

        insight_context = {}
        insight_error = f"Insight context generation failed: {exc}"

    else:
        insight_error = None

    # =====================================================
    # 10. GENERATE DETERMINISTIC INSIGHTS
    # =====================================================

    insight_response = None

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
        if insight_error is None:
            insight_error = str(exc)

    # =====================================================
    # 11. VISUALIZATION
    # =====================================================

    # Always initialize the title.
    visualization_title = None

    # Global aggregation does not have a grouping
    # dimension, therefore a table is safest.

    if not plan.group_by:
        visualization_type = "table"

    else:
        visualization_type = plan.visualization or "table"

    try:
        with measure(
            "visualization",
            timings,
        ):
            try:
                visualization_spec = create_visualization_spec(
                    result=result,
                    visualization_type=visualization_type,
                    title=visualization_title,
                )

            except ValueError:
                # Chart generation failed.
                # Return a table instead.

                visualization_spec = create_visualization_spec(
                    result=result,
                    visualization_type="table",
                    title=visualization_title,
                )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Visualization generation failed: {exc}",
        ) from exc

    # =====================================================
    # 12. TOTAL PERFORMANCE
    # =====================================================

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

    # =====================================================
    # 13. FINAL RESPONSE
    # =====================================================

    return {
        "success": True,
        "question": question,
        # -------------------------------------------------
        # Planner
        # -------------------------------------------------
        "planner": {
            "type": planner_type,
            "fallback": planner_fallback,
        },
        # -------------------------------------------------
        # Analysis result
        # -------------------------------------------------
        "data": analysis_result,
        # -------------------------------------------------
        # Insights
        # -------------------------------------------------
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
        # -------------------------------------------------
        # Visualization
        # -------------------------------------------------
        "visualization": visualization_spec,
        # -------------------------------------------------
        # Final canonical AnalysisPlan
        # -------------------------------------------------
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
            "time_column": plan.time_column,
            "time_granularity": (plan.time_granularity),
        },
        # -------------------------------------------------
        # Performance
        # -------------------------------------------------
        "performance": timings,
    }
