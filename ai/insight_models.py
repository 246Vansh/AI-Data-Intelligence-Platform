from typing import Any

from pydantic import BaseModel, Field


class InsightEvidence(BaseModel):
    column: str
    value: int | float
    row: dict[str, Any] | None = None


class Insight(BaseModel):
    type: str
    title: str
    description: str
    evidence: InsightEvidence | None = None


class InsightResponse(BaseModel):
    insights: list[Insight] = Field(default_factory=list)
