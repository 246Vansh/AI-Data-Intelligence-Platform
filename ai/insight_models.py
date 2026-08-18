from typing import Literal

from pydantic import BaseModel, Field


# =========================================================
# SINGLE-ROW EVIDENCE
# =========================================================


class InsightEvidence(BaseModel):
    column: str
    value: int | float
    row: dict


# =========================================================
# MULTI-ROW EVIDENCE
# =========================================================


class MultiRowEvidence(BaseModel):
    rows: list[dict]


# =========================================================
# COVERAGE EVIDENCE
# =========================================================


class CoverageEvidence(BaseModel):
    date_column: str
    frequency: str

    min_date: str
    max_date: str

    observed_periods: int
    expected_periods: int

    missing_periods: list[str]

    is_continuous: bool


# =========================================================
# INSIGHT
# =========================================================


class Insight(BaseModel):
    type: str
    title: str
    description: str

    evidence: InsightEvidence | MultiRowEvidence | CoverageEvidence | None = None


# =========================================================
# RESPONSE
# =========================================================


class InsightResponse(BaseModel):
    insights: list[Insight] = Field(default_factory=list)
