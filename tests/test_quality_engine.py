"""Phase 2 / Step 6A: QualityEngine - dataset quality analysis
(duplicate rows, missing values, constant columns, high cardinality,
IQR numeric outliers) natively behind a storage-aware engine boundary,
mirroring data_engine.profiling's ProfilingEngine pattern.

Verifies:
  - QualityEngine is a genuine abstract contract.
  - PandasQualityEngine and DuckDBQualityEngine both satisfy it.
  - select_quality_engine_for()/check_quality_for_dataset() route
    purely on the Dataset's own storage type.
  - Full issue-set parity between the two engines across duplicate
    rows, missing values, constant columns, high cardinality, and IQR
    outliers.
  - The empty-dataset short-circuit response is preserved.
  - DuckDBQualityEngine never calls storage.to_dataframe() - proven
    with a spy storage subclass.
  - data_engine.data_quality (the unmodified Pandas baseline) still
    works standalone.
"""

import pandas as pd
import pytest

from data_engine.data_quality import check_data_quality
from data_engine.dataset import Dataset
from data_engine.quality import (
    DuckDBQualityEngine,
    PandasQualityEngine,
    QualityEngine,
    check_quality_for_dataset,
    select_quality_engine_for,
)
from data_engine.storage import DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    # 24 rows: one duplicate pair, a missing-heavy column, a constant
    # column, a high-cardinality column, and a numeric column with
    # real quartile spread plus one clear IQR outlier - large enough
    # that pandas' and DuckDB's quantile interpolation agree on which
    # rows are outliers.
    n = 24
    amounts = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0] * (n // 6)
    amounts[-1] = 100000.0

    return pd.DataFrame(
        {
            "region": (["north", "south"] * (n // 2)),
            "flag": ["y"] * n,  # constant column
            "notes": [None if i % 3 == 0 else f"note-{i}" for i in range(n)],  # missing
            "customer_id": [f"cust-{i}" for i in range(n)],  # high cardinality
            "amount": amounts,  # one clear outlier against real spread
        }
    )


def _make_duplicate_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1, 1, 2, 3],
            "b": ["x", "x", "y", "z"],
        }
    )


class _SpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage that records whether to_dataframe() was called."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.to_dataframe_calls: list[bool] = []

    def to_dataframe(self) -> pd.DataFrame:
        self.to_dataframe_calls.append(True)
        return super().to_dataframe()


# =========================================================
# CONTRACT / ABSTRACTNESS
# =========================================================


def test_quality_engine_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        QualityEngine()


def test_pandas_quality_engine_is_a_quality_engine():
    assert isinstance(PandasQualityEngine(), QualityEngine)


def test_duckdb_quality_engine_is_a_quality_engine():
    assert isinstance(DuckDBQualityEngine(), QualityEngine)


# =========================================================
# SELECTOR - routes by storage type
# =========================================================


def test_selector_picks_duckdb_engine_for_duckdb_storage():
    dataset = Dataset(storage=DuckDBStorage(_make_dataframe()))
    assert isinstance(select_quality_engine_for(dataset), DuckDBQualityEngine)


def test_selector_picks_pandas_engine_for_pandas_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    assert isinstance(select_quality_engine_for(dataset), PandasQualityEngine)


# =========================================================
# ISSUE-SET PARITY - identical synthetic dataset, both engines
# =========================================================


def _issue_keys(issues):
    return {(issue["type"], issue.get("column")) for issue in issues}


def test_quality_parity_status_and_issue_count():
    df = _make_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert pandas_quality["status"] == duckdb_quality["status"]
    assert pandas_quality["issue_count"] == duckdb_quality["issue_count"]


def test_quality_parity_issue_types_and_columns():
    df = _make_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    assert _issue_keys(pandas_quality["issues"]) == _issue_keys(duckdb_quality["issues"])


def test_quality_parity_detects_each_issue_type():
    df = _make_dataframe()
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    keys = _issue_keys(duckdb_quality["issues"])
    assert ("missing_values", "notes") in keys
    assert ("constant_column", "flag") in keys
    assert ("high_cardinality", "customer_id") in keys
    assert ("numeric_outliers", "amount") in keys


