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

    limit: int | None = None

    visualization: str | None = None