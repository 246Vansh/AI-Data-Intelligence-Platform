from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.json_safety import make_json_safe
from data_engine.metadata import detect_column_role, get_allowed_operations
from data_engine.metadata_engine.base import MetadataEngine
from data_engine.storage.duckdb_storage import DuckDBStorage

# Bounded sample used only for role detection (time/metric/dimension)
# and sample_values - never the full dataset.
METADATA_SAMPLE_LIMIT = 100
SAMPLE_VALUES_LIMIT = 5

# DuckDB type-name substrings, checked in order, mapped onto the same
# basic-data-type categories data_engine.metadata.detect_data_type()
# assigns from a pandas dtype - kept as its own local copy (mirroring
# data_engine.profiling.duckdb_profiling's equivalent table) so this
# engine stays self-contained and independent of the profiling tier.
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


def _select_time_column(
    columns: dict[str, Any],
    time_columns: list[str],
) -> str | None:
    """
    Reproduces data_engine.metadata.get_metadata()'s primary
    time-column tie-break exactly: a single time column wins outright;
    among several, an actual "datetime"-typed one is preferred, else
    the first detected.
    """

    if len(time_columns) == 1:
        return time_columns[0]

    if len(time_columns) > 1:
        datetime_columns = [
            column for column in time_columns if columns[column]["data_type"] == "datetime"
        ]

        if datetime_columns:
            return datetime_columns[0]

        return time_columns[0]

    return None


class DuckDBMetadataEngine(MetadataEngine):
    """
    DuckDB-native adapter satisfying the MetadataEngine contract.

    Row/column counts and per-column non-null/distinct counts are
    computed as a single consolidated aggregate SQL query executed
    directly against the dataset's own DuckDB table - no DataFrame is
    produced to get them. Semantic role detection (time/metric/
    dimension) and sample_values instead need actual values to inspect
    - both are derived from a single bounded ``LIMIT 100`` sample
    query, never the full dataset.
    """

    def get_metadata(self, dataset: Dataset) -> dict[str, Any]:
        storage = dataset.storage

        if not isinstance(storage, DuckDBStorage):
            raise TypeError(
                "DuckDBMetadataEngine requires a DuckDBStorage-backed dataset."
            )

        table = _quote_identifier(storage.table_name)
        schema = storage.schema_info()
        column_names = storage.column_names()

        if not column_names:
            row_count = storage.execute_one(
                f"SELECT COUNT(*) FROM {table}"
            )[0]

            return {
                "row_count": int(row_count),
                "column_count": 0,
                "columns": {},
                "time_column": None,
                "time_columns": [],
            }

        # Single consolidated aggregate query for counts: row_count
        # plus, per column, a non-null count (-> missing_count) and a
        # distinct count (-> unique_values).
        select_parts = ["COUNT(*) AS row_count"]

        for index, column in enumerate(column_names):
            quoted = _quote_identifier(column)
            select_parts.append(f"COUNT({quoted}) AS non_null_{index}")
            select_parts.append(f"COUNT(DISTINCT {quoted}) AS distinct_{index}")

        counts_query = f"SELECT {', '.join(select_parts)} FROM {table}"
        counts_row = storage.execute_one(counts_query)

        row_count = int(counts_row[0])
        per_column_counts = counts_row[1:]

        # Bounded LIMIT 100 sample - the only rows ever pulled into
        # pandas, used purely for role detection and sample_values.
        sample_df = storage.execute_df(
            f"SELECT * FROM {table} LIMIT {METADATA_SAMPLE_LIMIT}"
        )

        columns: dict[str, Any] = {}
        time_columns: list[str] = []

        for index, column in enumerate(column_names):
            non_null, distinct = per_column_counts[index * 2 : index * 2 + 2]
            missing_count = row_count - int(non_null or 0)
            unique_values = int(distinct or 0)

            sample_series = sample_df[column]

            role = detect_column_role(sample_series, column)
            data_type = _categorize_duckdb_type(schema[column])

            sample_values = [
                make_json_safe(value)
                for value in sample_series.dropna().head(SAMPLE_VALUES_LIMIT).tolist()
            ]

            columns[column] = {
                "data_type": data_type,
                "role": role,
                "allowed_operations": get_allowed_operations(role),
                "nullable": missing_count > 0,
                "missing_count": missing_count,
                "unique_values": unique_values,
                "sample_values": sample_values,
            }

            if role == "time":
                time_columns.append(column)

        return {
            "row_count": row_count,
            "column_count": len(column_names),
            "columns": columns,
            "time_column": _select_time_column(columns, time_columns),
            "time_columns": time_columns,
        }