def test_quality_parity_duplicate_rows():
    df = _make_duplicate_dataframe()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_quality = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    pandas_dup = next(i for i in pandas_quality["issues"] if i["type"] == "duplicate_rows")
    duckdb_dup = next(i for i in duckdb_quality["issues"] if i["type"] == "duplicate_rows")

    assert pandas_dup["count"] == duckdb_dup["count"] == 1


# =========================================================
# EMPTY-DATASET SHORT-CIRCUIT PRESERVED
# =========================================================


def test_duckdb_quality_empty_dataset_response():
    # DuckDBStorage rejects an empty DataFrame at construction time
    # (like PandasStorage) - build a from_parquet-style zero-row VIEW
    # instead to exercise the empty-result path DuckDBQualityEngine
    # itself must still handle.
    import os
    import tempfile

    df = pd.DataFrame({"a": [1]})
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "empty.parquet")
        df.iloc[0:0].to_parquet(path)
        storage = DuckDBStorage.from_parquet(path)
        dataset = Dataset(storage=storage)

        result = check_quality_for_dataset(dataset)

    assert result["status"] == "invalid"
    assert result["issue_count"] == 1
    assert result["issues"][0]["type"] == "empty_dataset"


# =========================================================
# BOUNDARY DISCIPLINE - zero to_dataframe() for DuckDB quality
# =========================================================


def test_duckdb_quality_never_calls_to_dataframe():
    df = _make_dataframe()
    storage = _SpyDuckDBStorage(df)
    dataset = Dataset(storage=storage)

    check_quality_for_dataset(dataset)

    assert storage.to_dataframe_calls == []


def test_duckdb_quality_engine_rejects_non_duckdb_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()))

    with pytest.raises(TypeError):
        DuckDBQualityEngine().check_quality(dataset)


# =========================================================
# EXISTING BASELINE MODULE UNTOUCHED
# =========================================================


def test_legacy_data_quality_module_still_works_unmodified():
    df = _make_dataframe()
    quality = check_data_quality(df)

    assert quality["status"] in {"healthy", "info", "warning", "error"}


# =========================================================
# R3 - EXACT QUARTILES BATCHED IN GROUPS OF FOUR COLUMNS
# =========================================================


class _QuerySpyDuckDBStorage(DuckDBStorage):
    """DuckDBStorage recording every execute_one() query and its row."""

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__(dataframe)
        self.executed: list[tuple[str, tuple]] = []

    def execute_one(self, query: str, params=None):
        row = super().execute_one(query, params)
        self.executed.append((query, row))
        return row


def _quartile_queries(storage: _QuerySpyDuckDBStorage) -> list[tuple[str, tuple]]:
    return [(q, row) for q, row in storage.executed if "quantile_cont" in q]


def _numeric_frame(numeric_count: int, n: int = 40) -> pd.DataFrame:
    # Interleave a string column between numeric ones so batching must
    # follow numeric-column order, not raw column order. Each numeric
    # column gets a different spread and one clear high outlier.
    data: dict[str, list] = {}

    for index in range(numeric_count):
        values = [float((i * (index + 3)) % 17) for i in range(n)]
        values[index % n] = 10_000.0 + index
        data[f"num_{index}"] = values
        data[f"label_{index}"] = [f"l{i % 3}" for i in range(n)]

    return pd.DataFrame(data)


def _single_query_baseline(storage: DuckDBStorage, numeric_columns: list[str]):
    """
    The pre-R3 algorithm verbatim: one fused query of scalar
    quantile_cont(col, 0.25)/quantile_cont(col, 0.75) pairs across
    every numeric column, then one fused outlier COUNT(*) FILTER query.
    """
    from data_engine.quality.duckdb_quality import _quote_identifier

    table = _quote_identifier(storage.table_name)
    parts = []

    for index, column in enumerate(numeric_columns):
        quoted = _quote_identifier(column)
        parts.append(f"quantile_cont({quoted}, 0.25) AS q1_{index}")
        parts.append(f"quantile_cont({quoted}, 0.75) AS q3_{index}")

    row = storage.connection.execute(f"SELECT {', '.join(parts)} FROM {table}").fetchone()
    quartiles = {
        column: (row[index * 2], row[index * 2 + 1])
        for index, column in enumerate(numeric_columns)
    }

    bounds = {}

    for column, (q1, q3) in quartiles.items():
        if q1 is None or q3 is None or q3 - q1 == 0:
            continue
        iqr = q3 - q1
        bounds[column] = (q1 - 1.5 * iqr, q3 + 1.5 * iqr)

    counts = {}

    if bounds:
        outlier_parts = [
            f"COUNT(*) FILTER (WHERE {_quote_identifier(c)} < {lo!r} "
            f"OR {_quote_identifier(c)} > {hi!r})"
            for c, (lo, hi) in bounds.items()
        ]
        outlier_row = storage.connection.execute(
            f"SELECT {', '.join(outlier_parts)} FROM {table}"
        ).fetchone()
        counts = {c: int(v) for c, v in zip(bounds.keys(), outlier_row)}

    return quartiles, counts


