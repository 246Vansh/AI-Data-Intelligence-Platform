from dataclasses import dataclass, field
from typing import Any


@dataclass
class FilterCondition:
    column: str
    operator: str
    value: Any


@dataclass
class AnalysisPlan:
    filters: list[FilterCondition] = field(default_factory=list)

    group_by: list[str] = field(default_factory=list)

    metric: str | None = None

    aggregation: str = "sum"

    sort: str = "desc"

    sort_by: str = "metric"

    limit: int | None = None

    visualization: str | None = None

    # -----------------------------------------
    # Time analysis
    # -----------------------------------------

    time_granularity: str | None = None

    time_column: str | None = None


# =========================================================
# CANONICAL AGGREGATION DEFINITIONS
# =========================================================

AGGREGATION_ALIASES: dict[str, str] = {
    "sum": "sum",
    "total": "sum",
    "summation": "sum",
    "mean": "mean",
    "average": "mean",
    "avg": "mean",
    "median": "median",
    "min": "min",
    "minimum": "min",
    "lowest": "min",
    "max": "max",
    "maximum": "max",
    "highest": "max",
    "count": "count",
    "number": "count",
    "number_of": "count",
}

CANONICAL_AGGREGATIONS: set[str] = {
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "count",
}
