from __future__ import annotations

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


def _is_numeric_duckdb_type(duckdb_type: str) -> bool:
    upper = str(duckdb_type).upper()

    if "BOOL" in upper:
        return False

    return any(token in upper for token in _NUMERIC_TYPE_TOKENS)


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


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
        # -----------------------------------------------------

        distinct_row_count = int(
            storage.execute_one(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table}) AS distinct_rows"
            )[0]
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
        # Single consolidated aggregate query: per-column non-null
        # and distinct counts, for missing-value / constant-column /
        # high-cardinality checks.
        # -----------------------------------------------------

        select_parts = []

        for index, column in enumerate(column_names):
            quoted = _quote_identifier(column)
            select_parts.append(f"COUNT({quoted}) AS non_null_{index}")
            select_parts.append(f"COUNT(DISTINCT {quoted}) AS distinct_{index}")

        counts_row = storage.execute_one(
            f"SELECT {', '.join(select_parts)} FROM {table}"
        )

        # -----------------------------------------------------
        # IQR outlier bounds - one aggregate query computing Q1/Q3
        # for every numeric column at once, then a second aggregate
        # counting values outside the derived bounds.
        # -----------------------------------------------------

        numeric_columns = [
            column for column in column_names if _is_numeric_duckdb_type(schema[column])
        ]

        outlier_counts: dict[str, int] = {}

        if numeric_columns:
            quantile_parts = []

            for index, column in enumerate(numeric_columns):
                quoted = _quote_identifier(column)
                quantile_parts.append(f"quantile_cont({quoted}, 0.25) AS q1_{index}")
                quantile_parts.append(f"quantile_cont({quoted}, 0.75) AS q3_{index}")

            quantile_row = storage.execute_one(
                f"SELECT {', '.join(quantile_parts)} FROM {table}"
            )

            bounds: dict[str, tuple[float, float]] = {}

            for index, column in enumerate(numeric_columns):
                q1, q3 = quantile_row[index * 2], quantile_row[index * 2 + 1]

                if q1 is None or q3 is None:
                    continue

                iqr = q3 - q1

                if iqr == 0:
                    continue

                bounds[column] = (q1 - 1.5 * iqr, q3 + 1.5 * iqr)

            if bounds:
                outlier_parts = []

                for column, (lower, upper) in bounds.items():
                    quoted = _quote_identifier(column)
                    outlier_parts.append(
                        f"COUNT(*) FILTER (WHERE {quoted} < {lower!r} OR {quoted} > {upper!r}) "
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

        for index, column in enumerate(column_names):
            non_null, distinct = counts_row[index * 2], counts_row[index * 2 + 1]
            missing_count = row_count - int(non_null or 0)
            unique_count = int(distinct or 0)

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