@pytest.mark.parametrize(
    "numeric_count, expected_queries",
    [(1, 1), (4, 1), (5, 2), (9, 3)],
)
def test_quartiles_batched_in_groups_of_four(numeric_count, expected_queries):
    storage = _QuerySpyDuckDBStorage(_numeric_frame(numeric_count))

    check_quality_for_dataset(Dataset(storage=storage))

    queries = _quartile_queries(storage)
    assert len(queries) == expected_queries

    # Every numeric column appears in exactly one quartile query, in
    # numeric-column order, and each uses the single list-form state.
    seen = []
    for query, _ in queries:
        assert query.count("quantile_cont(") <= 4
        assert "[0.25, 0.75]" in query
        seen.extend(
            name for name in (f"num_{i}" for i in range(numeric_count))
            if f'"{name}"' in query
        )
    assert seen == [f"num_{i}" for i in range(numeric_count)]


def test_no_quartile_query_without_numeric_columns():
    storage = _QuerySpyDuckDBStorage(
        pd.DataFrame({"a": ["x", "y", "z"], "flag": [True, False, True]})
    )

    check_quality_for_dataset(Dataset(storage=storage))

    assert _quartile_queries(storage) == []


def test_batched_quartiles_and_outliers_match_single_query_baseline():
    numeric_count = 9
    df = _numeric_frame(numeric_count)
    df["all_null"] = [None] * len(df)
    df["all_null"] = df["all_null"].astype("float64")
    df["constant_num"] = [7] * len(df)
    with_nulls = [None if i % 4 == 0 else float(i) for i in range(len(df))]
    with_nulls[1] = 5_000.0
    df["with_nulls"] = with_nulls
    numeric_columns = [f"num_{i}" for i in range(numeric_count)] + [
        "all_null",
        "constant_num",
        "with_nulls",
    ]

    storage = _QuerySpyDuckDBStorage(df)
    result = check_quality_for_dataset(Dataset(storage=storage))

    baseline_quartiles, baseline_counts = _single_query_baseline(storage, numeric_columns)

    # Quartile values: the batched list-form results, keyed by column,
    # are exactly (==, including type) the pre-R3 scalar results.
    batched_quartiles = {}
    queries = _quartile_queries(storage)
    assert len(queries) == 3
    for query, row in queries:
        columns_in_batch = [c for c in numeric_columns if f'"{c}"' in query]
        for column, pair in zip(columns_in_batch, row):
            batched_quartiles[column] = (None, None) if pair is None else tuple(pair)

    assert batched_quartiles == baseline_quartiles
    assert baseline_quartiles["all_null"] == (None, None)
    assert baseline_quartiles["constant_num"][0] == baseline_quartiles["constant_num"][1]

    # Outlier counts reported by the engine equal the baseline's.
    reported = {
        issue["column"]: issue["count"]
        for issue in result["issues"]
        if issue["type"] == "numeric_outliers"
    }
    assert reported == {c: n for c, n in baseline_counts.items() if n > 0}
    assert "all_null" not in reported
    assert "constant_num" not in reported
    assert reported["with_nulls"] == 1

    # The outlier COUNT(*) FILTER query is still a single fused query.
    filter_queries = [q for q, _ in storage.executed if "COUNT(*) FILTER" in q]
    assert len(filter_queries) == 1


