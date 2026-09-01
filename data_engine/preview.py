from __future__ import annotations

from typing import Any

from data_engine.dataset import Dataset
from data_engine.json_safety import sanitize_records
from data_engine.storage.duckdb_storage import DuckDBStorage

# Historical /preview row cap (backend/routes/dataset.py's previous
# `df.head(10)`), preserved exactly.
PREVIEW_ROW_LIMIT = 10


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def preview_dataset(
    dataset: Dataset,
    limit: int = PREVIEW_ROW_LIMIT,
) -> dict[str, Any]:
    """
    Build the {columns, rows} preview payload for a dataset, reading
    at most `limit` rows regardless of storage backend.

    A DuckDB-backed dataset is read through a single bounded
    ``LIMIT <limit>`` SQL query executed directly against its own
    table/view - the dataset's full contents are never pulled into a
    Pandas DataFrame to get here, only the `limit`-row slice actually
    returned. A Pandas-backed dataset goes through the existing
    DatasetStorage.to_dataframe() compatibility boundary followed by
    .head(limit), matching the historical /preview behavior exactly.

    Not cached: matches the historical route's behavior of recomputing
    the preview slice on every call rather than memoizing it on
    Dataset.cache.
    """
    storage = dataset.storage

    if isinstance(storage, DuckDBStorage):
        table = _quote_identifier(storage.table_name)
        preview_df = storage.connection.execute(
            f"SELECT * FROM {table} LIMIT {int(limit)}"
        ).df()
        columns = list(preview_df.columns)
    else:
        preview_df = storage.to_dataframe().head(limit)
        columns = preview_df.columns.tolist()

    rows = sanitize_records(preview_df.to_dict(orient="records"))

    return {
        "columns": columns,
        "rows": rows,
    }
