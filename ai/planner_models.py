from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


# =========================================================
# FILTER PLAN
# =========================================================


class FilterPlan(BaseModel):
    """
    Structured representation of a dataset filter.

    Example:

        {
            "column": "age",
            "operator": ">",
            "value": 30
        }
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    column: str
    operator: str
    value: str | int | float | bool


# =========================================================
# VISUALIZATION PLAN
# =========================================================


class VisualizationPlan(BaseModel):
    """
    Visualization requested by the planner.

    The adapter is responsible for normalizing and validating
    the visualization type against the Data Engine vocabulary.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    type: str
    title: str | None = None


# =========================================================
# ANALYSIS PLAN RESPONSE
# =========================================================


class AnalysisPlanResponse(BaseModel):
    """
    Canonical structured response produced by an AI planner.

    This model represents the boundary between the AI planning
    layer and the Data Engine.

    Planner states:

        success
            The user's request can be safely converted into
            an executable analysis plan.

        clarification
            The user's intent is related to the dataset, but
            the request is missing information required to
            safely create an analysis plan.

        invalid
            The request cannot be answered using the available
            dataset or is unrelated to dataset analysis.

    IMPORTANT:

    This model intentionally does NOT force the AI to use
    Data Engine aggregation terminology.

    For example, the AI may return:

        "average"
        "avg"
        "mean"

    The adapter converts those values into the canonical
    Data Engine representation before execution.

    Therefore:

        AI response
             ↓
        AnalysisPlanResponse
             ↓
        adapter
             ↓
        AnalysisPlan
             ↓
        validator
             ↓
        executor
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    # =====================================================
    # Planner status
    # =====================================================

    status: Literal[
        "success",
        "clarification",
        "invalid",
    ]

    # =====================================================
    # Explanation
    # =====================================================

    reason: str | None = None

    # =====================================================
    # Clarification question
    # =====================================================
    #
    # Used only when:
    #
    #     status == "clarification"
    #
    # Example:
    #
    # User:
    #     "show me the best one"
    #
    # clarification_question:
    #     "What would you like to compare: products,
    #      regions, or customers?"
    #
    # This prevents the system from guessing the user's
    # intended dimension or metric.
    # =====================================================

    clarification_question: str | None = None

    # =====================================================
    # Filters
    # =====================================================

    filters: list[FilterPlan] = Field(
        default_factory=list,
    )

    # =====================================================
    # Grouping
    # =====================================================

    group_by: list[str] = Field(
        default_factory=list,
    )

    # =====================================================
    # Metric
    # =====================================================

    metric: str | None = None

    # =====================================================
    # Aggregation
    # =====================================================

    aggregation: str | None = None

    # =====================================================
    # Sorting
    # =====================================================

    sort: str = "desc"

    sort_by: Literal[
        "metric",
        "time",
    ] = "metric"

    # =====================================================
    # Result limit
    # =====================================================

    limit: int | None = None

    # =====================================================
    # Time analysis
    # =====================================================

    time_granularity: (
        Literal[
            "day",
            "week",
            "month",
            "quarter",
            "year",
        ]
        | None
    ) = None

    time_column: str | None = None

    # =====================================================
    # Visualization
    # =====================================================

    visualization: VisualizationPlan | None = None
