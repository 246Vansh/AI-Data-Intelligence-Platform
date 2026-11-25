from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass

import duckdb
import pandas as pd

from data_engine.storage.base import DatasetStorage, StorageClosedError
from data_engine.storage.deadline import QueryTimeoutError, remaining_seconds

if os.name == "nt":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)

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
#
# Step 91: lowered from 4GB. This is a per-instance limit and every
# registered dataset owns its own instance, so with ANALYSIS_JOB_WORKERS
# (default 2) bounding concurrent heavy scans, 2 x 4GB alone already
# exceeded the 7.9GB development host. 1GB keeps that pooled share at
# ~2GB nominal and relies on spill (verified for column_statistics in
# Steps 87-88) beyond it. Not a cap on total process memory.
_DEFAULT_DUCKDB_MEMORY_LIMIT = "1GB"


def _read_duckdb_memory_limit() -> str:
    return os.environ.get("DUCKDB_MEMORY_LIMIT") or _DEFAULT_DUCKDB_MEMORY_LIMIT


def _read_duckdb_temp_root() -> str:
    return os.environ.get("DUCKDB_TEMP_ROOT") or tempfile.gettempdir()


# R2 (backend performance audit): every instance is its own DuckDB
# database, so DuckDB's defaults apply per dataset - 4 threads each
# (2 concurrent heavy scans = 8 threads on a 4-core host, plus 3 idle
# worker threads held by every registered dataset), and a spill cap of
# 90% of free disk each (two scans could together claim far more disk
# than exists). With ANALYSIS_JOB_WORKERS=2, 2 threads per instance
# matches 4 cores and gives each thread 512MB of the 1GB memory_limit;
# a 10GiB cap per instance bounds worst-case concurrent spill to
# ~20GiB and turns a runaway spill into a failed query instead of a
# full disk. Overridable via DUCKDB_THREADS /
# DUCKDB_MAX_TEMP_DIRECTORY_SIZE. An invalid override logs a warning
# and falls back to the default - it never stops a dataset opening.
#
# The cap covers DuckDB's own spill files only, not files a query
# writes itself (e.g. the duplicate-row COPY partitions below).
# enable_external_file_cache and preserve_insertion_order are left at
# DuckDB's defaults on purpose: the cache holds only file metadata for
# local Parquet, and preview / metadata samples rely on insertion order
# (`LIMIT` without `ORDER BY`).
_DEFAULT_DUCKDB_THREADS = 2
# Overrides above this are rejected: with 2 analysis workers, more than
# the host's 4 cores per instance only oversubscribes the CPU.
_MAX_DUCKDB_THREADS = 4
_DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE = "10GiB"

# Canonical spelling for every size unit DuckDB accepts (case-
# insensitive). KB/MB/GB/TB are decimal in DuckDB; KiB..TiB binary.
_SIZE_UNITS = {
    "b": ("B", 1),
    "kb": ("KB", 1000),
    "mb": ("MB", 1000**2),
    "gb": ("GB", 1000**3),
    "tb": ("TB", 1000**4),
    "kib": ("KiB", 1024),
    "mib": ("MiB", 1024**2),
    "gib": ("GiB", 1024**3),
    "tib": ("TiB", 1024**4),
}
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$")


def _read_duckdb_threads() -> int:
    raw = os.environ.get("DUCKDB_THREADS")

    if raw is None or raw.strip() == "":
        return _DEFAULT_DUCKDB_THREADS

    try:
        value = int(raw.strip())
    except ValueError:
        value = 0

    if not 1 <= value <= _MAX_DUCKDB_THREADS:
        logger.warning(
            "Ignoring invalid DUCKDB_THREADS=%r (must be an integer from 1 "
            "to %d); using %d.",
            raw,
            _MAX_DUCKDB_THREADS,
            _DEFAULT_DUCKDB_THREADS,
        )
        return _DEFAULT_DUCKDB_THREADS

    return value


def _normalize_size(raw: str) -> str | None:
    """
    `raw` as a DuckDB size string (e.g. "10 gib" -> "10GiB"), or None
    when it is not a number plus a known unit, or is under one byte. A
    zero cap would make DuckDB disable spilling entirely, so it is
    rejected here and never reaches DuckDB.
    """
    match = _SIZE_RE.match(raw)
    if match is None:
        return None

    number, unit = match.groups()
    canonical = _SIZE_UNITS.get(unit.lower())
    if canonical is None:
        return None

    unit_name, multiplier = canonical
    if float(number) * multiplier < 1:
        return None

    return f"{number}{unit_name}"