def _mixed_type_frame(n: int = 40) -> pd.DataFrame:
    # More than four numeric columns, interleaved with string and
    # boolean columns, covering integer, float, all-null, constant and
    # partly-null numeric inputs.
    ints = [i % 10 for i in range(n)]
    ints[3] = 500
    floats = [float(i % 7) + 0.5 for i in range(n)]
    floats[5] = -900.0
    big = [i * 1000 for i in range(n)]
    big[0] = 10**9
    partly_null = [None if i % 5 == 0 else float(i % 9) for i in range(n)]
    partly_null[2] = 777.0

    return pd.DataFrame(
        {
            "label": [f"row-{i % 4}" for i in range(n)],
            "int_col": ints,
            "flag": [i % 2 == 0 for i in range(n)],  # boolean: never quantiled
            "float_col": floats,
            "all_null": pd.Series([None] * n, dtype="float64"),
            "category": ["a", "b"] * (n // 2),
            "constant_num": [3] * n,
            "big_int": big,
            "partly_null": partly_null,
            "verified": [True] * n,  # constant boolean
        }
    )


def test_pandas_duckdb_parity_with_more_than_four_numeric_columns():
    df = _mixed_type_frame()

    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(df)))
    duckdb_storage = _QuerySpyDuckDBStorage(df)
    duckdb_quality = check_quality_for_dataset(Dataset(storage=duckdb_storage))

    def ordered(issues):
        return [(i["type"], i.get("column"), i.get("count")) for i in issues]

    assert ordered(duckdb_quality["issues"]) == ordered(pandas_quality["issues"])
    assert duckdb_quality["status"] == pandas_quality["status"]
    assert duckdb_quality["issue_count"] == pandas_quality["issue_count"]

    # 6 numeric columns -> 2 quartile batches; booleans never quantiled.
    queries = _quartile_queries(duckdb_storage)
    assert len(queries) == 2
    assert not any('"flag"' in q or '"verified"' in q for q, _ in queries)

    outlier_columns = {
        i["column"] for i in duckdb_quality["issues"] if i["type"] == "numeric_outliers"
    }
    assert outlier_columns == {"int_col", "float_col", "big_int", "partly_null"}


def test_issue_order_follows_columns_when_numeric_and_text_interleave():
    df = _mixed_type_frame()

    result = check_quality_for_dataset(Dataset(storage=DuckDBStorage(df)))

    # Column order first, then missing -> constant -> high cardinality
    # -> outliers within a column - independent of which quartile
    # batch each numeric column was computed in (int_col/float_col/
    # all_null/constant_num in batch 1, big_int/partly_null in batch 2).
    assert [(i["type"], i.get("column")) for i in result["issues"]] == [
        ("numeric_outliers", "int_col"),
        ("numeric_outliers", "float_col"),
        ("missing_values", "all_null"),
        ("constant_column", "all_null"),
        ("constant_column", "constant_num"),
        ("high_cardinality", "big_int"),
        ("numeric_outliers", "big_int"),
        ("missing_values", "partly_null"),
        ("numeric_outliers", "partly_null"),
        ("constant_column", "verified"),
    ]


def test_list_form_quartiles_equal_scalar_form_for_decimal_columns():
    # SQL-level check: for DECIMAL input the list form returns the same
    # Decimal values (same type and scale) as the scalar form, including
    # NULL when every value is NULL.
    import decimal

    df = pd.DataFrame(
        {
            "dec": [decimal.Decimal(f"{i}.{i % 10}") for i in range(1, 30)],
            "dec_nulls": [
                None if i % 3 == 0 else decimal.Decimal(f"{i}.25") for i in range(1, 30)
            ],
        }
    )
    storage = DuckDBStorage(df)
    assert storage.schema_info()["dec"].startswith("DECIMAL")
    table = f'"{storage.table_name}"'

    for column in ("dec", "dec_nulls"):
        q1, q3, pair = storage.execute_one(
            f'SELECT quantile_cont("{column}", 0.25), quantile_cont("{column}", 0.75), '
            f'quantile_cont("{column}", [0.25, 0.75]) FROM {table}'
        )
        assert [q1, q3] == list(pair)
        assert all(isinstance(v, decimal.Decimal) for v in (q1, q3, *pair))

    empty = storage.execute_one(
        f'SELECT quantile_cont("dec", 0.25), quantile_cont("dec", [0.25, 0.75]) '
        f"FROM {table} WHERE false"
    )
    assert empty == (None, None)


# =========================================================
# DECIMAL COLUMNS - exact Decimal IQR bounds
# =========================================================


from decimal import Decimal  # noqa: E402


