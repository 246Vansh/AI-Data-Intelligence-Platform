from typing import Literal

from pydantic import BaseModel, Field


class FilterPlan(BaseModel):
    column: str
    operator: str
    value: str | int | float | bool


class VisualizationPlan(BaseModel):
    type: str
    title: str | None = None


class AnalysisPlanResponse(BaseModel):

    status: Literal[
        "success",
        "invalid",
    ]

    reason: str | None = None

    filters: list[FilterPlan] = Field(
        default_factory=list
    )

    group_by: list[str] = Field(
        default_factory=list
    )

    metric: str | None = None

    aggregation: str | None = None

    sort: str = "desc"

    limit: int | None = None

    visualization: VisualizationPlan | None = None