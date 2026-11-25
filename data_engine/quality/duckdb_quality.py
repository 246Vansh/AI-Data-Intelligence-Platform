from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Any

from data_engine.dataset import Dataset
from data_engine.quality.base import QualityEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

HIGH_CARDINALITY_MIN_UNIQUE = 20
HIGH_CARDINALITY_PERCENTAGE = 95.0

# DuckDB type-name substrings identifying a numeric column eligible
# for IQR outlier detection - booleans are excluded even though
# DuckDB's BOOLEAN participates in some numeric contexts, matching
# data_engine.data_quality._count_iqr_outliers's own
# is_bool_dtype exclusion.
_NUMERIC_TYPE_TOKENS = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UINT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "NUMERIC",
)


# R3: number of numeric columns whose exact Q1/Q3 are computed per
# quartile query. Exact quantile_cont buffers every non-null value of
# its column for the whole scan, so one query spanning every numeric
# column holds all of those buffers at once; batching caps how many are
# live together, mirroring DuckDBStorage._COLUMN_STATISTICS_BATCH_SIZE
# (data_engine/storage/duckdb_storage.py). Results are unchanged - each
# column's quantile state depends only on that column's own values.
_QUANTILE_BATCH_SIZE = 4


def _is_numeric_duckdb_type(duckdb_type: str) -> bool:
    upper = str(duckdb_type).upper()

    if "BOOL" in upper:
        return False

    return any(token in upper for token in _NUMERIC_TYPE_TOKENS)


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


# DECIMAL quartiles come back from DuckDB as decimal.Decimal (same
# scale as the column), so their IQR bounds are computed in exact
# Decimal arithmetic rather than via float. Python's default Decimal
# context rounds to 28 significant digits, fewer than DECIMAL(38, s)
# can hold, hence a local context with ample precision: q - 1.5 * iqr
# needs at most ~40 significant digits for any DECIMAL(38, s) input.
_DECIMAL_BOUND_PRECISION = 80
_DECIMAL_IQR_MULTIPLIER = Decimal("1.5")


def _iqr_bounds(q1: Any, q3: Any) -> tuple[Any, Any] | None:
    """
    Return (q1 - 1.5 * iqr, q3 + 1.5 * iqr), or None when the IQR is 0.

    Float quartiles (every non-DECIMAL numeric type) use exactly the
    original float arithmetic; Decimal quartiles (DECIMAL columns) use
    exact Decimal arithmetic.

    Decimal bounds are then snapped onto the column's own scale -
    lower rounded up, upper rounded down. Every stored value v is a
    multiple of 10**-scale, so ``v < L`` iff ``v < ceil(L)`` and
    ``v > U`` iff ``v > floor(U)``: the outlier count is identical,
    while the bound keeps the column's scale instead of the extra
    digit `1.5 *` adds, so it fits DECIMAL(38, scale) whenever it is
    within that type's range (see _sql_numeric_literal()).
    DuckDB returns DECIMAL quartiles at the column's scale, so the
    quartiles' own exponent is that scale.
    """
    if isinstance(q1, Decimal) or isinstance(q3, Decimal):
        with localcontext() as context:
            context.prec = _DECIMAL_BOUND_PRECISION
            q1, q3 = Decimal(q1), Decimal(q3)
            iqr = q3 - q1

            if iqr == 0:
                return None

            spread = _DECIMAL_IQR_MULTIPLIER * iqr
            quantum = Decimal(1).scaleb(
                min(q1.as_tuple().exponent, q3.as_tuple().exponent)
            )
            return (
                (q1 - spread).quantize(quantum, rounding=ROUND_CEILING),
                (q3 + spread).quantize(quantum, rounding=ROUND_FLOOR),
            )

    iqr = q3 - q1

    if iqr == 0:
        return None

    return (q1 - 1.5 * iqr, q3 + 1.5 * iqr)


_DUCKDB_MAX_DECIMAL_WIDTH = 38


