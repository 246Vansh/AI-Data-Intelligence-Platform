"""Step 18B: hard ceiling on an explicit plan.limit.

data_engine.plan_validator.validate_plan() already rejected a
non-integer or non-positive plan.limit. Before this step, a positive
integer limit had no upper bound at all and was honored verbatim all
the way through DuckDB's fetchdf(), ExecutionResult.rows, DataFrame
reconstruction, sanitization, and JSON serialization.

This suite verifies:
  - plan.limit=None still passes validation unchanged (DEFAULT_MAX_
    RESULT_ROWS continues to apply only inside the execution engines,
    not in the validator).
  - Every positive integer limit up to and including the new
    MAX_RESULT_ROWS ceiling (100_000) still passes validation
    unchanged.
  - A limit of MAX_RESULT_ROWS + 1 (and a much larger value) is now
    rejected with a dedicated, clear ValueError - never silently
    clamped.
  - The pre-existing non-integer / zero / negative limit errors are
    unchanged.
  - The DuckDB execution path honors a validated limit of exactly
    MAX_RESULT_ROWS (100_000) as-is, rather than silently falling back
    to DEFAULT_MAX_RESULT_ROWS (10_000) - proven via a query-string spy
    over a tiny fixture, never a large generated dataset.
"""

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.duckdb_query_engine import DEFAULT_MAX_RESULT_ROWS, MAX_RESULT_ROWS
from data_engine.plan_executor import execute_plan_for_dataset
from data_engine.plan_validator import validate_plan
from data_engine.storage import DuckDBStorage


class _ColumnsView:
    """Minimal df-shaped stand-in validate_plan() accepts (see
    backend.routes.analysis._ColumnsView) - it only ever checks
    `column in df.columns`."""

    def __init__(self, columns):
        self.columns = columns


def _make_plan(limit) -> AnalysisPlan:
    return AnalysisPlan(
        group_by=["region"],
        metric="quantity",
        aggregation="sum",
        limit=limit,
    )


def _validate(limit) -> None:
    validate_plan(
        _ColumnsView(["region", "quantity"]),
        _make_plan(limit),
        metadata=None,
    )


# =========================================================
# CEILING CONSTANT
# =========================================================


def test_max_result_rows_is_100_000_and_default_is_unchanged():
    assert MAX_RESULT_ROWS == 100_000
    assert DEFAULT_MAX_RESULT_ROWS == 10_000


# =========================================================
# VALID LIMITS - unchanged behavior
# =========================================================


@pytest.mark.parametrize("limit", [None, 5, 10_000, 100_000])
def test_valid_limits_still_pass_validation(limit):
    # Must not raise.
    _validate(limit)


# =========================================================
# NEW CEILING - explicit limits above MAX_RESULT_ROWS are rejected
# =========================================================


@pytest.mark.parametrize("limit", [100_001, 50_000_000])
def test_limits_above_ceiling_are_rejected(limit):
    with pytest.raises(ValueError, match=r"Limit must not exceed 100000 rows\."):
        _validate(limit)


def test_limit_is_not_silently_clamped():
    """A rejected limit must raise, not be coerced down to the ceiling
    or to DEFAULT_MAX_RESULT_ROWS."""

    plan = _make_plan(100_001)

    with pytest.raises(ValueError):
        validate_plan(_ColumnsView(["region", "quantity"]), plan, metadata=None)

    # The plan object itself is untouched - no silent rewrite.
    assert plan.limit == 100_001


# =========================================================
# PRE-EXISTING VALIDATION - unchanged
# =========================================================


def test_non_integer_limit_still_rejected():
    with pytest.raises(ValueError, match="Limit must be an integer."):
        _validate(3.5)


@pytest.mark.parametrize("limit", [0, -1, -100_000])
def test_zero_or_negative_limit_still_rejected(limit):
    with pytest.raises(ValueError, match="Limit must be greater than zero."):
        _validate(limit)


# =========================================================
# DUCKDB EXECUTION PATH - validated ceiling is honored as-is
# =========================================================


class _QuerySpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that records every query text passed to
    execute_df(), so the generated LIMIT clause can be inspected
    without needing a dataset anywhere near MAX_RESULT_ROWS in size."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.queries: list[str] = []

    def execute_df(self, query: str, params: list | None = None) -> pd.DataFrame:
        self.queries.append(query)
        return super().execute_df(query, params)


def _tiny_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "south", "east"],
            "quantity": [10, 20, 30],
        }
    )


def test_duckdb_path_honors_validated_max_result_rows_without_clamping():
    df = _tiny_dataframe()
    storage = _QuerySpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    plan = _make_plan(MAX_RESULT_ROWS)

    # Same contract boundary a real request goes through: validate,
    # then execute.
    validate_plan(_ColumnsView(dataset.column_names), plan, metadata=None)

    result = execute_plan_for_dataset(dataset, plan)

    assert storage.queries, "expected execute_df() to be called"
    # Exact trailing-clause match (not a substring check): "LIMIT
    # 10000" is itself a substring of "LIMIT 100000", so only an exact
    # match at the end of the query distinguishes "honored the
    # validated 100_000 ceiling" from "silently fell back to the
    # 10_000 default".
    assert storage.queries[-1].strip().endswith(f"LIMIT {MAX_RESULT_ROWS}")
    assert not storage.queries[-1].strip().endswith(f"LIMIT {DEFAULT_MAX_RESULT_ROWS}")

    # Tiny fixture has only 3 groups - the 100_000 ceiling is far above
    # the actual result size, exactly as it should be for a normal
    # request; it is the SQL LIMIT clause above, not the row count,
    # that proves the ceiling itself was honored rather than clamped.
    assert result.row_count == 3
