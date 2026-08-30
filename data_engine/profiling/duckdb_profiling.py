from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.profiling._shared import safe_scalar
from data_engine.profiling.base import ProfilingEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

# DuckDB type-name substrings, checked in order, mapped onto the same
# basic-data-type categories data_engine.metadata.detect_data_type()
# assigns from a pandas dtype - so "basic datatypes" read identically
# regardless of which engine computed them.
_DUCKDB_TYPE_CATEGORIES = (
    (("TIMESTAMP", "DATE", "TIME", "INTERVAL"), "datetime"),
    (("BOOL",), "boolean"),
    (("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UINT"), "integer"),
    (("DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC"), "float"),
)


def _categorize_duckdb_type(duckdb_type: str) -> str:
    upper = str(duckdb_type).upper()

    for tokens, category in _DUCKDB_TYPE_CATEGORIES:
        if any(token in upper for token in tokens):
            return category

    return "string"


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


class DuckDBProfilingEngine(ProfilingEngine):
    """
    DuckDB-native adapter satisfying the ProfilingEngine contract.

    Row/column counts, per-column missing-value tallies, distinct
    counts, min/max bounds, and basic data types are all computed as a
    single bounded aggregate SQL query executed directly against the
    dataset's own DuckDB table - raw rows are never pulled out of
    DuckDB. No DataFrame is produced at all: the result is built
    straight from the scalar aggregate values DuckDB returns.
    """

    def basic_statistics(self, dataset: Dataset) -> dict[str, Any]:
        storage = dataset.storage

        if not isinstance(storage, DuckDBStorage):
            raise TypeError(
                "DuckDBProfilingEngine requires a DuckDBStorage-backed dataset."
            )

        table = _quote_identifier(storage.table_name)
        schema = storage.schema_info()
        column_names = storage.column_names()

        row_count = storage.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

        # Legacy-only stat (data_engine.profiler.profile_dataset's
        # "duplicate_rows") - computed as a single native aggregate
        # (row_count minus the count of distinct full rows), never by
        # pulling raw rows out of DuckDB for a Python-side comparison.
        distinct_row_count = storage.connection.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table}) AS distinct_rows"
        ).fetchone()[0]

        duplicate_rows = int(row_count) - int(distinct_row_count)

        if not column_names:
            return {
                "row_count": int(row_count),
                "column_count": 0,
                "columns": {},
                "duplicate_rows": duplicate_rows,
                # No native DuckDB equivalent to pandas'
                # memory_usage(deep=True) - see the note below.
                "memory_usage_bytes": None,
            }

        select_parts = []

        for index, column in enumerate(column_names):
            quoted = _quote_identifier(column)
            select_parts.append(f"COUNT({quoted}) AS non_null_{index}")
            select_parts.append(f"COUNT(DISTINCT {quoted}) AS distinct_{index}")
            select_parts.append(f"MIN({quoted}) AS min_{index}")
            select_parts.append(f"MAX({quoted}) AS max_{index}")

        query = f"SELECT {', '.join(select_parts)} FROM {table}"
        row = storage.connection.execute(query).fetchone()

        columns: dict[str, Any] = {}

        for index, column in enumerate(column_names):
            non_null, distinct, min_value, max_value = row[index * 4 : index * 4 + 4]

            missing_count = int(row_count) - int(non_null or 0)

            columns[column] = {
                "data_type": _categorize_duckdb_type(schema[column]),
                "missing_count": missing_count,
                "missing_percentage": round(
                    (missing_count / row_count) * 100 if row_count else 0.0,
                    2,
                ),
                "distinct_count": int(distinct or 0),
                "min": safe_scalar(min_value),
                "max": safe_scalar(max_value),
            }

        return {
            "row_count": int(row_count),
            "column_count": len(column_names),
            "columns": columns,
            "duplicate_rows": duplicate_rows,
            # pandas' memory_usage(deep=True) has no faithful DuckDB
            # equivalent (it accounts for Python/pandas object
            # overhead specifically) - reporting a fabricated number
            # here would be more misleading than reporting none.
            "memory_usage_bytes": None,
        }
