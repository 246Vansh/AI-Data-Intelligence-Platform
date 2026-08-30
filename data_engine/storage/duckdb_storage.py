from __future__ import annotations

import uuid

import duckdb
import pandas as pd

from data_engine.storage.base import DatasetStorage


class DuckDBStorage(DatasetStorage):
    """
    DuckDB-backed storage implementation.

    Data lives inside DuckDB (not as a Python-side DataFrame the rest
    of the storage keeps around), so analytical work can be pushed
    down to the DuckDB engine itself instead of pandas.

    Isolation: every instance opens its own private, in-memory DuckDB
    connection (":memory:"). Two DuckDBStorage instances never share a
    connection, so their tables can never collide regardless of name -
    on top of that, each instance's table is additionally namespaced
    with a fresh uuid, so even code that reused a single shared
    connection in the future would still be safe from name collisions.
    """

    def __init__(self, dataframe: pd.DataFrame):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame.")

        if dataframe.empty:
            raise ValueError("The dataset is empty.")

        # Private, in-memory connection - not shared with any other
        # DuckDBStorage instance or dataset.
        self._connection = duckdb.connect(database=":memory:")

        # Unique table name, namespaced per instance as a second,
        # independent layer of isolation.
        self._table_name = f"dataset_{uuid.uuid4().hex}"

        self._connection.register("_source_df", dataframe)
        self._connection.execute(
            f'CREATE TABLE "{self._table_name}" AS SELECT * FROM _source_df'
        )
        self._connection.unregister("_source_df")

        self._columns = list(dataframe.columns)

    @classmethod
    def from_parquet(cls, parquet_path: str) -> "DuckDBStorage":
        """
        Build a DuckDBStorage instance directly from a Parquet file on
        disk, via DuckDB's own native ``read_parquet`` - a Pandas
        DataFrame of the source is never constructed to get here.

        This is the constructor the ingestion -> registration path
        (Step 10) uses: ``ingest_to_parquet`` only ever hands back a
        path, never a DataFrame, so ``DuckDBStorage(dataframe)`` isn't
        an option for that caller.

        Bypasses ``__init__`` (which requires a DataFrame) via
        ``__new__`` and sets up the same private-connection /
        namespaced-table invariants inline.
        """
        instance = cls.__new__(cls)

        instance._connection = duckdb.connect(database=":memory:")
        instance._table_name = f"dataset_{uuid.uuid4().hex}"

        instance._connection.execute(
            f'CREATE TABLE "{instance._table_name}" AS SELECT * FROM read_parquet(?)',
            [parquet_path],
        )

        instance._columns = list(instance._connection.table(instance._table_name).columns)

        return instance

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """
        The private DuckDB connection backing this dataset.

        Exposed so an execution layer (e.g. a DuckDB-native query
        engine) can run SQL directly against the engine instead of
        materializing the dataset into pandas first.
        """
        return self._connection

    @property
    def table_name(self) -> str:
        """The uniquely namespaced table name holding this dataset."""
        return self._table_name

    def relation(self) -> duckdb.DuckDBPyRelation:
        """Return a fresh DuckDB relation over this dataset's table."""
        return self._connection.table(self._table_name)

    def schema_info(self) -> dict[str, str]:
        """Return a mapping of column name -> DuckDB type name."""
        rel = self.relation()
        return dict(zip(rel.columns, (str(t) for t in rel.types)))

    def to_dataframe(self) -> pd.DataFrame:
        """
        Materialize the dataset as a Pandas DataFrame.

        This is the compatibility boundary for existing DataFrame-based
        application components - the DuckDB engine itself is used for
        any actual analytical computation.
        """
        return self.relation().to_df()

    def row_count(self) -> int:
        return self.relation().shape[0]

    def column_count(self) -> int:
        return len(self._columns)

    def column_names(self) -> list[str]:
        return list(self._columns)

    def close(self) -> None:
        """Release the underlying DuckDB connection."""
        self._connection.close()