def _boundary_values(q1: str, q3: str, eps: str) -> tuple[list[Decimal], Decimal, Decimal]:
    """
    41 values whose exact quartiles are q1 (sorted index 10) and q3
    (index 30) - no interpolation - with the exact lower/upper IQR
    bound present (not an outlier, comparisons are strict) and one
    value one `eps` step beyond each bound (outliers). Exactly 2
    outliers; any rounding of the bounds flips one of the edge values.
    """
    from decimal import localcontext

    # The 31-digit DECIMAL(38,10) case exceeds Python's default 28-digit
    # context, so the expected values need the same headroom the
    # engine itself uses.
    with localcontext() as context:
        context.prec = 80
        q1_d, q3_d, eps_d = Decimal(q1), Decimal(q3), Decimal(eps)
        spread = Decimal("1.5") * (q3_d - q1_d)
        lower, upper = q1_d - spread, q3_d + spread
        # Every case's bounds lie on the column grid; express them at
        # the column's scale (1.5 * adds a trailing-zero digit) so they
        # are storable, and prove the quantize is lossless.
        on_grid_lower, on_grid_upper = lower.quantize(eps_d), upper.quantize(eps_d)
        assert (on_grid_lower, on_grid_upper) == (lower, upper)
        lower, upper = on_grid_lower, on_grid_upper
        mid = (q1_d + q3_d) / 2
        values = (
            [lower - eps_d, lower]
            + [q1_d - eps_d] * 8
            + [q1_d]
            + [mid.quantize(eps_d)] * 19
            + [q3_d]
            + [q3_d + eps_d] * 8
            + [upper, upper + eps_d]
        )
    assert len(values) == 41
    return values, lower, upper


# (arrow precision, scale, q1, q3, eps) - every bound lands exactly on
# the column's own scale. The DECIMAL(38,10) case has 31 significant
# digits: beyond both float64 and Python's default 28-digit context.
# The DECIMAL(38,38) cases reproduce the R3c defect: a bare 38-digit
# fractional literal ("0." + 38 digits) is typed DOUBLE by DuckDB, so
# the value one 1e-38 step beyond the bound compared equal to it and
# the outlier was missed; they cover positive and negative fractions
# (the negative case also has a negative upper bound, -0.25).
_SCALE_38 = 38
_E38 = "0." + "0" * 37 + "1"
_DECIMAL_CASES = [
    pytest.param(9, 2, "10.00", "20.10", "0.01", id="DECIMAL(9,2)"),
    pytest.param(9, 2, "-40.00", "-30.00", "0.01", id="DECIMAL(9,2)-negative-upper"),
    pytest.param(18, 4, "1234.5678", "2345.6790", "0.0001", id="DECIMAL(18,4)"),
    pytest.param(
        38,
        10,
        "100000000000000000001.0000000000",
        "100000000000000000003.0000000002",
        "0.0000000001",
        id="DECIMAL(38,10)",
    ),
    pytest.param(
        38,
        _SCALE_38,
        "0.4" + "0" * 37,
        "0.5" + "0" * 37,
        _E38,
        id="DECIMAL(38,38)",
    ),
    pytest.param(
        38,
        _SCALE_38,
        "-0.5" + "0" * 37,
        "-0.4" + "0" * 37,
        _E38,
        id="DECIMAL(38,38)-negative",
    ),
]


