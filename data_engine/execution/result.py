from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionResult:
    """
    Engine-neutral analytical result returned by ExecutionEngine.execute().

    This is the boundary type that replaces a raw pandas DataFrame as the
    ExecutionEngine contract's return value: every concrete engine
    (DuckDB, Pandas, or any future backend) must produce one of these
    instead of handing callers a backend-specific object. Fields are
    intentionally minimal - only what downstream callers (the analysis
    route, insight generation, visualization) actually need.

    columns: ordered result column names.
    rows: result rows as plain dicts, in column order.
    row_count: number of rows in `rows` (== len(rows)).
    truncated: True only when the execution logic that produced this
        result already knows for a fact that rows were cut off by a
        limit. False whenever that is not already known - never
        computed via an extra query/scan.
    """

    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError(f"row_count must be >= 0, got {self.row_count}")