def _read_duckdb_max_temp_directory_size() -> str:
    raw = os.environ.get("DUCKDB_MAX_TEMP_DIRECTORY_SIZE")

    if raw is None or raw.strip() == "":
        return _DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE

    normalized = _normalize_size(raw)

    if normalized is None:
        logger.warning(
            "Ignoring invalid DUCKDB_MAX_TEMP_DIRECTORY_SIZE=%r (must be a "
            "positive size such as '10GiB'); using %s.",
            raw,
            _DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
        )
        return _DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE

    return normalized


# Step 38: DuckDBStorage.distinct_row_count() computes the exact
# duplicate-row scalar via one-pass physical hash partitioning (see
# that method and _compute_distinct_row_count_partitioned() below)
# instead of a single full-table `SELECT DISTINCT *` - the COPY step
# below writes the dataset out to K independent Parquet partitions
# (bucketed by `hash(row) % K`, so identical rows always land in the
# same partition), and an exact `SELECT DISTINCT *` runs against each
# partition independently, one partition's worth of rows at a time,
# rather than needing the whole table's working set live at once.
#
# 16 was sized against the original 4GB memory_limit (not re-validated
# for Step 91's 1GB default, where the spill safety net below matters
# more): with
# a roughly uniform hash distribution each partition holds on the
# order of 1/16th of the dataset, so even a dataset large enough that
# a single full-table `SELECT DISTINCT *` would exhaust the budget
# shrinks, per partition, to a slice DuckDB can dedupe comfortably
# inside that same budget - with the existing memory_limit/
# temp_directory governance (Step 30) still standing behind each
# partition's own scan as a spill-to-disk safety net for any
# partition that ends up skewed larger than the 1/K average.
#
# Overridable via DUCKDB_DISTINCT_ROW_PARTITIONS, matching the
# plain-env-var pattern already used for DUCKDB_MEMORY_LIMIT/
# DUCKDB_TEMP_ROOT above.
_DEFAULT_DISTINCT_ROW_PARTITION_COUNT = 16


def _read_distinct_row_partition_count() -> int:
    raw = os.environ.get("DUCKDB_DISTINCT_ROW_PARTITIONS")

    if not raw:
        return _DEFAULT_DISTINCT_ROW_PARTITION_COUNT

    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "DUCKDB_DISTINCT_ROW_PARTITIONS must be a positive integer, "
            f"got {raw!r}."
        ) from exc

    if value < 1:
        raise ValueError(
            "DUCKDB_DISTINCT_ROW_PARTITIONS must be a positive integer, "
            f"got {raw!r}."
        )

    return value


# =========================================================
# R6: spill-directory ownership and startup cleanup
#
# Every instance's private spill directory is
# <DUCKDB_TEMP_ROOT>/duckdb_spill_dataset_<32 hex>. close() removes it,
# but a process that exits without closing its datasets (crash, kill,
# tests, scripts) leaves it behind - thousands had accumulated on the
# development host. To make abandoned directories distinguishable from
# live ones - including live ones owned by *another* process sharing
# the same temp root - each instance holds an OS-level exclusive lock
# on <dir>/.owner.lock for its whole lifetime. The OS releases that
# lock when the owning process dies, however it dies, so "lock can be
# acquired" reliably means "no live owner".
# =========================================================

_SPILL_DIR_NAME_RE = re.compile(r"^duckdb_spill_dataset_[0-9a-f]{32}$")
_SPILL_OWNER_LOCK_NAME = ".owner.lock"

# Never touch a directory modified this recently, whatever its lock
# state: closes the window between another process creating its
# directory and taking the owner lock.
_SPILL_CLEANUP_MIN_AGE_SECONDS = 5 * 60

# Directories created before owner locks existed carry no lock file, so
# liveness can't be proven; they're removed only once nothing in them
# has changed for this long. Deleting an idle live one would still be
# harmless (DuckDB recreates its temp directory on demand, verified on
# 1.5.5), this age is an extra margin.
_LEGACY_SPILL_MIN_AGE_SECONDS = 24 * 60 * 60

if os.name == "nt":
    _FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _lock_fd_nonblocking(fd: int) -> None:
    """Take an exclusive, non-blocking OS lock on fd; OSError if held."""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _acquire_spill_owner_lock(temp_dir: str) -> int:
    """
    Create/open <temp_dir>/.owner.lock and hold an exclusive lock on it.
    Returns the open file descriptor; OSError if another handle (this
    process or another) already holds it.
    """
    fd = os.open(
        os.path.join(temp_dir, _SPILL_OWNER_LOCK_NAME),
        os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
    )
    try:
        _lock_fd_nonblocking(fd)
    except OSError:
        os.close(fd)
        raise
    return fd


