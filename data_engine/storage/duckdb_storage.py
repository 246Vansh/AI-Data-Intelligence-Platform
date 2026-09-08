from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid

import duckdb
import pandas as pd

from data_engine.storage.base import DatasetStorage

# Step 30: every DuckDBStorage connection gets an explicit memory_limit
# and a private, per-instance temp_directory, so a heavy full-table
# aggregate (e.g. the duplicate-row `SELECT DISTINCT *` check in
# data_engine.profiling.duckdb_profiling /
# data_engine.quality.duckdb_quality) spills to disk under memory
# pressure instead of running against DuckDB's unconfigured default
# with no verified spill path (see
# step29a_duplicate_detection_feasibility.txt, which proved spilling
# works once these two settings are present - the duplicate-row SQL
# itself is unchanged).
#
# Overridable via the DUCKDB_MEMORY_LIMIT / DUCKDB_TEMP_ROOT
# environment variables, matching the plain-env-var pattern already
# used for MAX_UPLOAD_BYTES (backend/routes/dataset.py) - this project
# has no other configuration mechanism yet.
_DEFAULT_DUCKDB_MEMORY_LIMIT = "4GB"


def _read_duckdb_memory_limit() -> str:
    return os.environ.get("DUCKDB_MEMORY_LIMIT") or _DEFAULT_DUCKDB_MEMORY_LIMIT


def _read_duckdb_temp_root() -> str:
    return os.environ.get("DUCKDB_TEMP_ROOT") or tempfile.gettempdir()


