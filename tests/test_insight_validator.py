"""Step 26: MultiRowEvidence candidate-index optimization.

Covers ai/insight_validator.py, previously untested by any pytest module
(Step 25 audit finding). Focuses on two things:

  1. Correctness: the optimized _ResultRowIndex-backed _row_exists()
     must accept/reject exactly the same rows the original unindexed
     full scan would, across every semantic edge case _rows_match()
     defines (duplicates, None/NaN/pandas.NA/NaT, float tolerance,
     column ordering, missing/extra columns) - including the existing
     "NaN != NaN" quirk, which this step intentionally preserves
     rather than fixes.

  2. Performance: the indexed path is dramatically faster than the
     reference O(evidence x result) scan at a size where the old
     behavior is already measurably slow (Step 25 measured ~55s at
     N=10,000 for the unindexed scan).

A test-local `_reference_row_exists()` reproduces the pre-Step-26
unindexed algorithm exactly (this is NOT a production implementation -
it exists only so the optimized path can be checked against it).
"""

import math
import time

import pandas as pd
import pytest

from ai.insight_models import Insight, InsightResponse, MultiRowEvidence
from ai.insight_validator import (
    _ResultRowIndex,
    _row_exists,
    _rows_match,
    validate_insights,
)


# =========================================================
# TEST-LOCAL REFERENCE IMPLEMENTATION (pre-Step-26 behavior)
# =========================================================


def _reference_row_exists(target_row, result_rows):
    for result_row in result_rows:
        if _rows_match(target_row, result_row):
            return True
    return False


def _optimized_row_exists(target_row, result_rows):
    index = _ResultRowIndex(result_rows)
    return _row_exists(target_row, result_rows, index=index)


# =========================================================
# A. BASIC VALID MULTI-ROW EVIDENCE
# =========================================================


def test_valid_multi_row_evidence_passes():
    result_rows = [
        {"Date": "2020-01-01", "sum_sales": 100.0},
        {"Date": "2020-02-01", "sum_sales": 200.0},
        {"Date": "2020-03-01", "sum_sales": 300.0},
    ]

    response = InsightResponse(
        insights=[
            Insight(
                type="increasing",
                title="Sales increased",
                description="Sales increased across the observed periods.",
                evidence=MultiRowEvidence(rows=result_rows),
            )
        ]
    )

    context = {"result_rows": result_rows, "metric_column": "sum_sales"}

    # Should not raise.
    validate_insights(response, context)


# =========================================================
# B. MISSING EVIDENCE ROW IS REJECTED
# =========================================================


def test_evidence_row_not_in_result_is_rejected():
    result_rows = [
        {"Date": "2020-01-01", "sum_sales": 100.0},
        {"Date": "2020-02-01", "sum_sales": 200.0},
    ]

    fabricated_row = {"Date": "2020-03-01", "sum_sales": 999.0}

    response = InsightResponse(
        insights=[
            Insight(
                type="trend",
                title="Fake trend",
                description="Claims a row that was never in the result.",
                evidence=MultiRowEvidence(rows=[result_rows[0], fabricated_row]),
            )
        ]
    )

    context = {"result_rows": result_rows, "metric_column": "sum_sales"}

    with pytest.raises(ValueError, match="does not exist"):
        validate_insights(response, context)


# =========================================================
# C/D/E. DUPLICATE SEMANTICS - NO CONSUMPTION/MULTIPLICITY TRACKING
# =========================================================


def test_duplicate_result_rows_and_duplicate_evidence_rows_both_valid():
    # result_rows: A, A, B / evidence: A, A -> both evidence rows valid.
    row_a = {"k": "A", "v": 1}
    row_b = {"k": "B", "v": 2}
    result_rows = [row_a, dict(row_a), row_b]

    assert _optimized_row_exists(row_a, result_rows) is True
    assert _reference_row_exists(row_a, result_rows) is True