def _sql_numeric_literal(value: Any) -> str:
    """
    Render a bound as a SQL numeric expression; non-Decimal values via
    repr() exactly as before.

    A Decimal bound that fits DECIMAL(38, scale) - |value| <
    10**(38 - scale) - is emitted as an explicit
    ``CAST('<fixed-point text>' AS DECIMAL(38, scale))``. A bare
    literal isn't enough: DuckDB 1.5.5 types an unadorned decimal
    literal by its digit count *including a leading zero*, so a
    38-digit fraction such as 0.50000000000000000000000000000000000001
    (39 digits counting the "0") parses as DOUBLE, and comparing a
    DECIMAL(38,38) column against it can misclassify values (an actual
    outlier was missed). Comparing DECIMAL(p, scale) against
    DECIMAL(38, scale) stays exact.

    A bound outside DECIMAL(38, scale)'s range can't be cast (DuckDB
    raises ConversionException), so it keeps the plain fixed-point
    literal (never exponent form), which DuckDB may type as HUGEINT or
    DOUBLE. That comparison still classifies every stored value
    correctly: such a bound lies strictly beyond every storable value,
    and rounding to DOUBLE is monotonic, so no stored value can compare
    past it.
    """
    if isinstance(value, Decimal):
        text = format(value, "f")
        scale = max(0, -value.as_tuple().exponent)

        if scale <= _DUCKDB_MAX_DECIMAL_WIDTH and value.copy_abs() < Decimal(1).scaleb(
            _DUCKDB_MAX_DECIMAL_WIDTH - scale
        ):
            return f"CAST('{text}' AS DECIMAL({_DUCKDB_MAX_DECIMAL_WIDTH},{scale}))"

        return text

    return repr(value)


# =========================================================
# Severity / status - local copies of
# data_engine.data_quality's private helpers, kept as its own
# self-contained implementation (mirroring how
# data_engine.profiling.duckdb_profiling never reaches into
# data_engine.profiling.pandas_profiling's internals either).
# =========================================================


def _missing_severity(percentage: float) -> str:
    if percentage >= 50:
        return "error"

    if percentage >= 20:
        return "warning"

    return "info"


def _determine_status(issues: list[dict[str, Any]]) -> str:
    severities = {issue["severity"] for issue in issues}

    if "error" in severities:
        return "error"

    if "warning" in severities:
        return "warning"

    if issues:
        return "info"

    return "healthy"