def _configure_connection_and_temp_dir(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> str:
    """
    Apply the configured memory_limit and a private, per-instance
    temp_directory to a freshly opened connection, before any table or
    view is created on it. The directory is namespaced with the same
    unique ``table_name`` every instance already uses, so it can never
    collide with another instance's spill files. Returns the created
    directory's path so the caller can remove it again in close().
    """
    memory_limit = str(_read_duckdb_memory_limit()).replace("'", "''")
    temp_dir = os.path.join(_read_duckdb_temp_root(), f"duckdb_spill_{table_name}")
    os.makedirs(temp_dir, exist_ok=True)

    escaped_temp_dir = temp_dir.replace("'", "''")

    connection.execute(f"PRAGMA memory_limit='{memory_limit}'")
    connection.execute(f"PRAGMA temp_directory='{escaped_temp_dir}'")

    return temp_dir


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

    Thread-safety: every instance also owns a private ``RLock``
    guarding its connection. Every method that touches the connection
    (``relation``, ``to_dataframe``, ``row_count``, ``column_count``,
    ``column_names``, ``schema_info``, ``execute_df``, ``execute_one``,
    the ``connection`` property) and ``close()`` itself all acquire it
    before doing anything. That makes ``close()`` and any in-flight
    read mutually exclusive on *this* instance: a read already holding
    the lock keeps a concurrent ``close()`` waiting until it finishes,
    and once ``close()`` has run, any later read finds ``_closed`` set
    and raises before it ever touches the (by then invalid) connection,
    instead of segfaulting DuckDB or racing it. It is an ``RLock``
    (reentrant), not a plain ``Lock``, because these methods call each
    other from the same thread (e.g. ``to_dataframe()`` calls
    ``relation()``) - a plain ``Lock`` would deadlock a thread against
    itself the moment one guarded method called another. The lock is
    strictly per-instance: it never coordinates across different
    DuckDBStorage instances, and nothing here is a global/shared lock,
    a connection pool, or an async primitive.

    Step 17B: ``execute_df()``/``execute_one()`` hold the lock across
    the query's full execute-and-materialize lifetime, not just a
    connection handoff - see their docstrings and the ``connection``
    property's docstring for why that distinction matters. Every live
    production call site (analysis execution, preview, metadata,
    profiling, quality) goes through these two methods; the raw
    ``connection`` property remains only for direct/diagnostic use.

    Step 30: every connection also gets an explicit ``memory_limit``
    and its own private ``temp_directory`` (see
    ``_configure_connection_and_temp_dir`` above), applied identically
    by both constructors before any table/view is created. The temp
    directory is removed again in ``close()``.
    """

    def __init__(self, dataframe: pd.DataFrame):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame.")

        if dataframe.empty:
            raise ValueError("The dataset is empty.")

        self._lock = threading.RLock()
        self._closed = False

        # No on-disk artifact - this constructor builds a physical,
        # in-memory-only table from an already-materialized DataFrame.
        # See from_parquet() for the on-disk-backed case.
        self._parquet_path: str | None = None

        # Private, in-memory connection - not shared with any other
        # DuckDBStorage instance or dataset.
        self._connection = duckdb.connect(database=":memory:")

        # Unique table name, namespaced per instance as a second,
        # independent layer of isolation.
        self._table_name = f"dataset_{uuid.uuid4().hex}"

        # Step 30: explicit memory_limit + private spill directory,
        # applied before any table exists on this connection.
        self._temp_dir = _configure_connection_and_temp_dir(
            self._connection, self._table_name
        )

        self._connection.register("_source_df", dataframe)
        self._connection.execute(
            f'CREATE TABLE "{self._table_name}" AS SELECT * FROM _source_df'
        )
        self._connection.unregister("_source_df")

        self._columns = list(dataframe.columns)

    @classmethod
    def from_parquet(cls, parquet_path: str) -> "DuckDBStorage":
        """
        Build a DuckDBStorage instance as a zero-copy VIEW over a
        Parquet file on disk, via DuckDB's own native ``read_parquet``
        - neither a Pandas DataFrame nor a physical copy of the
        dataset's rows is ever created to get here.

        This is the constructor the ingestion -> registration path
        (Step 10) uses: ``ingest_to_parquet`` only ever hands back a
        path, never a DataFrame, so ``DuckDBStorage(dataframe)`` isn't
        an option for that caller.

        Bypasses ``__init__`` (which requires a DataFrame) via
        ``__new__`` and sets up the same private-connection /
        namespaced-table invariants inline - except the table is a
        ``CREATE VIEW ... AS SELECT * FROM read_parquet(?)``, not a
        physical ``CREATE TABLE ... AS SELECT``. DuckDB resolves the
        view against the Parquet file itself at query time, so
        registration never scans or copies the dataset's rows - the
        connection only stores the view's query plan. Every downstream
        consumer (execute_plan_duckdb, profiling, to_dataframe/
        row_count/column_count/column_names/schema_info) keeps working
        unmodified: DuckDB queries a view exactly like a table.
        """
        instance = cls.__new__(cls)

        instance._lock = threading.RLock()
        instance._closed = False

        instance._connection = duckdb.connect(database=":memory:")
        instance._table_name = f"dataset_{uuid.uuid4().hex}"
        instance._parquet_path = parquet_path

        # Step 30: explicit memory_limit + private spill directory,
        # applied before the view exists on this connection - same
        # helper, same guarantees as the DataFrame-backed constructor.
        instance._temp_dir = _configure_connection_and_temp_dir(
            instance._connection, instance._table_name
        )

        # DuckDB DDL (CREATE VIEW) cannot be a prepared statement, so
        # the path can't be passed as a bound parameter here the way
        # the old CREATE TABLE ... AS SELECT statement did - it is
        # escaped and inlined into the view definition instead.
        escaped_parquet_path = str(parquet_path).replace("'", "''")
        instance._connection.execute(
            f'CREATE VIEW "{instance._table_name}" AS '
            f"SELECT * FROM read_parquet('{escaped_parquet_path}')"
        )

        instance._columns = list(instance._connection.table(instance._table_name).columns)

        return instance

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError(
                "This DuckDBStorage instance has already been closed."
            )

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """
        The private DuckDB connection backing this dataset.

        Step 17B: this property only guards the *access* to the
        connection object - the instance lock cannot stay held across
        whatever a caller subsequently does with the returned
        reference, since that execution happens outside of this
        method's call frame. That gap made ``storage.connection
        .execute(...)`` racy against a concurrent ``close()``. Every
        live production call site has been migrated to
        ``execute_df()``/``execute_one()`` below, which hold the lock
        for the query's entire execution, not just the handoff.

        This property is kept only for direct low-level/diagnostic use
        (e.g. isolation tests that compare connection identity or run
        ad-hoc DDL). New production call sites should use
        ``execute_df()``/``execute_one()`` instead of this property.
        """
        with self._lock:
            self._raise_if_closed()
            return self._connection

    def execute_df(self, query: str, params: list | None = None) -> pd.DataFrame:
        """
        Run a read-only SQL query against this dataset's connection and
        materialize the result as a DataFrame.

        Lock-safe replacement for the ``storage.connection.execute(...)
        .fetchdf()`` pattern: the connection-closed check, the query's
        execution, and its materialization into a DataFrame all happen
        inside the same ``with self._lock:`` critical section that
        ``close()`` also acquires. A concurrent ``close()`` therefore
        either finishes first (this call then raises the same
        controlled "already closed" error every other read boundary
        raises) or waits for this call to finish (close() blocks on
        the lock until this method returns) - it can never run
        in between this method's connection access and its query
        execution the way it could through the raw ``connection``
        property.
        """
        with self._lock:
            self._raise_if_closed()
            if params is None:
                return self._connection.execute(query).fetchdf()
            return self._connection.execute(query, params).fetchdf()

    def execute_one(self, query: str, params: list | None = None):
        """
        Like ``execute_df()``, but for a single-row/scalar result
        (``COUNT(*)``, quantile aggregates, etc.) fetched via
        ``fetchone()`` instead of materializing a DataFrame. Same
        full-lock-coverage guarantee as ``execute_df()``.
        """
        with self._lock:
            self._raise_if_closed()
            if params is None:
                return self._connection.execute(query).fetchone()
            return self._connection.execute(query, params).fetchone()

    @property
    def table_name(self) -> str:
        """The uniquely namespaced table name holding this dataset."""
        return self._table_name

    @property
    def artifact_path(self) -> str | None:
        """
        Path of the Parquet file this storage is backed by, if it was
        built via from_parquet(); None for a storage built from an
        already in-memory DataFrame (__init__), which has no on-disk
        artifact of its own to clean up.
        """
        return self._parquet_path

    def relation(self) -> duckdb.DuckDBPyRelation:
        """Return a fresh DuckDB relation over this dataset's table."""
        with self._lock:
            self._raise_if_closed()
            return self._connection.table(self._table_name)

    def schema_info(self) -> dict[str, str]:
        """Return a mapping of column name -> DuckDB type name."""
        with self._lock:
            self._raise_if_closed()
            rel = self._connection.table(self._table_name)
            return dict(zip(rel.columns, (str(t) for t in rel.types)))

    def to_dataframe(self) -> pd.DataFrame:
        """
        Materialize the dataset as a Pandas DataFrame.

        This is the compatibility boundary for existing DataFrame-based
        application components - the DuckDB engine itself is used for
        any actual analytical computation.
        """
        with self._lock:
            self._raise_if_closed()
            return self._connection.table(self._table_name).to_df()

    def row_count(self) -> int:
        with self._lock:
            self._raise_if_closed()
            return self._connection.table(self._table_name).shape[0]

    def column_count(self) -> int:
        return len(self._columns)

    def column_names(self) -> list[str]:
        return list(self._columns)

    def close(self) -> None:
        """
        Release the underlying DuckDB connection.

        Idempotent - closing an already-closed instance is a no-op,
        not an error. Waits for the instance lock, so any read
        currently in flight on this instance (relation/to_dataframe/
        row_count/schema_info/connection) finishes first; once this
        returns, every subsequent read on this instance raises instead
        of touching the closed connection.

        Step 30: DuckDB itself deletes its own spill files from
        temp_directory when the connection closes, but leaves the
        directory itself behind - so this also removes the private
        per-instance temp directory created at construction.
        ``ignore_errors=True`` keeps this a safe, best-effort cleanup
        (e.g. if the directory was already removed by something else)
        rather than turning close() into a new failure point.
        """
        with self._lock:
            if self._closed:
                return

            self._connection.close()
            self._closed = True

            shutil.rmtree(self._temp_dir, ignore_errors=True)