def _release_spill_owner_lock(fd: int | None) -> None:
    """Best-effort unlock + close; never raises."""
    if fd is None:
        return
    try:
        _unlock_fd(fd)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _remove_spill_dir(temp_dir: str | None, owner_lock_fd: int | None) -> None:
    """
    Release the owner lock, then remove the directory. The lock must be
    released first: Windows can't delete a file with an open handle.
    """
    _release_spill_owner_lock(owner_lock_fd)
    if temp_dir is not None:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _is_link_or_reparse_point(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    if os.name == "nt":
        try:
            attributes = entry.stat(follow_symlinks=False).st_file_attributes
        except OSError:
            return True
        return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _scan_spill_dir(path: str) -> tuple[bool, float] | None:
    """
    Walk a candidate spill directory without following links. Returns
    (has_owner_lock_file, newest_mtime_seen), or None if anything in it
    is a symlink/junction/reparse point or can't be inspected - such a
    directory is never deleted.
    """
    newest = os.lstat(path).st_mtime
    has_lock = False
    pending = [path]

    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if _is_link_or_reparse_point(entry):
                    return None
                info = entry.stat(follow_symlinks=False)
                newest = max(newest, info.st_mtime)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                elif not entry.is_file(follow_symlinks=False):
                    return None
                elif current == path and entry.name == _SPILL_OWNER_LOCK_NAME:
                    has_lock = True

    return has_lock, newest


def cleanup_abandoned_spill_directories(
    root: str | None = None,
    *,
    min_age_seconds: float = _SPILL_CLEANUP_MIN_AGE_SECONDS,
    legacy_min_age_seconds: float = _LEGACY_SPILL_MIN_AGE_SECONDS,
    now: float | None = None,
) -> dict[str, int]:
    """
    R6: remove spill directories whose owner is gone. Never raises.

    Only direct children of ``root`` (default: the configured
    DUCKDB_TEMP_ROOT) named exactly ``duckdb_spill_dataset_<32 hex>``
    that are real directories are considered - nothing else in the temp
    root (other applications' files, uploads, Parquet datasets, which
    live elsewhere anyway) can ever match. A candidate is skipped when:

      - it, or anything inside it, is a symlink/junction/reparse point;
      - it was modified within ``min_age_seconds``;
      - it has an owner lock file that is currently held (a live
        DuckDBStorage in this or any other process);
      - it has no owner lock file (pre-R6 directory) and something in
        it changed within ``legacy_min_age_seconds``.

    Returns counts of removed / skipped / failed directories.
    """
    root = root or _read_duckdb_temp_root()
    now = time.time() if now is None else now
    counts = {"removed": 0, "skipped_active": 0, "skipped_recent": 0, "skipped_unsafe": 0, "failed": 0}

    try:
        entries = list(os.scandir(root))
    except OSError:
        logger.warning("Spill cleanup skipped: cannot list %r.", root, exc_info=True)
        return counts

    for entry in entries:
        if not _SPILL_DIR_NAME_RE.match(entry.name):
            continue

        try:
            if _is_link_or_reparse_point(entry) or not entry.is_dir(follow_symlinks=False):
                counts["skipped_unsafe"] += 1
                continue

            if now - entry.stat(follow_symlinks=False).st_mtime < min_age_seconds:
                counts["skipped_recent"] += 1
                continue

            scanned = _scan_spill_dir(entry.path)

            if scanned is None:
                counts["skipped_unsafe"] += 1
                continue

            has_lock, newest_mtime = scanned

            if has_lock:
                try:
                    fd = _acquire_spill_owner_lock(entry.path)
                except OSError:
                    counts["skipped_active"] += 1
                    continue
                # Owner is gone. Release before deleting (Windows).
                _release_spill_owner_lock(fd)
            elif now - newest_mtime < legacy_min_age_seconds:
                counts["skipped_recent"] += 1
                continue

            shutil.rmtree(entry.path)
            counts["removed"] += 1

        except OSError:
            counts["failed"] += 1
            logger.debug("Could not clean spill directory %r.", entry.path, exc_info=True)

    if any(counts.values()):
        logger.info("Spill directory cleanup in %r: %s", root, counts)

    return counts


def _configure_connection_and_temp_dir(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> tuple[str, int]:
    """
    Apply the configured memory_limit and a private, per-instance
    temp_directory to a freshly opened connection, before any table or
    view is created on it. The directory is namespaced with the same
    unique ``table_name`` every instance already uses, so it can never
    collide with another instance's spill files. Returns the created
    directory's path so the caller can remove it again in close().

    R2: also sets ``threads`` and ``max_temp_directory_size`` (see the
    defaults above). If any setting fails, the directory created here
    is removed before the error propagates - the caller never learned
    its path, so it could not clean it up. Closing the connection
    stays the caller's job.

    R6: also takes the directory's owner lock (see
    cleanup_abandoned_spill_directories) and returns its file
    descriptor with the path; the caller releases it via
    _remove_spill_dir().
    """
    memory_limit = str(_read_duckdb_memory_limit()).replace("'", "''")
    threads = _read_duckdb_threads()
    max_temp_directory_size = _read_duckdb_max_temp_directory_size()
    temp_dir = os.path.join(_read_duckdb_temp_root(), f"duckdb_spill_{table_name}")
    os.makedirs(temp_dir, exist_ok=True)

    escaped_temp_dir = temp_dir.replace("'", "''")
    owner_lock_fd = None

    try:
        owner_lock_fd = _acquire_spill_owner_lock(temp_dir)
        connection.execute(f"PRAGMA memory_limit='{memory_limit}'")
        connection.execute(f"PRAGMA temp_directory='{escaped_temp_dir}'")
        # Both values are validated above: an int >= 1, and a size
        # built only from digits and a known unit - nothing to escape.
        connection.execute(f"SET threads={threads}")
        connection.execute(f"SET max_temp_directory_size='{max_temp_directory_size}'")
    except Exception:
        _remove_spill_dir(temp_dir, owner_lock_fd)
        raise

    return temp_dir, owner_lock_fd


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


@dataclass(frozen=True)
class ColumnStatistics:
    """
    Per-column non-null count, distinct count, and min/max bounds - the
    single aggregate DuckDBStorage.column_statistics() computes at most
    once per instance (see that method's docstring), consumed
    identically by DuckDBMetadataEngine.get_metadata(),
    DuckDBProfilingEngine.basic_statistics(), and
    DuckDBQualityEngine.check_quality() instead of each engine running
    its own separate copy of this same per-column scan (Step 35 - see
    step34_post_step33_scalability_audit.txt /
    step35_shared_column_stats_audit.txt).

    Internal representation only - never returned directly by any HTTP
    route; each consumer still builds its own public response shape
    from these values.
    """

    non_null_count: int
    distinct_count: int
    min_value: object
    max_value: object


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
    (``relation``, ``to_dataframe``, ``schema_info``, ``execute_df``,
    ``execute_one``, the ``connection`` property) and ``close()`` itself
    all acquire it before doing anything. ``row_count``,
    ``column_count`` and ``column_names`` return values fixed at
    construction and never touch the connection, so they don't wait for
    the lock (``row_count`` still raises once closed). That makes
    ``close()`` and any in-flight read mutually exclusive on *this* instance: a read already holding
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

    Step 33: ``distinct_row_count()`` memoizes the one scalar both
    ``DuckDBProfilingEngine.basic_statistics()`` and
    ``DuckDBQualityEngine.check_quality()`` derive their duplicate-row
    count from - the exact distinct-row scan is expensive and
    otherwise ran twice per dataset (see
    step32_post_governance_scalability_audit.txt). Since this instance
    already exists exactly once per dataset and already owns a lock
    serializing every query against its connection, that lock is
    reused here too: whichever caller reaches this method first on a
    fresh instance runs its own copy of the scan and caches the
    result; a concurrent second caller blocks on the same lock and
    then reuses the cached value instead of running the scan again.

    Step 38: the scan itself is no longer a single full-table `SELECT
    COUNT(*) FROM (SELECT DISTINCT * FROM table)` - see
    ``_compute_distinct_row_count_partitioned()`` for the one-pass
    physical hash-partitioning replacement, which never needs the
    whole table's working set live at once.

    Step 35: ``column_statistics()`` applies the exact same memoization
    pattern to the per-column non-null/distinct/min/max aggregate that
    ``DuckDBMetadataEngine.get_metadata()``,
    ``DuckDBProfilingEngine.basic_statistics()``, and
    ``DuckDBQualityEngine.check_quality()`` each used to compute via
    their own separate, unshared full-table-per-column scan (see
    step34_post_step33_scalability_audit.txt). Whichever of the three
    engines reaches it first for this instance pays for the one
    consolidated scan (which computes MIN/MAX too, at no extra scan
    cost, so every consumer's needs are covered by the same result
    regardless of call order); every other caller - including a
    concurrent first caller - reuses the cached mapping.
    """

    def __init__(self, dataframe: pd.DataFrame):
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame.")

        if dataframe.empty:
            raise ValueError("The dataset is empty.")

        self._lock = threading.RLock()
        self._closed = False
        self._init_query_interruption()

        # Step 33: memoized exact distinct-row-count, shared between
        # profiling and quality - see distinct_row_count() below.
        self._distinct_row_count: int | None = None

        # Step 35: memoized per-column statistics (non-null count,
        # distinct count, min, max), shared between metadata,
        # profiling, and quality - see column_statistics() below.
        self._column_statistics: dict[str, ColumnStatistics] | None = None

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

        # None until the helper returns: if the helper itself fails it
        # has already removed its own directory and released its lock.
        self._temp_dir = None
        self._spill_owner_lock_fd = None

        try:
            # Step 30 / R2: explicit memory_limit, threads, spill cap
            # and private spill directory, applied before any table
            # exists on this connection.
            self._temp_dir, self._spill_owner_lock_fd = _configure_connection_and_temp_dir(
                self._connection, self._table_name
            )

            self._connection.register("_source_df", dataframe)
            self._connection.execute(
                f'CREATE TABLE "{self._table_name}" AS SELECT * FROM _source_df'
            )
            self._connection.unregister("_source_df")
        except Exception:
            # Same cleanup as from_parquet(): the instance never reaches
            # a caller, so nobody else would close it.
            self._connection.close()
            _remove_spill_dir(self._temp_dir, self._spill_owner_lock_fd)
            raise

        self._columns = list(dataframe.columns)

        # Fixed at construction - see row_count().
        self._row_count = len(dataframe)

    @classmethod
    def from_parquet(
        cls, parquet_path: str, row_count: int | None = None
    ) -> "DuckDBStorage":
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

        ``row_count``: the file's row count when the caller already
        knows it (ingestion counts every row it writes - see
        ``select_storage_for_ingestion``). When omitted (startup
        recovery), it is counted once here, from the Parquet footer,
        before the instance is shared with any other thread. Either
        way ``row_count()`` never queries or locks afterwards.
        """
        if row_count is not None and (
            isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0
        ):
            raise ValueError("row_count must be a non-negative integer.")

        instance = cls.__new__(cls)

        instance._lock = threading.RLock()
        instance._closed = False
        instance._init_query_interruption()

        # Step 33: memoized exact distinct-row-count, shared between
        # profiling and quality - see distinct_row_count() below.
        instance._distinct_row_count = None

        # Step 35: memoized per-column statistics, shared between
        # metadata, profiling, and quality - see column_statistics()
        # below.
        instance._column_statistics = None

        instance._connection = duckdb.connect(database=":memory:")
        instance._table_name = f"dataset_{uuid.uuid4().hex}"
        instance._parquet_path = parquet_path

        # DuckDB DDL (CREATE VIEW) cannot be a prepared statement, so
        # the path can't be passed as a bound parameter here the way
        # the old CREATE TABLE ... AS SELECT statement did - it is
        # escaped and inlined into the view definition instead.
        escaped_parquet_path = str(parquet_path).replace("'", "''")

        # None until the helper returns: if the helper itself fails it
        # has already removed its own directory and released its lock.
        instance._temp_dir = None
        instance._spill_owner_lock_fd = None

        try:
            # Step 30 / R2: explicit memory_limit, threads, spill cap
            # and private spill directory, applied before the view
            # exists on this connection - same helper, same guarantees
            # as the DataFrame-backed constructor.
            (
                instance._temp_dir,
                instance._spill_owner_lock_fd,
            ) = _configure_connection_and_temp_dir(
                instance._connection, instance._table_name
            )

            instance._connection.execute(
                f'CREATE VIEW "{instance._table_name}" AS '
                f"SELECT * FROM read_parquet('{escaped_parquet_path}')"
            )

            instance._columns = list(
                instance._connection.table(instance._table_name).columns
            )

            if row_count is None:
                row_count = int(
                    instance._connection.execute(
                        f'SELECT COUNT(*) FROM "{instance._table_name}"'
                    ).fetchone()[0]
                )
        except Exception:
            # Not yet returned to anyone, so nobody else will close it:
            # release the connection and spill directory here.
            instance._connection.close()
            _remove_spill_dir(instance._temp_dir, instance._spill_owner_lock_fd)
            raise

        instance._row_count = row_count

        return instance

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise StorageClosedError(
                "This DuckDBStorage instance has already been closed."
            )

    # -----------------------------------------------------
    # R4: interruptible query execution
    #
    # Two things may stop a running query on this connection:
    #   - the active query deadline (data_engine.storage.deadline),
    #     enforced by a per-query timer;
    #   - close(), so deleting a dataset or shutting down never waits
    #     for a long scan to finish on its own.
    # Both go through _interrupt_if_active(), which interrupts only
    # while the *same* query is still registered as active: the token
    # is cleared under _interrupt_guard before the instance lock is
    # released, so a late timer can never interrupt a later, unrelated
    # query on this connection. Other instances (other datasets) have
    # their own connections and are never touched. A query is reported
    # as timed out/closed only after DuckDB itself raised
    # InterruptException for it, i.e. after it actually stopped; the
    # connection stays usable afterwards (verified on DuckDB 1.5.5).
    # -----------------------------------------------------

    def _init_query_interruption(self) -> None:
        self._interrupt_guard = threading.Lock()
        self._active_query_token: object | None = None
        self._active_query_reasons: set | None = None
        self._closing = False

    # DuckDB drops an interrupt that arrives before the query has
    # actually started executing (the flag is reset at query start), and
    # a query is registered as active a moment before execute() begins.
    # So interrupts are re-issued at this interval until the query they
    # target is no longer active; re-interrupting is harmless.
    _INTERRUPT_RETRY_SECONDS = 0.05

    def _interrupt_if_active(self, token: object, reasons: set, reason: str) -> bool:
        """Interrupt only if `token`'s query is still the active one."""
        with self._interrupt_guard:
            if self._active_query_token is not token:
                return False
            reasons.add(reason)
            self._connection.interrupt()
            return True

    def _interrupt_until_stopped(self, token: object, reasons: set, reason: str) -> None:
        """Deadline timer body: keep interrupting until the query ends."""
        while self._interrupt_if_active(token, reasons, reason):
            time.sleep(self._INTERRUPT_RETRY_SECONDS)

    def _interrupt_active_query_for_close(self) -> None:
        with self._interrupt_guard:
            if self._active_query_token is not None:
                self._active_query_reasons.add("closing")
                self._connection.interrupt()

    def _run_interruptible(self, run):
        """
        Run ``run()`` (which executes on self._connection). Caller must
        hold self._lock and have checked _raise_if_closed().
        """
        if self._closing:
            raise StorageClosedError(
                "This DuckDBStorage instance is being closed."
            )

        remaining = remaining_seconds()

        if remaining is not None and remaining <= 0:
            raise QueryTimeoutError("The operation exceeded its time limit.")

        token = object()
        reasons: set[str] = set()

        with self._interrupt_guard:
            self._active_query_token = token
            # close() may have started between the check above and
            # registering this query; it then found nothing to
            # interrupt, so refuse to start instead.
            if self._closing:
                self._active_query_token = None
                raise StorageClosedError(
                    "This DuckDBStorage instance is being closed."
                )
            self._active_query_reasons = reasons

        timer = None

        if remaining is not None:
            timer = threading.Timer(
                remaining,
                self._interrupt_until_stopped,
                args=(token, reasons, "deadline"),
            )
            timer.daemon = True
            timer.start()

        try:
            return run()
        except duckdb.InterruptException as exc:
            if "closing" in reasons:
                raise StorageClosedError(
                    "This DuckDBStorage instance was closed while a query was running."
                ) from exc
            if "deadline" in reasons:
                raise QueryTimeoutError(
                    "The query exceeded its time limit and was stopped."
                ) from exc
            raise
        finally:
            with self._interrupt_guard:
                self._active_query_token = None
                self._active_query_reasons = None
            if timer is not None:
                timer.cancel()

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
                return self._run_interruptible(
                    lambda: self._connection.execute(query).fetchdf()
                )
            return self._run_interruptible(
                lambda: self._connection.execute(query, params).fetchdf()
            )

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
                return self._run_interruptible(
                    lambda: self._connection.execute(query).fetchone()
                )
            return self._run_interruptible(
                lambda: self._connection.execute(query, params).fetchone()
            )

    def distinct_row_count(self, compute) -> int:
        """
        Return this dataset's cached exact distinct-row count,
        computing it only on the first call for this instance.

        ``compute`` is accepted only for backward compatibility with
        existing callers (``data_engine.profiling.duckdb_profiling`` /
        ``data_engine.quality.duckdb_quality``, both still passing
        their own zero-arg callable) and is otherwise ignored: as of
        Step 38 the actual computation is always
        ``_compute_distinct_row_count_partitioned()`` below, since the
        one-pass hash-partitioning it performs needs this instance's
        own table name/connection and can't be expressed as a query
        text handed in from outside. Keeping the parameter (rather
        than dropping it) means neither caller needed to change how it
        calls this method. See the class docstring's Step 33 note for
        why the existing per-instance lock is what makes a concurrent
        second caller reuse the cached value instead of running its
        own copy of the scan.
        """
        with self._lock:
            self._raise_if_closed()

            if self._distinct_row_count is None:
                self._distinct_row_count = self._compute_distinct_row_count_partitioned()

            return self._distinct_row_count

    def _compute_distinct_row_count_partitioned(self) -> int:
        """
        Exact distinct-row count via one-pass physical hash
        partitioning, replacing the old single full-table `SELECT
        COUNT(*) FROM (SELECT DISTINCT * FROM table)` scan (Step 38 -
        see the class docstring's Step 33/38 notes).

        The dataset is COPY'd to a private, per-call temporary Parquet
        directory exactly once, bucketed by ``hash(row) % K`` into K
        partitions (K = ``_read_distinct_row_partition_count()``).
        Because the hash is a pure function of a row's own values,
        two identical rows always hash identically and therefore
        always land in the same partition - so an exact `SELECT
        DISTINCT *` run independently against each partition, summed
        across partitions, is exactly as correct as one `SELECT
        DISTINCT *` over the whole table, while never needing more
        than one partition's worth of rows live at once. A hash
        collision between two *different* rows only ever costs a
        partition some extra non-duplicate rows to distinguish - it
        can never merge two distinct rows into one or split one row's
        duplicates across partitions, so it can't produce a wrong
        answer, only a less evenly balanced one.

        Only ever called from distinct_row_count() while self._lock is
        already held (an RLock, so the nested execute_one() calls
        below are safe), exactly like _compute_column_statistics().
        """
        partition_count = _read_distinct_row_partition_count()
        table = _quote_identifier(self._table_name)

        partition_root = os.path.join(
            self._temp_dir, f"distinct_partitions_{uuid.uuid4().hex}"
        )
        os.makedirs(partition_root, exist_ok=True)
        escaped_root = partition_root.replace("'", "''")

        try:
            # __row is meant as a fresh row alias (so `hash(__row)`
            # means "hash of the whole row"), but even if the dataset
            # happened to have its own column literally named "__row",
            # that would still produce a correct answer, only a
            # differently-distributed one: identical rows always share
            # every column's value - including one named __row - so
            # they'd still hash identically and land in the same
            # partition regardless of which meaning DuckDB resolves.
            self.execute_one(
                f"COPY (SELECT *, hash(__row) % {partition_count} "
                f"AS __distinct_partition FROM {table} AS __row) "
                f"TO '{escaped_root}' (FORMAT PARQUET, "
                "PARTITION_BY (__distinct_partition), "
                "OVERWRITE_OR_IGNORE 1)"
            )

            total = 0

            for partition_index in range(partition_count):
                partition_dir = os.path.join(
                    partition_root, f"__distinct_partition={partition_index}"
                )

                if not os.path.isdir(partition_dir):
                    # No row hashed into this bucket - nothing to scan.
                    continue

                escaped_glob = os.path.join(partition_dir, "*.parquet").replace(
                    "'", "''"
                )
                count = self.execute_one(
                    "SELECT COUNT(*) FROM (SELECT DISTINCT * "
                    "EXCLUDE (__distinct_partition) "
                    f"FROM read_parquet('{escaped_glob}')) AS distinct_partition_rows"
                )[0]
                total += int(count or 0)

            return total
        finally:
            # Best-effort cleanup, same as close()'s own spill-directory
            # removal - never turn cleanup itself into a new failure.
            shutil.rmtree(partition_root, ignore_errors=True)

    def column_statistics(self) -> dict[str, ColumnStatistics]:
        """
        Return this dataset's cached per-column statistics - non-null
        count, distinct count, min, and max for every column - computing
        them via a small number of fused aggregate SQL scans over every
        column the first time this is called for this instance, and
        reusing the cached mapping on every later call, including from
        a different consumer (DuckDBMetadataEngine,
        DuckDBProfilingEngine, or DuckDBQualityEngine - see the class
        docstring's Step 35 note).

        Unlike ``distinct_row_count()``, the query itself isn't
        supplied by the caller: metadata/profiling/quality need
        overlapping but not identical subsets of the same per-column
        statistics (profiling additionally needs min/max; metadata and
        quality don't), so the same batched queries have to serve all
        three regardless of which one runs first - those queries are
        built and run here, not by each caller. Computing min/max
        unconditionally costs nothing extra: DuckDB derives every
        aggregate in a batch's SELECT list from that batch's own single
        table scan.

        Reentrant through ``self.execute_one()`` while ``self._lock``
        is already held - safe only because the lock is an ``RLock``,
        exactly as documented on the class and exercised by
        ``distinct_row_count()`` above.
        """
        with self._lock:
            self._raise_if_closed()

            if self._column_statistics is None:
                self._column_statistics = self._compute_column_statistics()

            return self._column_statistics

    # Step 44: number of columns fused into each _compute_column_statistics()
    # batch query. A single query spanning every column in a wide table
    # forces DuckDB to hold one intermediate hash-table/materialization per
    # column simultaneously for the full scan; measured batching (Step 42/43
    # benchmarks) fuses only this many columns' COUNT/COUNT DISTINCT/MIN/MAX
    # per table scan, bounding that peak working set while still sharing the
    # scan across every column in the batch (as opposed to one query per
    # column, which would multiply the number of full-table scans instead).
    _COLUMN_STATISTICS_BATCH_SIZE = 4

    def _compute_column_statistics(self) -> dict[str, ColumnStatistics]:
        """
        Build and run the fused aggregate queries producing every
        column's non-null count, distinct count, min, and max, batching
        ``_COLUMN_STATISTICS_BATCH_SIZE`` columns' worth of
        COUNT/COUNT DISTINCT/MIN/MAX into each query instead of one
        query spanning every column in the table.

        Only ever called from column_statistics() while self._lock is
        already held.
        """
        if not self._columns:
            return {}

        table = _quote_identifier(self._table_name)
        statistics: dict[str, ColumnStatistics] = {}
        batch_size = self._COLUMN_STATISTICS_BATCH_SIZE

        for batch_start in range(0, len(self._columns), batch_size):
            batch = self._columns[batch_start : batch_start + batch_size]
            select_parts = []

            for offset, column in enumerate(batch):
                quoted = _quote_identifier(column)
                select_parts.append(f"COUNT({quoted}) AS non_null_{offset}")
                select_parts.append(f"COUNT(DISTINCT {quoted}) AS distinct_{offset}")
                select_parts.append(f"MIN({quoted}) AS min_{offset}")
                select_parts.append(f"MAX({quoted}) AS max_{offset}")

            row = self.execute_one(f"SELECT {', '.join(select_parts)} FROM {table}")

            for offset, column in enumerate(batch):
                non_null, distinct, min_value, max_value = row[
                    offset * 4 : offset * 4 + 4
                ]

                statistics[column] = ColumnStatistics(
                    non_null_count=int(non_null or 0),
                    distinct_count=int(distinct or 0),
                    min_value=min_value,
                    max_value=max_value,
                )

        return statistics

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
            return self._run_interruptible(
                lambda: self._connection.table(self._table_name).to_df()
            )

    def row_count(self) -> int:
        """
        The dataset's row count, fixed when this instance was built
        (dataset contents never change after upload).

        Deliberately does NOT take the instance lock: it never touches
        the connection, so it must not wait behind a long scan holding
        that lock - dataset listing and upload responses read it. It
        still raises StorageClosedError once closed, like every other
        read, so a deleted dataset is reported as gone.
        """
        self._raise_if_closed()
        return self._row_count

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

        R4/R6: a query running through execute_df()/execute_one()/
        to_dataframe() is interrupted first instead of being waited
        out, so deleting a dataset or shutting down never blocks for
        the length of a long scan. That query's caller gets
        StorageClosedError - the same "dataset is gone" error it would
        get had the close landed before its query - and any further
        query in the same multi-query operation is refused the same
        way. Only this instance's own connection is interrupted.

        Step 30: DuckDB itself deletes its own spill files from
        temp_directory when the connection closes, but leaves the
        directory itself behind - so this also removes the private
        per-instance temp directory created at construction.
        ``ignore_errors=True`` keeps this a safe, best-effort cleanup
        (e.g. if the directory was already removed by something else)
        rather than turning close() into a new failure point.
        """
        with self._interrupt_guard:
            if not self._closed:
                self._closing = True

        # Interrupt whatever query holds the lock - repeatedly, since an
        # interrupt landing just before a query starts is dropped by
        # DuckDB - until the lock is free. Once _closing is set no new
        # query starts, so this converges as soon as the current one
        # (or the multi-query operation around it) unwinds.
        while True:
            self._interrupt_active_query_for_close()
            if self._lock.acquire(timeout=self._INTERRUPT_RETRY_SECONDS):
                break

        try:
            if self._closed:
                return

            self._connection.close()
            self._closed = True

            _remove_spill_dir(self._temp_dir, self._spill_owner_lock_fd)
            self._spill_owner_lock_fd = None
        finally:
            self._lock.release()
