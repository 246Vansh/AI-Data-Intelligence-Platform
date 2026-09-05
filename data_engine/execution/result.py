from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class ExecutionResult:
    """
    Engine-neutral analytical result returned by ExecutionEngine.execute().

    This is the boundary type that replaces a raw pandas DataFrame as the
    ExecutionEngine contract's return value: every concrete engine
    (DuckDB, Pandas, or any future backend) must produce one of these
    instead of handing callers a backend-specific object.

    columns: ordered result column names.
    row_count: number of rows in the result (== len(dataframe)).
    truncated: True only when the execution logic that produced this
        result already knows for a fact that rows were cut off by a
        limit. False whenever that is not already known - never
        computed via an extra query/scan.
    _dataframe: the canonical, already filtered/aggregated/sorted/limited
        pandas DataFrame the execution engine produced. This is the
        single materialized representation ExecutionResult is built
        from - an internal implementation field, not part of the
        public contract; retrieve it via `to_dataframe()` rather than a
        rebuilt copy.

    Step 21: `rows` is NOT a stored field. It is a lazily computed,
    cached property - `dataframe.to_dict(orient="records")` only runs
    the first time `.rows` is actually accessed, and every later access
    returns that same cached list object. Constructing an ExecutionResult
    never performs that conversion up front, so a caller that only needs
    `columns`/`row_count`/`truncated`/`to_dataframe()` never pays for it.
    """

    columns: list[str]
    row_count: int
    truncated: bool
    _dataframe: pd.DataFrame = field(repr=False, compare=False)

    # Populated lazily by the `rows` property below via
    # object.__setattr__ (this dataclass is frozen). Never set at
    # construction time and never part of equality/repr - purely an
    # internal cache for the list[dict] conversion, not part of the
    # public contract.
    _rows_cache: list[dict] | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError(f"row_count must be >= 0, got {self.row_count}")

    @property
    def rows(self) -> list[dict]:
        """
        Result rows as plain dicts, in column order.

        Computed from the internal canonical DataFrame on first access
        and cached - every later access returns the exact same list
        object instead of re-converting the DataFrame.
        """
        if self._rows_cache is None:
            object.__setattr__(
                self,
                "_rows_cache",
                self._dataframe.to_dict(orient="records"),
            )

        return self._rows_cache

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return the canonical DataFrame this ExecutionResult was built
        from - the exact object the execution engine produced, never a
        copy and never reconstructed from `rows`.
        """
        return self._dataframe
