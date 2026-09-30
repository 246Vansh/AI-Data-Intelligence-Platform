"""
Semantic layer (Step 60A): a minimal, in-memory semantic view derived
from the existing dataset metadata.

The metadata produced by data_engine.metadata / data_engine.metadata_engine
remains the single source of truth. This module only *reshapes* it:
every value here is copied from metadata["columns"], metadata["time_columns"]
and metadata["time_column"] - nothing is inferred, renamed, or read from
the dataset itself, and no second metadata system is introduced.

Deliberately out of scope: calculated metrics, expressions, joins,
relationships, SQL generation, persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


METRIC_ROLE = "metric"
DIMENSION_ROLE = "dimension"
TIME_ROLE = "time"

# role -> default aggregation. Roles absent from this table (including
# "time") default to None.
_DEFAULT_AGGREGATIONS: dict[str, Optional[str]] = {
    METRIC_ROLE: "sum",
    DIMENSION_ROLE: "count",
}


@dataclass(frozen=True)
class SemanticField:
    name: str
    column: str
    role: str
    data_type: Any
    allowed_operations: tuple[Any, ...]
    default_aggregation: Optional[str]


@dataclass(frozen=True)
class SemanticDataset:
    dimensions: tuple[SemanticField, ...] = ()
    metrics: tuple[SemanticField, ...] = ()
    time_dimensions: tuple[SemanticField, ...] = ()
    primary_time_column: Optional[str] = None


def _build_field(column: str, column_metadata: Mapping[str, Any]) -> SemanticField:
    role = column_metadata.get("role")

    return SemanticField(
        # The physical column name, unchanged - no business naming.
        name=column,
        column=column,
        role=role,
        data_type=column_metadata.get("data_type"),
        allowed_operations=tuple(column_metadata.get("allowed_operations") or ()),
        default_aggregation=_DEFAULT_AGGREGATIONS.get(role),
    )


def build_semantic_dataset(metadata: Optional[Mapping[str, Any]]) -> SemanticDataset:
    """
    Derive a SemanticDataset from existing dataset metadata.

    Pure and deterministic: field order follows metadata["columns"]
    (dimensions, metrics) and metadata["time_columns"] (time dimensions).
    The input is never mutated. Missing or empty sections yield empty
    tuples / None rather than raising.
    """

    metadata = metadata or {}
    columns: Mapping[str, Any] = metadata.get("columns") or {}

    dimensions = []
    metrics = []

    for column, column_metadata in columns.items():
        role = (column_metadata or {}).get("role")

        if role == DIMENSION_ROLE:
            dimensions.append(_build_field(column, column_metadata))

        elif role == METRIC_ROLE:
            metrics.append(_build_field(column, column_metadata))

    # Time dimensions come from metadata["time_columns"] only; a listed
    # column without a per-column entry is skipped rather than invented.
    time_dimensions = [
        _build_field(column, columns[column])
        for column in metadata.get("time_columns") or ()
        if columns.get(column)
    ]

    return SemanticDataset(
        dimensions=tuple(dimensions),
        metrics=tuple(metrics),
        time_dimensions=tuple(time_dimensions),
        primary_time_column=metadata.get("time_column"),
    )