class DuckDBQualityEngine(QualityEngine):
    """
    DuckDB-native adapter satisfying the QualityEngine contract.

    Duplicate-row detection, per-column missing-value/constant-column/
    high-cardinality checks, and IQR-based numeric outlier counts are
    all computed via bounded aggregate SQL executed directly against
    the dataset's own DuckDB table - raw rows are never pulled out of
    DuckDB and no DataFrame is ever produced.
    """

    def check_quality(self, dataset: Dataset) -> dict[str, Any]:
        storage = dataset.storage

        if not isinstance(storage, DuckDBStorage):
            raise TypeError(
                "DuckDBQualityEngine requires a DuckDBStorage-backed dataset."
            )

        table = _quote_identifier(storage.table_name)
        schema = storage.schema_info()
        column_names = storage.column_names()

        row_count = int(
            storage.execute_one(f"SELECT COUNT(*) FROM {table}")[0]
        )

        if row_count == 0:
            return {
                "status": "invalid",
                "issue_count": 1,
                "issues": [
                    {
                        "type": "empty_dataset",
                        "severity": "error",
                        "message": "Dataset contains no rows.",
                    }
                ],
            }

        issues: list[dict[str, Any]] = []

        # -----------------------------------------------------
        # Duplicate rows - single aggregate: row_count minus the
        # count of distinct full rows.
        #
        # Step 33: this exact scan is also needed by
        # DuckDBProfilingEngine.basic_statistics() for the same
        # dataset, so it's routed through storage.distinct_row_count(),
        # which caches the scalar on the dataset's own DuckDBStorage
        # instance - whichever of profiling/quality runs first for
        # this dataset pays for the scan, the other reuses the cached
        # value.
        # -----------------------------------------------------

        distinct_row_count = int(
            storage.distinct_row_count(
                lambda: storage.execute_one(
                    f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table}) AS distinct_rows"
                )[0]
            )
        )
        duplicate_count = row_count - distinct_row_count

        if duplicate_count > 0:
            issues.append(
                {
                    "type": "duplicate_rows",
                    "severity": "warning",
                    "count": duplicate_count,
                    "message": f"Dataset contains {duplicate_count} duplicate rows.",
                }
            )

        if not column_names:
            status = _determine_status(issues)
            return {"status": status, "issue_count": len(issues), "issues": issues}

        # -----------------------------------------------------
        # Per-column non-null and distinct counts, for missing-value /
        # constant-column / high-cardinality checks.
        #
        # Step 35: sourced from DuckDBStorage's single shared aggregate
        # scan - memoized on the dataset's own storage instance and
        # reused as-is by DuckDBMetadataEngine and
        # DuckDBProfilingEngine too, instead of each engine running its
        # own separate copy of this query (see
        # step34_post_step33_scalability_audit.txt /
        # step35_shared_column_stats_audit.txt).
        # -----------------------------------------------------

        column_statistics = storage.column_statistics()

        # -----------------------------------------------------
        # IQR outlier bounds - exact Q1/Q3 computed in batches of
        # _QUANTILE_BATCH_SIZE numeric columns (one aggregate query per
        # batch), then one aggregate counting values outside the
        # derived bounds for every bounded column at once.
        #
        # R3: each column uses the list form
        # quantile_cont(col, [0.25, 0.75]) - one exact aggregate state
        # per column instead of two - verified on DuckDB 1.5.5 to
        # return values (and types) identical to the two scalar
        # quantile_cont(col, 0.25)/quantile_cont(col, 0.75) calls,
        # including NULL for an all-null column.
        # -----------------------------------------------------

        numeric_columns = [
            column for column in column_names if _is_numeric_duckdb_type(schema[column])
        ]

        outlier_counts: dict[str, int] = {}

        if numeric_columns:
            bounds: dict[str, tuple[Any, Any]] = {}
            quartiles: list[tuple[str, Any, Any]] = []

            for batch_start in range(0, len(numeric_columns), _QUANTILE_BATCH_SIZE):
                batch = numeric_columns[batch_start : batch_start + _QUANTILE_BATCH_SIZE]
                quantile_parts = [
                    f"quantile_cont({_quote_identifier(column)}, [0.25, 0.75]) AS q_{offset}"
                    for offset, column in enumerate(batch)
                ]

                quantile_row = storage.execute_one(
                    f"SELECT {', '.join(quantile_parts)} FROM {table}"
                )

                for column, pair in zip(batch, quantile_row):
                    q1, q3 = (None, None) if pair is None else pair
                    quartiles.append((column, q1, q3))

            for column, q1, q3 in quartiles:
                if q1 is None or q3 is None:
                    continue

                column_bounds = _iqr_bounds(q1, q3)

                if column_bounds is None:
                    continue

                bounds[column] = column_bounds

            if bounds:
                outlier_parts = []

                for column, (lower, upper) in bounds.items():
                    quoted = _quote_identifier(column)
                    lower_sql = _sql_numeric_literal(lower)
                    upper_sql = _sql_numeric_literal(upper)
                    outlier_parts.append(
                        f"COUNT(*) FILTER (WHERE {quoted} < {lower_sql} OR {quoted} > {upper_sql}) "
                        f"AS {_quote_identifier('outliers_' + column)}"
                    )

                outlier_row = storage.execute_one(
                    f"SELECT {', '.join(outlier_parts)} FROM {table}"
                )

                outlier_counts = {
                    column: int(count)
                    for column, count in zip(bounds.keys(), outlier_row)
                }

        # -----------------------------------------------------
        # Per-column issues, in the same order as
        # data_engine.data_quality.check_data_quality(): missing ->
        # constant -> high cardinality -> outliers, column by column.
        # -----------------------------------------------------

        for column in column_names:
            stats = column_statistics[column]
            missing_count = row_count - stats.non_null_count
            unique_count = stats.distinct_count

            if missing_count > 0:
                missing_percentage = (missing_count / row_count) * 100

                issues.append(
                    {
                        "type": "missing_values",
                        "severity": _missing_severity(missing_percentage),
                        "column": column,
                        "count": missing_count,
                        "percentage": round(missing_percentage, 2),
                        "message": (
                            f"Column '{column}' contains "
                            f"{missing_count} missing values "
                            f"({missing_percentage:.2f}%)."
                        ),
                    }
                )

            if unique_count <= 1:
                issues.append(
                    {
                        "type": "constant_column",
                        "severity": "warning",
                        "column": column,
                        "unique_count": unique_count,
                        "message": (
                            f"Column '{column}' contains {unique_count} unique value."
                        ),
                    }
                )

            cardinality_percentage = (unique_count / row_count) * 100

            if (
                cardinality_percentage >= HIGH_CARDINALITY_PERCENTAGE
                and unique_count > HIGH_CARDINALITY_MIN_UNIQUE
            ):
                issues.append(
                    {
                        "type": "high_cardinality",
                        "severity": "info",
                        "column": column,
                        "unique_count": unique_count,
                        "percentage": round(cardinality_percentage, 2),
                        "message": f"Column '{column}' has very high cardinality.",
                    }
                )

            outlier_count = outlier_counts.get(column, 0)

            if outlier_count > 0:
                issues.append(
                    {
                        "type": "numeric_outliers",
                        "severity": "info",
                        "column": column,
                        "count": outlier_count,
                        "message": (
                            f"Column '{column}' contains "
                            f"{outlier_count} potential "
                            f"IQR outliers."
                        ),
                    }
                )

        status = _determine_status(issues)

        return {
            "status": status,
            "issue_count": len(issues),
            "issues": issues,
        }
