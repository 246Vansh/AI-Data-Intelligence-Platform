import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from data_engine.performance import measure
from data_engine.json_safety import sanitize_json, sanitize_records

from data_engine.dataset_manager import get_cached_on
from data_engine.dataset_registry import dataset_registry, DatasetNotFoundError
from data_engine.metadata import get_metadata

from data_engine.plan_validator import validate_plan

from data_engine.plan_executor import execute_plan_for_dataset

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


class _ColumnsView:
    """
    Minimal stand-in for the `df` parameter `plan_validator.validate_plan()`
    expects.

    validate_plan() only ever checks `column in df.columns` / `not in`
    - it never reads row data, dtypes, or anything else DataFrame-
    specific. Handing it this instead of a materialized DataFrame lets
    plan validation run off `Dataset.column_names` (a cheap schema
    lookup on every storage backend) rather than requiring a full raw
    dataset buffer just to check column membership - keeping this
    route storage/engine agnostic without touching plan_validator.py
    itself.
    """

    __slots__ = ("columns",)

    def __init__(self, columns):
        self.columns = columns


# =========================================================
# REQUEST MODEL
# =========================================================


QUESTION_MAX_LENGTH = 500

# Control characters (other than the whitespace pandas/AI prompts
# already tolerate) are stripped so a question can't smuggle null
# bytes or terminal/ANSI escapes into logs or the AI provider prompt.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class AnalysisRequest(BaseModel):
    dataset_id: str = Field(
        ...,
        description="ID of the dataset to analyze, as returned by /api/dataset/upload.",
    )

    question: str = Field(
        ...,
        max_length=QUESTION_MAX_LENGTH,
        description="Natural-language question about the specified dataset.",
    )

    @field_validator("question")
    @classmethod
    def strip_control_characters(cls, value: str) -> str:
        return _CONTROL_CHARS_RE.sub("", value)


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
    # 2. LOAD DATASET BY ID
    # =====================================================

    try:
        with measure(
            "dataset_loading",
            timings,
        ):
            try:
                dataset = dataset_registry.get(request.dataset_id)

            except DatasetNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"No dataset found for dataset_id: {request.dataset_id!r}",
                ) from exc

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
            metadata = get_cached_on(
                dataset,
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
                _ColumnsView(dataset.column_names),
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
            result = execute_plan_for_dataset(
                dataset,
                plan,
            )

            safe_rows = sanitize_records(result.to_dict(orient="records"))

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

        # build_insight_response() may have already succeeded before
        # validate_insights() rejected the result. Discard it so a
        # failed-validation insight is never reported as
        # insight_status: "success".
        insight_response = None

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
            sanitize_json(insight_response.model_dump())
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