def test_single_result_row_satisfies_repeated_identical_evidence_rows():
    # result_rows: A, B / evidence: A, A -> both evidence rows still valid
    # (no consumption: one result row can satisfy unlimited identical
    # evidence rows).
    row_a = {"k": "A", "v": 1}
    row_b = {"k": "B", "v": 2}
    result_rows = [row_a, row_b]

    evidence_rows = [dict(row_a), dict(row_a)]

    for evidence_row in evidence_rows:
        assert _optimized_row_exists(evidence_row, result_rows) is True
        assert _reference_row_exists(evidence_row, result_rows) is True

    # And through the full validator (which requires >= 2 evidence rows).
    response = InsightResponse(
        insights=[
            Insight(
                type="trend",
                title="Repeated evidence",
                description="Same row asserted twice as evidence.",
                evidence=MultiRowEvidence(rows=evidence_rows),
            )
        ]
    )

    context = {"result_rows": result_rows, "metric_column": "v"}

    validate_insights(response, context)  # must not raise


# =========================================================
# F/G/H/I. NULL / NaN / pandas.NA / NaT SEMANTICS
# =========================================================


def test_none_vs_none_matches():
    assert _rows_match({"a": None}, {"a": None}) is True
    assert _optimized_row_exists({"a": None}, [{"a": None}]) is True


def test_none_vs_zero_does_not_match():
    assert _rows_match({"a": None}, {"a": 0}) is False
    assert _optimized_row_exists({"a": None}, [{"a": 0}]) is False


def test_nan_vs_nan_does_not_match_existing_quirk_preserved():
    # Step 25 finding: math.isclose(nan, nan) is False, so two NaN
    # values never match. This step intentionally preserves that
    # behavior rather than fixing it.
    nan_row = {"a": float("nan")}

    assert _rows_match(nan_row, dict(nan_row)) is False
    assert _reference_row_exists(nan_row, [dict(nan_row)]) is False
    assert _optimized_row_exists(nan_row, [dict(nan_row)]) is False


def test_pandas_na_vs_pandas_na_matches():
    assert _rows_match({"a": pd.NA}, {"a": pd.NA}) is True
    assert _optimized_row_exists({"a": pd.NA}, [{"a": pd.NA}]) is True


def test_pandas_na_vs_none_does_not_match():
    assert _rows_match({"a": pd.NA}, {"a": None}) is False
    assert _optimized_row_exists({"a": pd.NA}, [{"a": None}]) is False


def test_nat_vs_nat_matches():
    assert _rows_match({"a": pd.NaT}, {"a": pd.NaT}) is True
    assert _optimized_row_exists({"a": pd.NaT}, [{"a": pd.NaT}]) is True


# =========================================================
# J/K. FLOAT TOLERANCE
# =========================================================


def test_float_inside_tolerance_matches():
    assert _rows_match({"a": 1.0000001}, {"a": 1.0000002}) is True
    assert _optimized_row_exists({"a": 1.0000001}, [{"a": 1.0000002}]) is True


def test_float_outside_tolerance_does_not_match():
    assert _rows_match({"a": 1.0}, {"a": 1.1}) is False
    assert _optimized_row_exists({"a": 1.0}, [{"a": 1.1}]) is False


def test_float_near_tolerance_boundary_matches_reference_exactly():
    # A handful of values straddling NUMERIC_TOLERANCE (1e-6): whatever
    # _rows_match decides, the indexed path must agree - numeric
    # columns are never used to narrow candidates, so this must be
    # decided by the same isclose() call either way.
    base = 1.0
    deltas = [9e-7, 1e-6, 1.0000001e-6, 2e-6, 5e-7]

    result_rows = [{"a": base + delta} for delta in deltas]

    for target_delta in deltas:
        target_row = {"a": base + target_delta}

        expected = _reference_row_exists(target_row, result_rows)
        actual = _optimized_row_exists(target_row, result_rows)

        assert actual == expected