def _decimal_storage(tmp_path, columns: dict) -> DuckDBStorage:
    """Build a DuckDBStorage from Parquet so DECIMAL(p,s) is exact."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "decimals.parquet"
    pq.write_table(pa.table(columns), str(path))
    return DuckDBStorage.from_parquet(str(path))


@pytest.mark.parametrize("precision, scale, q1, q3, eps", _DECIMAL_CASES)
def test_decimal_column_outliers_use_exact_bounds(tmp_path, precision, scale, q1, q3, eps):
    import pyarrow as pa

    values, lower, upper = _boundary_values(q1, q3, eps)
    storage = _decimal_storage(
        tmp_path, {"dec": pa.array(values, pa.decimal128(precision, scale))}
    )

    try:
        assert storage.schema_info()["dec"] == f"DECIMAL({precision},{scale})"

        result = check_quality_for_dataset(Dataset(storage=storage))

        outliers = [i for i in result["issues"] if i["type"] == "numeric_outliers"]
        assert outliers == [
            {
                "type": "numeric_outliers",
                "severity": "info",
                "column": "dec",
                "count": 2,
                "message": "Column 'dec' contains 2 potential IQR outliers.",
            }
        ]

        # Exactly the two values strictly beyond the exact bounds - the
        # values on each bound are not outliers. Checked with
        # independently written exact DECIMAL casts (not the engine's
        # own literal helper).
        table = f'"{storage.table_name}"'

        def exact(bound):
            return f"CAST('{bound:f}' AS DECIMAL({precision},{scale}))"

        beyond, on_bound = storage.execute_one(
            f"SELECT COUNT(*) FILTER (WHERE dec < {exact(lower)} OR dec > {exact(upper)}), "
            f"COUNT(*) FILTER (WHERE dec = {exact(lower)} OR dec = {exact(upper)}) "
            f"FROM {table}"
        )
        assert beyond == 2
        assert on_bound == 2
    finally:
        storage.close()


def test_decimal_bounds_are_exact_beyond_default_decimal_context():
    from data_engine.quality.duckdb_quality import _iqr_bounds, _sql_numeric_literal

    q1 = Decimal("100000000000000000001.0000000000")
    q3 = Decimal("100000000000000000003.0000000002")

    lower, upper = _iqr_bounds(q1, q3)

    # 31 significant digits each - exact, not rounded to 28 - and kept
    # at the column's scale (10), not the scale 11 `1.5 *` produces.
    assert lower == Decimal("99999999999999999997.9999999997")
    assert upper == Decimal("100000000000000000006.0000000005")
    assert _sql_numeric_literal(lower) == (
        "CAST('99999999999999999997.9999999997' AS DECIMAL(38,10))"
    )
    assert _sql_numeric_literal(upper) == (
        "CAST('100000000000000000006.0000000005' AS DECIMAL(38,10))"
    )

    # Off-grid exact bounds snap inward onto the column's grid:
    # lower 10.00 - 1.5*0.01 = 9.985 -> 9.99; upper 10.01 + 0.015 =
    # 10.025 -> 10.02. For values on the 0.01 grid, v < 9.985 iff
    # v < 9.99 and v > 10.025 iff v > 10.02.
    assert _iqr_bounds(Decimal("10.00"), Decimal("10.01")) == (
        Decimal("9.99"),
        Decimal("10.02"),
    )
    assert _iqr_bounds(Decimal("-10.01"), Decimal("-10.00")) == (
        Decimal("-10.02"),
        Decimal("-9.99"),
    )

    # In-range bounds are explicit DECIMAL(38, scale) casts, including a
    # 28-integer-digit DECIMAL(38,10) bound and 38-digit fractions
    # (positive and negative) that a bare literal would make DOUBLE.
    big_q1 = Decimal("1000000000000000000000000000.0000000000")
    big_q3 = Decimal("1000000000000000000000000001.0000000001")
    _, big_upper = _iqr_bounds(big_q1, big_q3)
    # Built from strings: unary minus on a Decimal would round to the
    # default 28-digit context.
    fraction = Decimal("0.5" + "0" * 36 + "1")
    negative_fraction = Decimal("-0.5" + "0" * 36 + "1")
    in_range = {
        _sql_numeric_literal(big_upper): "DECIMAL(38,10)",
        _sql_numeric_literal(fraction): "DECIMAL(38,38)",
        _sql_numeric_literal(negative_fraction): "DECIMAL(38,38)",
        _sql_numeric_literal(Decimal("-5.15")): "DECIMAL(38,2)",
        _sql_numeric_literal(Decimal("1E+3")): "DECIMAL(38,0)",
    }
    assert _sql_numeric_literal(negative_fraction) == (
        "CAST('-0.50000000000000000000000000000000000001' AS DECIMAL(38,38))"
    )
    # Never exponent notation inside the cast text, even for values
    # Decimal itself prints that way.
    assert _sql_numeric_literal(Decimal("1E+3")) == "CAST('1000' AS DECIMAL(38,0))"
    assert _sql_numeric_literal(Decimal("-1.5E-8")) == (
        "CAST('-0.000000015' AS DECIMAL(38,9))"
    )

    # Out-of-range bounds (|value| >= 10**(38 - scale)) keep the plain
    # fixed-point literal - a DECIMAL(38, scale) cast would raise.
    out_of_range = {
        "1." + "0" * 38: Decimal("1." + "0" * 38),  # scale 38, |v| >= 1
        "-1.85" + "0" * 36: Decimal("-1.85" + "0" * 36),
        "1" + "0" * 38: Decimal("1" + "0" * 38),  # scale 0, 39 digits
    }
    for expected, value in out_of_range.items():
        assert _sql_numeric_literal(value) == expected

    probe = DuckDBStorage(pd.DataFrame({"x": [1]}))
    try:
        for expression, expected_type in in_range.items():
            assert probe.execute_one(f"SELECT typeof({expression})")[0] == expected_type
        # The R3c defect itself: bare literal is DOUBLE and loses the
        # 1e-38 step; the cast literal compares exactly.
        bare_value = format(fraction, "f")
        stored = f"CAST('{bare_value}' AS DECIMAL(38,38))"
        bound = Decimal("0.5" + "0" * 37)
        assert probe.execute_one(
            f"SELECT {stored} > {_sql_numeric_literal(bound)}"
        )[0] is True
    finally:
        probe.close()

    # Float/integer quartiles keep the original float arithmetic and
    # repr() literals.
    assert _iqr_bounds(10.0, 20.0) == (-5.0, 35.0)
    assert _iqr_bounds(5.0, 5.0) is None
    assert _sql_numeric_literal(35.25) == repr(35.25)
    assert _sql_numeric_literal(-1e300) == repr(-1e300)


@pytest.mark.parametrize(
    "values, expected_outliers",
    [
        # q1 = 10.00, q3 = 10.01: exact bounds 9.985 / 10.025 fall
        # between 0.01 grid points and snap inward to 9.99 / 10.02.
        pytest.param(
            ["9.98"] + ["9.99"] * 9 + ["10.00"] * 20 + ["10.01"] + ["10.02"] * 9 + ["10.03"],
            {"9.98", "10.03"},
            id="positive",
        ),
        # q1 = -10.01, q3 = -10.00: exact bounds -10.025 / -9.985 snap
        # inward to -10.02 / -9.99 - a negative upper bound.
        pytest.param(
            ["-10.03"] + ["-10.02"] * 9 + ["-10.01"] * 20 + ["-10.00"] + ["-9.99"] * 9 + ["-9.98"],
            {"-10.03", "-9.98"},
            id="negative",
        ),
    ],
)
def test_decimal_off_grid_bounds_round_inward_end_to_end(tmp_path, values, expected_outliers):
    import pyarrow as pa

    assert len(values) == 41  # quartiles at sorted indexes 10 and 30 exactly
    storage = _decimal_storage(
        tmp_path, {"dec": pa.array([Decimal(v) for v in values], pa.decimal128(9, 2))}
    )

    try:
        result = check_quality_for_dataset(Dataset(storage=storage))
        table = f'"{storage.table_name}"'
        q1, q3 = storage.execute_one(f"SELECT quantile_cont(dec, [0.25, 0.75]) FROM {table}")[0]
    finally:
        storage.close()

    # The exact bounds are off-grid (third decimal digit 5).
    exact_lower, exact_upper = q1 - Decimal("1.5") * (q3 - q1), q3 + Decimal("1.5") * (q3 - q1)
    assert exact_lower.as_tuple().exponent == -3 and exact_upper.as_tuple().exponent == -3
    expected = {
        v for v in values if Decimal(v) < exact_lower or Decimal(v) > exact_upper
    }
    assert expected == expected_outliers  # values one grid step inside stay non-outliers

    outliers = [i for i in result["issues"] if i["type"] == "numeric_outliers"]
    assert [(i["column"], i["count"]) for i in outliers] == [("dec", len(expected_outliers))]


def test_decimal_38_38_out_of_range_bounds_flag_nothing(tmp_path):
    # q1 = -0.4, q3 = 0.5 -> exact bounds -1.75 / 1.85, outside
    # DECIMAL(38,38)'s (-1, 1) range: emitted as plain literals, and
    # even the most extreme storable values must not be outliers.
    import pyarrow as pa

    extreme = Decimal("0." + "9" * 38)
    negative_extreme = Decimal("-0." + "9" * 38)  # not -extreme: 28-digit context
    values = (
        [negative_extreme] * 10
        + [Decimal("-0.4")]
        + [Decimal(0)] * 19
        + [Decimal("0.5")]
        + [extreme] * 10
    )
    storage = _decimal_storage(
        tmp_path, {"dec": pa.array(values, pa.decimal128(38, _SCALE_38))}
    )

    try:
        assert storage.schema_info()["dec"] == "DECIMAL(38,38)"
        result = check_quality_for_dataset(Dataset(storage=storage))
    finally:
        storage.close()

    assert [i for i in result["issues"] if i["type"] == "numeric_outliers"] == []


def test_decimal_iqr_zero_and_all_null_columns_skip_outliers(tmp_path):
    import pyarrow as pa

    storage = _decimal_storage(
        tmp_path,
        {
            "const_dec": pa.array([Decimal("7.25")] * 10, pa.decimal128(9, 2)),
            "null_dec": pa.array([None] * 10, pa.decimal128(18, 4)),
        },
    )

    try:
        result = check_quality_for_dataset(Dataset(storage=storage))
    finally:
        storage.close()

    assert [(i["type"], i.get("column")) for i in result["issues"]] == [
        ("duplicate_rows", None),
        ("constant_column", "const_dec"),
        ("missing_values", "null_dec"),
        ("constant_column", "null_dec"),
    ]


def test_decimal_from_dataframe_no_longer_raises():
    # The DataFrame path infers a narrow DECIMAL (e.g. DECIMAL(5,1));
    # this previously raised TypeError (float * Decimal).
    values = [Decimal(f"{i}.5") for i in range(1, 20)] + [Decimal("9999.5")]
    storage = DuckDBStorage(pd.DataFrame({"dec": values}))
    assert storage.schema_info()["dec"].startswith("DECIMAL")

    result = check_quality_for_dataset(Dataset(storage=storage))

    outliers = [i for i in result["issues"] if i["type"] == "numeric_outliers"]
    assert [(i["column"], i["count"]) for i in outliers] == [("dec", 1)]


def test_decimal_outliers_match_pandas_on_binary_exact_values(tmp_path):
    # pandas treats Decimal *objects* as non-numeric, so parity is
    # checked against the same values as float64/int columns - chosen
    # as multiples of 0.25, exactly representable in binary, so the
    # pandas float result is itself exact. INTEGER/BIGINT/FLOAT/DOUBLE
    # columns ride along to confirm their behaviour is unchanged.
    import pyarrow as pa

    n = 41
    base = [Decimal(i % 9) * Decimal("0.25") for i in range(n)]
    dec_9_2 = list(base)
    dec_9_2[0] = Decimal("500.25")
    dec_18_4 = [v + Decimal("1000") for v in base]
    dec_18_4[1] = Decimal("-750.5")
    dec_38_10 = [v * 4 for v in base]
    dec_38_10[2] = Decimal("12345.75")
    ints = [i % 11 for i in range(n)]
    ints[3] = 900

    columns = {
        "d9_2": pa.array(dec_9_2, pa.decimal128(9, 2)),
        "i32": pa.array(ints, pa.int32()),
        "d18_4": pa.array(dec_18_4, pa.decimal128(18, 4)),
        "i64": pa.array([v * 1_000_000_007 for v in ints], pa.int64()),
        "d38_10": pa.array(dec_38_10, pa.decimal128(38, 10)),
        "f32": pa.array([float(v) for v in dec_9_2], pa.float32()),
        "f64": pa.array([float(v) for v in dec_18_4], pa.float64()),
        "label": pa.array([f"r{i % 3}" for i in range(n)], pa.string()),
    }
    storage = _decimal_storage(tmp_path, columns)

    float_frame = pd.DataFrame(
        {
            name: (
                [float(v) for v in array.to_pylist()]
                if pa.types.is_decimal(array.type)
                else array.to_pandas()
            )
            for name, array in columns.items()
        }
    )

    try:
        duckdb_quality = check_quality_for_dataset(Dataset(storage=storage))
    finally:
        storage.close()
    pandas_quality = check_quality_for_dataset(Dataset(storage=PandasStorage(float_frame)))

    def ordered(issues):
        return [(i["type"], i.get("column"), i.get("count")) for i in issues]

    assert ordered(duckdb_quality["issues"]) == ordered(pandas_quality["issues"])
    assert duckdb_quality["status"] == pandas_quality["status"]

    outlier_columns = [
        i["column"] for i in duckdb_quality["issues"] if i["type"] == "numeric_outliers"
    ]
    assert outlier_columns == ["d9_2", "i32", "d18_4", "i64", "d38_10", "f32", "f64"]