# =========================================================
# L/M/N. COLUMN SEMANTICS
# =========================================================


def test_column_order_is_irrelevant():
    row_a = {"a": 1, "b": "x"}
    row_b_reordered = {"b": "x", "a": 1}

    assert _rows_match(row_a, row_b_reordered) is True
    assert _optimized_row_exists(row_a, [row_b_reordered]) is True


def test_missing_column_is_rejected():
    target_row = {"a": 1, "b": "x"}
    result_rows = [{"a": 1}]  # missing "b"

    assert _rows_match(target_row, result_rows[0]) is False
    assert _optimized_row_exists(target_row, result_rows) is False
    assert _reference_row_exists(target_row, result_rows) is False


def test_extra_column_is_rejected():
    target_row = {"a": 1}
    result_rows = [{"a": 1, "b": "x"}]  # extra "b"

    assert _rows_match(target_row, result_rows[0]) is False
    assert _optimized_row_exists(target_row, result_rows) is False
    assert _reference_row_exists(target_row, result_rows) is False


# =========================================================
# O. EXISTING INVALID TREND EVIDENCE IS STILL REJECTED
# =========================================================


def test_invalid_increasing_trend_evidence_is_rejected():
    # Mirrors scripts/test_invalid_insight_evidence.py: evidence rows
    # in reverse (decreasing) order, claimed as an "increasing" trend.
    result_rows = [
        {"Date": "2010-03-01", "sum_Weekly_Sales": 181919802.5},
        {"Date": "2010-04-01", "sum_Weekly_Sales": 231412368.05},
        {"Date": "2010-12-01", "sum_Weekly_Sales": 288760532.72},
    ]

    fake_insight = Insight(
        type="increasing",
        title="Fake increasing trend",
        description="Sales increased continuously.",
        evidence=MultiRowEvidence(
            rows=[
                result_rows[2],
                result_rows[1],
                result_rows[0],
            ]
        ),
    )

    response = InsightResponse(insights=[fake_insight])
    context = {"result_rows": result_rows, "metric_column": "sum_Weekly_Sales"}

    with pytest.raises(ValueError):
        validate_insights(response, context)


# =========================================================
# P. REGRESSION: OPTIMIZED LOOKUP MATCHES REFERENCE ON A MIXED DATASET
# =========================================================


def test_optimized_matches_reference_on_mixed_dataset():
    """
    A deliberately heterogeneous dataset - mixed key sets, numeric and
    non-numeric columns, None/NaN/pandas.NA/NaT, near-duplicate floats,
    and duplicate rows - checked exhaustively (every row as a query
    against the full set) against the reference implementation.
    """

    result_rows = [
        {"Date": "2020-01-01", "region": "east", "sum_sales": 100.0},
        {"Date": "2020-01-01", "region": "east", "sum_sales": 100.0},  # exact dup
        {"Date": "2020-02-01", "region": "east", "sum_sales": 100.0000001},
        {"Date": "2020-02-01", "region": "west", "sum_sales": 250.5},
        {"Date": "2020-03-01", "region": "west", "sum_sales": float("nan")},
        {"Date": "2020-03-01", "region": None, "sum_sales": 300.0},
        {"Date": pd.NaT, "region": "east", "sum_sales": 400.0},
        {"Date": "2020-04-01", "region": pd.NA, "sum_sales": 500.0},
        # a different column set entirely
        {"Date": "2020-05-01", "sum_sales": 600.0},
        {"region": "east", "sum_sales": 700.0},
    ]

    queries = result_rows + [
        # a row that must not be found under any semantics
        {"Date": "2099-01-01", "region": "nowhere", "sum_sales": -1.0},
        # same shape as a real row but with a value far outside tolerance
        {"Date": "2020-01-01", "region": "east", "sum_sales": 999.0},
    ]

    index = _ResultRowIndex(result_rows)

    for query in queries:
        expected = _reference_row_exists(query, result_rows)
        actual = _row_exists(query, result_rows, index=index)
        assert actual == expected, f"mismatch for query={query!r}"


# =========================================================
# PERFORMANCE (separate from correctness - not timing-fragile)
# =========================================================


def _make_synthetic_rows(n: int) -> list[dict]:
    # One row per distinct period, mirroring the actual production
    # shape: a trend-evidence result is one row per group-by key
    # (e.g. one row per day/month/customer), not many rows repeating a
    # handful of period values. A low-cardinality "safe" column is a
    # separate, deliberately-tested pathological case below
    # (test_low_cardinality_safe_column_still_correct_but_degrades) -
    # this generator is for the common case the optimization targets.
    return [
        {"Date": f"2020-01-{i:06d}", "sum_metric": float(i) + 0.5}
        for i in range(n)
    ]


@pytest.mark.parametrize("n", [1_000, 5_000])
def test_optimized_validation_is_dramatically_faster_than_reference(n):
    """
    Not a strict wall-clock assertion (machine-speed dependent) - this
    compares the optimized path against the same reference
    implementation used for correctness above, run over the same
    dataset, and requires the optimized path to be substantially
    faster (a generous 5x margin, far below the ~quadratic vs.
    ~linear gap actually expected at these sizes).
    """

    rows = _make_synthetic_rows(n)

    start = time.perf_counter()
    for row in rows:
        assert _reference_row_exists(row, rows) is True
    reference_time = time.perf_counter() - start

    index = _ResultRowIndex(rows)

    start = time.perf_counter()
    for row in rows:
        assert _row_exists(row, rows, index=index) is True
    optimized_time = time.perf_counter() - start

    assert optimized_time * 5 < reference_time, (
        f"optimized ({optimized_time:.4f}s) was not substantially "
        f"faster than reference ({reference_time:.4f}s) at N={n}"
    )


def test_full_validate_insights_at_10000_rows_completes_quickly():
    """
    End-to-end (validate_insights(), not just _row_exists()) at
    N=10,000 - the size Step 25 measured at ~55s for the unindexed
    scan. A generous bound (not a fragile sub-second assertion) proves
    the optimized path no longer exhibits that behavior.
    """

    n = 10_000
    result_rows = _make_synthetic_rows(n)

    response = InsightResponse(
        insights=[
            Insight(
                type="trend",
                title="Mixed trend",
                description="Synthetic large trend evidence.",
                evidence=MultiRowEvidence(rows=result_rows),
            )
        ]
    )

    context = {"result_rows": result_rows, "metric_column": "sum_metric"}

    start = time.perf_counter()
    validate_insights(response, context)
    elapsed = time.perf_counter() - start

    # Step 25 measured ~55s for the unindexed scan at this size; a
    # generous 10s bound comfortably proves the quadratic behavior is
    # gone without pinning an exact, machine-dependent number.
    assert elapsed < 10.0, f"validate_insights took {elapsed:.2f}s at N={n}"


def test_low_cardinality_safe_column_still_correct_but_may_degrade():
    """
    Pathological case called out explicitly in the Step 26 spec: if
    every "safe" (non-numeric) column has very low cardinality (here,
    only 2 distinct values across 2,000 rows), the index cannot narrow
    candidates much and this degrades toward the original full scan
    for that bucket. That is an accepted tradeoff - the requirement is
    that correctness is still exactly preserved, not that every
    dataset shape gets a dramatic speedup. This is therefore a
    correctness assertion, not a performance one.
    """

    n = 2_000
    result_rows = [
        {"category": "a" if i % 2 == 0 else "b", "sum_metric": float(i)}
        for i in range(n)
    ]

    index = _ResultRowIndex(result_rows)

    for row in result_rows:
        assert _row_exists(row, result_rows, index=index) == _reference_row_exists(
            row, result_rows
        )
