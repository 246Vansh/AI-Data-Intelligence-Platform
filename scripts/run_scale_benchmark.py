"""STEP 13 - Scale benchmarking harness (empirical verification only).

Isolated, explicitly-executable benchmarking script. It lives outside
``tests/`` on purpose: pytest's default collection (``test_*.py`` /
``*_test.py``) never picks this file up, and it is never imported by
production code, so it cannot affect the regression suite.

Usage:
    python scripts/run_scale_benchmark.py
    python scripts/run_scale_benchmark.py --sizes 10000,100000,1000000
    python scripts/run_scale_benchmark.py --out my_report.json
    python scripts/run_scale_benchmark.py --wide-schema --sizes 10000000
    python scripts/run_scale_benchmark.py --wide-schema --column-stat-batch-size 4

``--wide-schema`` is an opt-in flag that switches synthetic generation
to a wider (~27-column) stress schema - high-cardinality strings,
several numeric columns, low/mid-cardinality categoricals, date/
timestamp columns, and nullable values across many of them, plus a
near-unique ``record_uuid`` - meant to stress ``DuckDBStorage.
column_statistics()`` and the ``quality_iqr`` op at scale. It preserves
``row_id``/``category``/``amount``/``is_active``/``event_time`` so the
existing AnalysisPlan-based ops still run unmodified against it. When
the flag is absent (the default), generation is unchanged.

What it measures (see module docstrings of the functions below for the
exact methodology):

  1. INGESTION   - CSV -> Parquet via ``data_engine.ingestion.
                   ingest_to_parquet`` only (never ``pd.read_csv``).
  2. DUCKDB       - ``data_engine.plan_executor.execute_plan_for_dataset``
                   against a DuckDBStorage-backed Dataset, across four
                   plan shapes (global aggregation, grouped aggregation,
                   filtering, sort+limit), with a storage spy proving
                   ``storage.to_dataframe()`` is never invoked.
  3. PROFILING    - ``data_engine.profiling.basic_statistics_for_dataset``
                   against the same DuckDB dataset.
  4. PANDAS       - The identical AnalysisPlan workflows executed
                   through the legacy Pandas path (PandasStorage +
                   PandasExecutionEngine/PandasProfilingEngine), but
                   only up to ``--pandas-max-rows`` to avoid host OOM.
  5. QUALITY      - ``data_engine.quality.selector.
                   check_quality_for_dataset`` (production DuckDB
                   quality path) against the same DuckDB dataset.
  6. DUPLICATES   - The same ``basic_statistics_for_dataset`` call as
                   (3), on its own fresh DuckDBStorage instance, to
                   time the exact Step 33 shared ``distinct_row_count()``
                   scan (used by both profiling and quality) in
                   isolation. No new duplicate-detection query is
                   written anywhere in this script.
  7. COLUMN STATS - ``DuckDBStorage.column_statistics()`` (the Step 35
                   shared non-null/distinct/min/max scan) called
                   directly on its own fresh DuckDBStorage instance, to
                   time that aggregate in isolation from profiling's or
                   quality's own use of the cached result. No new
                   statistics query is written anywhere in this script.
  8. QUALITY IQR  - ``check_quality_for_dataset`` again, but with this
                   run's own ``column_statistics()``/
                   ``distinct_row_count()`` pre-warmed (and therefore
                   memoized - Steps 33/35) *before* the timer starts, so
                   the timed window isolates the IQR ``quantile_cont``
                   Q1/Q3 scan and the outlier ``COUNT(*) FILTER`` scan -
                   the only aggregates check_quality_for_dataset still
                   has left to run. No new quality/quantile query is
                   written anywhere in this script.

STEP 41B - the ``quality`` (7)/``column_statistics``/``quality_iqr``
(8) ops above additionally sample DuckDB's own ``duckdb_memory()``
table function on a background thread (``_DuckDBMemorySampler``)
during the timed window, reporting each op's peak bytes per DuckDB
internal tag (e.g. ``HASH_TABLE`` for ``COUNT(DISTINCT)``,
``IN_MEMORY_TABLE`` for ``quantile_cont``) alongside the existing
OS-level peak RSS. ``--column-breakdown`` additionally runs each of
those two aggregates one column at a time (separate, opt-in ops, not
part of the default per-size run - see
``_op_duckdb_column_statistics_breakdown``/
``_op_duckdb_quality_iqr_breakdown``) to attribute cost to individual
columns, since ``EXPLAIN ANALYZE`` against the production fused query
folds every column's aggregate into one ``UNGROUPED_AGGREGATE``
operator with a single combined timing.

STEP 43 - ``--column-stat-batch-size [N]`` is an opt-in diagnostic that
recomputes ``DuckDBStorage._compute_column_statistics()``'s exact
per-column non-null-count/``COUNT(DISTINCT)``/``MIN``/``MAX``
semantics, but as fixed-size *batches* of columns (one fused query per
batch of N columns, via ``_op_duckdb_column_statistics_batched``)
instead of the single query fusing every column production uses. Unlike
``--column-breakdown`` (one query per column - the finest possible
grain, used to attribute cost), this measures whether an intermediate
batch width trades total wall-clock time for lower peak memory (fewer
concurrent per-column hash tables/min-max buffers live at once).
Reports elapsed time, peak RSS, per-tag DuckDB memory peaks (via the
same ``_DuckDBMemorySampler`` used elsewhere), and the exact per-column
(non_null_count, distinct_count, min_value, max_value) results, so they
can be diffed against ``duckdb_column_statistics``'s own output to
confirm batching only changes performance, not correctness. Runs
alongside (not instead of) the existing per-size ops; when the flag is
omitted, no batched op runs and every other op's behavior is unchanged.

STEP 38A - DuckDB memory/spill governance (Step 30) is exercised for
every DuckDB-backed worker op: each gets its own isolated spill
directory under ``--duckdb-temp-root`` (default: system temp dir) and
the configured ``--duckdb-memory-limit`` (default: 4GB, matching
production), passed the only way production itself reads them - the
``DUCKDB_MEMORY_LIMIT``/``DUCKDB_TEMP_ROOT`` environment variables
consumed by ``data_engine.storage.duckdb_storage`` - since
``DuckDBStorage.from_parquet`` takes no such parameters and is not
modified here. Spill-file bytes/count are measured just before that
worker's storage closes (close() deletes the spill directory), and the
per-invocation spill directory is removed by the parent afterwards
regardless of success, failure, or a subprocess timeout/kill.

Every measured operation runs in its own subprocess ("worker mode",
``--worker``). This is the key methodological choice: peak RSS is read
once, right before the worker process exits, via the OS's own
cumulative "peak working set" counter for that process. Running one
operation per process means that counter reflects *only* that
operation - it can never be inflated by a previous operation's
now-freed memory the way an in-process, same-run measurement would be.

Synthetic data is generated and streamed to Parquet in bounded chunks
(default 250k rows/chunk) - no full-size Python list or DataFrame is
ever built to do it. All multi-gigabyte CSV/Parquet artifacts are
removed immediately after the size that produced them finishes, not
held until the whole run ends.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 5_000_000, 10_000_000]
DEFAULT_PANDAS_MAX_ROWS = 100_000
DEFAULT_TIME_BUDGET_SECONDS = 1800
# Single per-operation timeout ceiling, replacing the previous
# hardcoded 600s (gen_csv/ingest) and 300s (duckdb/profiling/pandas)
# constants - set to the larger of the two so no existing operation
# becomes stricter than before.
DEFAULT_OP_TIMEOUT_SECONDS = 600.0
# Matches data_engine.storage.duckdb_storage's own
# _DEFAULT_DUCKDB_MEMORY_LIMIT / _read_duckdb_temp_root() defaults -
# kept as separate constants here (not imported) so this script never
# depends on that module's private names.
DEFAULT_DUCKDB_MEMORY_LIMIT = "4GB"
# STEP 43 - sensible default batch width for the opt-in
# --column-stat-batch-size experiment: splits the wide (~27-column)
# schema into ~7 batches, small enough to noticeably shrink the number
# of columns fused into any one query without making per-batch
# dispatch overhead dominate.
DEFAULT_COLUMN_STAT_BATCH_SIZE = 4
DEFAULT_DUCKDB_TEMP_ROOT = tempfile.gettempdir()
# Rough worst-case bytes/row for the synthetic schema below, used only
# for a pre-flight free-disk-space check before generating a size.
BYTES_PER_ROW_ESTIMATE = 120

CATEGORY_POOL = [f"segment_{i:02d}" for i in range(20)]

SYNTHETIC_SCHEMA = pa.schema(
    [
        ("row_id", pa.int64()),
        ("category", pa.string()),
        ("amount", pa.float64()),
        ("is_active", pa.bool_()),
        ("event_time", pa.timestamp("s")),
    ]
)

# =========================================================
# Opt-in wide (~27-column) stress schema (--wide-schema), used only to
# exercise DuckDBStorage.column_statistics() and the quality_iqr op at
# scale - it is never touched by the default generation path above.
# ``row_id``/``category``/``amount``/``is_active``/``event_time`` are
# generated identically to the default schema so the existing
# AnalysisPlan-based ops (_build_plan references ``amount``/
# ``category``) remain valid against a wide-schema dataset too.
# =========================================================

STATUS_POOL = [f"status_{i}" for i in range(5)]
REGION_POOL = [f"region_{i}" for i in range(8)]
TIER_POOL = ["bronze", "silver", "gold", "platinum"]
CHANNEL_POOL = [f"channel_{i}" for i in range(6)]
ZIP_POOL = [f"{i:05d}" for i in range(500)]
CONSTANT_FLAG_VALUE = "constant"
# Small word bank combined a few words at a time to build a
# higher-cardinality (but not necessarily unique) free-text column.
_NOTE_WORD_POOL = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "north", "south", "east", "west", "primary", "secondary", "backup",
    "urgent", "routine", "pending", "review", "closed", "open", "draft",
    "final", "legacy", "archived", "active", "inactive", "verified",
    "flagged", "priority", "standard", "express", "manual", "automated",
    "internal", "external", "shared", "private", "public", "restricted",
    "sample", "test", "production", "staging", "batch", "stream", "queue",
    "sync", "async", "cached",
]

WIDE_SYNTHETIC_SCHEMA = pa.schema(
    [
        ("row_id", pa.int64()),
        ("record_uuid", pa.string()),
        ("category", pa.string()),
        ("status", pa.string()),
        ("region", pa.string()),
        ("tier", pa.string()),
        ("channel", pa.string()),
        ("zip_code", pa.string()),
        ("constant_flag", pa.string()),
        ("customer_name", pa.string()),
        ("email", pa.string()),
        ("free_text_note", pa.string()),
        ("amount", pa.float64()),
        ("quantity", pa.int64()),
        ("unit_price", pa.float64()),
        ("discount_pct", pa.float64()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("account_balance", pa.float64()),
        ("score", pa.float64()),
        ("notes_len", pa.int64()),
        ("is_active", pa.bool_()),
        ("is_verified", pa.bool_()),
        ("event_time", pa.timestamp("s")),
        ("signup_date", pa.date32()),
        ("last_login_ts", pa.timestamp("s")),
        ("updated_at", pa.timestamp("s")),
    ]
)

# Rough worst-case bytes/row for the wide (~27-column) schema above -
# several string/date columns push this well above the narrow
# schema's estimate. Used only for the --wide-schema pre-flight
# free-disk-space check.
WIDE_BYTES_PER_ROW_ESTIMATE = 420


# =========================================================
# Peak-RSS measurement (no new third-party dependency: psutil is not
# installed, and Windows has no `resource` module - so peak working
# set is read straight from the OS via ctypes on win32, and via
# resource.getrusage on POSIX).
# =========================================================


def peak_rss_bytes() -> Optional[int]:
    """Best-effort OS-reported peak resident memory of *this* process."""

    if sys.platform == "win32":
        try:
            import ctypes.wintypes as wintypes

            class _ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            # Explicit argtypes/restype are required here: without them
            # ctypes marshals the HANDLE as a truncated 32-bit int on
            # 64-bit Windows and GetProcessMemoryInfo silently fails.
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetCurrentProcess.argtypes = []
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_ProcessMemoryCounters),
                wintypes.DWORD,
            ]

            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
            handle = kernel32.GetCurrentProcess()
            ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return int(counters.PeakWorkingSetSize) if ok else None
        except Exception:
            return None

    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # Linux reports ru_maxrss in KB, macOS in bytes.
        return int(usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024))
    except Exception:
        return None


# =========================================================
# Deterministic, chunked synthetic data generation
# =========================================================


def generate_synthetic_csv(
    path: str,
    num_rows: int,
    seed: int = 42,
    chunk_size: int = 250_000,
    wide: bool = False,
) -> int:
    """Stream ``num_rows`` of deterministic, typed synthetic data to a
    CSV file at ``path``, ``chunk_size`` rows at a time.

    Never holds more than one chunk's worth of columns in memory -
    each chunk is built as numpy arrays, handed to pyarrow as a
    RecordBatch, and serialized straight to the open file handle via
    ``pyarrow.csv.write_csv`` (only the first chunk writes a header).
    Deterministic: the same (num_rows, seed, wide) always produces
    byte-identical output, via ``numpy.random.default_rng(seed)``.

    When ``wide`` is False (the default), this is the original,
    unchanged narrow schema: row_id (int64), category (string), amount
    (float64), is_active (bool), event_time (datetime/timestamp[s]).

    When ``wide`` is True, generates the opt-in ~27-column stress
    schema (``WIDE_SYNTHETIC_SCHEMA``) instead - high-cardinality
    strings (``customer_name``/``email`` keyed off ``row_id``, plus a
    free-text column), several numeric columns (with an intentional
    IQR outlier fraction in ``discount_pct``), low/mid-cardinality
    categoricals, date/timestamp columns, nullable values on several
    columns (via pyarrow's ``mask=`` so they land as true SQL NULLs,
    not NaN), and a near-unique ``record_uuid``. ``row_id``,
    ``category``, ``amount``, ``is_active``, and ``event_time`` are
    generated exactly as in the narrow schema so the existing
    AnalysisPlan-based benchmark ops (which reference ``amount``/
    ``category``) stay valid against a wide-schema dataset too.
    """

    rng = np.random.default_rng(seed)
    base_ts = np.datetime64("2020-01-01T00:00:00", "s")
    five_years_seconds = 60 * 60 * 24 * 365 * 5
    base_date = np.datetime64("2015-01-01", "D")
    ten_years_days = 365 * 10

    written = 0
    with open(path, "wb") as fh:
        first_chunk = True
        while written < num_rows:
            n = min(chunk_size, num_rows - written)

            row_id = np.arange(written, written + n, dtype=np.int64)
            category = rng.choice(CATEGORY_POOL, size=n)
            amount = rng.uniform(0, 10_000, size=n)
            is_active = rng.integers(0, 2, size=n).astype(bool)
            offsets = rng.integers(0, five_years_seconds, size=n)
            event_time = base_ts + offsets.astype("timedelta64[s]")

            if not wide:
                batch = pa.record_batch(
                    [
                        pa.array(row_id, type=pa.int64()),
                        pa.array(category, type=pa.string()),
                        pa.array(amount, type=pa.float64()),
                        pa.array(is_active, type=pa.bool_()),
                        pa.array(event_time, type=pa.timestamp("s")),
                    ],
                    schema=SYNTHETIC_SCHEMA,
                )
            else:
                row_id_str = row_id.astype(str)

                # Near-unique: row_id makes every value distinct, a
                # random suffix keeps it looking like a real token
                # rather than a bare integer restated as a string.
                record_uuid = np.char.add(
                    np.char.add("rid-", row_id_str),
                    np.char.add("-", rng.integers(0, 1_000_000, size=n).astype(str)),
                )

                status = rng.choice(STATUS_POOL, size=n)
                region = rng.choice(REGION_POOL, size=n)
                tier = rng.choice(TIER_POOL, size=n)
                channel = rng.choice(CHANNEL_POOL, size=n)
                zip_code = rng.choice(ZIP_POOL, size=n)
                constant_flag = np.full(n, CONSTANT_FLAG_VALUE, dtype=object)

                # High-cardinality strings keyed off row_id (fully
                # vectorized, no per-row Python loop).
                customer_name = np.char.add("customer_", row_id_str)
                email = np.char.add(np.char.add("user", row_id_str), "@example.com")

                word_indices = rng.integers(0, len(_NOTE_WORD_POOL), size=(n, 5))
                words = np.array(_NOTE_WORD_POOL)[word_indices]
                free_text_note = words[:, 0]
                for col in range(1, words.shape[1]):
                    free_text_note = np.char.add(
                        np.char.add(free_text_note, " "), words[:, col]
                    )

                quantity = rng.integers(1, 500, size=n).astype(np.int64)
                unit_price = rng.uniform(1, 1_000, size=n)
                discount_pct = np.clip(rng.normal(0.1, 0.05, size=n), 0.0, 1.0)
                # Force a small, deterministic fraction of genuine IQR
                # outliers so quality_iqr's outlier-count path has
                # something to find at every size.
                outlier_mask = rng.random(n) < 0.01
                discount_pct = np.where(
                    outlier_mask, rng.uniform(5.0, 10.0, size=n), discount_pct
                )
                latitude = rng.uniform(-90.0, 90.0, size=n)
                longitude = rng.uniform(-180.0, 180.0, size=n)
                account_balance = rng.normal(5_000, 2_500, size=n)
                score = rng.uniform(0, 100, size=n)
                notes_len = rng.integers(0, 500, size=n).astype(np.int64)

                is_verified = rng.integers(0, 2, size=n).astype(bool)

                signup_date = base_date + rng.integers(
                    0, ten_years_days, size=n
                ).astype("timedelta64[D]")
                last_login_ts = base_ts + rng.integers(
                    0, five_years_seconds, size=n
                ).astype("timedelta64[s]")
                updated_at = base_ts + rng.integers(
                    0, five_years_seconds, size=n
                ).astype("timedelta64[s]")

                null_customer_name = rng.random(n) < 0.05
                null_email = rng.random(n) < 0.05
                null_free_text = rng.random(n) < 0.15
                null_quantity = rng.random(n) < 0.02
                null_account_balance = rng.random(n) < 0.05
                null_is_verified = rng.random(n) < 0.03
                null_signup_date = rng.random(n) < 0.04
                null_last_login = rng.random(n) < 0.10

                batch = pa.record_batch(
                    [
                        pa.array(row_id, type=pa.int64()),
                        pa.array(record_uuid, type=pa.string()),
                        pa.array(category, type=pa.string()),
                        pa.array(status, type=pa.string()),
                        pa.array(region, type=pa.string()),
                        pa.array(tier, type=pa.string()),
                        pa.array(channel, type=pa.string()),
                        pa.array(zip_code, type=pa.string()),
                        pa.array(constant_flag, type=pa.string()),
                        pa.array(
                            customer_name, type=pa.string(), mask=null_customer_name
                        ),
                        pa.array(email, type=pa.string(), mask=null_email),
                        pa.array(
                            free_text_note, type=pa.string(), mask=null_free_text
                        ),
                        pa.array(amount, type=pa.float64()),
                        pa.array(quantity, type=pa.int64(), mask=null_quantity),
                        pa.array(unit_price, type=pa.float64()),
                        pa.array(discount_pct, type=pa.float64()),
                        pa.array(latitude, type=pa.float64()),
                        pa.array(longitude, type=pa.float64()),
                        pa.array(
                            account_balance,
                            type=pa.float64(),
                            mask=null_account_balance,
                        ),
                        pa.array(score, type=pa.float64()),
                        pa.array(notes_len, type=pa.int64()),
                        pa.array(is_active, type=pa.bool_()),
                        pa.array(
                            is_verified, type=pa.bool_(), mask=null_is_verified
                        ),
                        pa.array(event_time, type=pa.timestamp("s")),
                        pa.array(
                            signup_date, type=pa.date32(), mask=null_signup_date
                        ),
                        pa.array(
                            last_login_ts,
                            type=pa.timestamp("s"),
                            mask=null_last_login,
                        ),
                        pa.array(updated_at, type=pa.timestamp("s")),
                    ],
                    schema=WIDE_SYNTHETIC_SCHEMA,
                )

            table = pa.Table.from_batches([batch])
            pa_csv.write_csv(
                table, fh, write_options=pa_csv.WriteOptions(include_header=first_chunk)
            )
            first_chunk = False
            written += n

    return written


# =========================================================
# Spy storage - proves DuckDB paths never materialize a DataFrame for
# raw data (only the already-aggregated result becomes one).
# =========================================================


def _make_spy_duckdb_storage():
    from data_engine.storage.duckdb_storage import DuckDBStorage

    class _SpyDuckDBStorage(DuckDBStorage):
        def to_dataframe(self):
            self.to_dataframe_calls = getattr(self, "to_dataframe_calls", 0) + 1
            return super().to_dataframe()

    return _SpyDuckDBStorage


def _apply_duckdb_governance(args: dict) -> None:
    """
    Set ``DUCKDB_MEMORY_LIMIT``/``DUCKDB_TEMP_ROOT`` for this worker
    process before any ``DuckDBStorage`` is constructed.

    This is the only knob production itself exposes (see
    ``data_engine.storage.duckdb_storage._read_duckdb_memory_limit``/
    ``_read_duckdb_temp_root``) - ``DuckDBStorage.from_parquet`` takes
    no such parameters, and is not modified here. Every worker op runs
    in its own subprocess, so setting these process-wide env vars here
    cannot leak into any other op or into the parent orchestrator.
    """
    if args.get("duckdb_memory_limit"):
        os.environ["DUCKDB_MEMORY_LIMIT"] = str(args["duckdb_memory_limit"])
    if args.get("duckdb_temp_root"):
        os.environ["DUCKDB_TEMP_ROOT"] = str(args["duckdb_temp_root"])


def _measure_spill(storage) -> dict:
    """
    Best-effort total size/count of spill files DuckDB has written so
    far under ``storage``'s own private ``temp_directory``.

    Must be called before ``storage.close()``, which deletes that
    directory (see ``DuckDBStorage.close``'s docstring). Reaches into
    the private ``_temp_dir`` attribute rather than reconstructing the
    ``duckdb_spill_<table_name>`` naming convention itself, so this
    stays correct even if that convention ever changes - production
    code is not modified to expose it any more publicly than that.
    """
    temp_dir = getattr(storage, "_temp_dir", None)
    if not temp_dir or not os.path.isdir(temp_dir):
        return {"spill_bytes": 0, "spill_file_count": 0}

    total_bytes = 0
    file_count = 0
    for root, _dirs, files in os.walk(temp_dir):
        for name in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, name))
                file_count += 1
            except OSError:
                pass
    return {"spill_bytes": total_bytes, "spill_file_count": file_count}


class _DuckDBMemorySampler:
    """
    STEP 41B - benchmark-only diagnostic (no production code touched):
    samples DuckDB's own ``duckdb_memory()`` table function (per-tag
    ``memory_usage_bytes`` - e.g. ``HASH_TABLE``, ``IN_MEMORY_TABLE``,
    ``ORDER_BY``) on a background thread via a second cursor on the
    same connection, while the timed operation runs on the storage's
    own cursor. Tracks the peak bytes seen per tag across the
    sampling window, attributing an operation's memory to a specific
    DuckDB internal subsystem instead of only the OS-level peak RSS
    the rest of this script already measures - e.g. distinguishing
    ``COUNT(DISTINCT ...)``'s per-column hash tables (tag
    ``HASH_TABLE``) from ``quantile_cont``'s per-column buffers (tag
    ``IN_MEMORY_TABLE``, confirmed empirically - not ``ORDER_BY``).

    Uses ``connection.cursor()`` - DuckDB's own documented mechanism
    for a second thread to query the same database concurrently
    without touching the first cursor/thread's in-flight query - so
    this never contends with ``DuckDBStorage``'s own per-instance
    lock (the sampler's cursor bypasses that lock entirely, exactly
    like any other direct/diagnostic use of the ``connection``
    property the class docstring already sanctions).

    ``duckdb_memory()`` reports *live*, not historical, usage, so a
    peak recorded here is only a lower bound on the operation's true
    peak: it can only ever reflect whatever the sampling thread
    happened to observe while that memory was actually held. A finer
    poll ``interval`` narrows that gap at the cost of more sampling
    overhead.
    """

    def __init__(self, connection, interval: float = 0.05):
        self._cursor = connection.cursor()
        self._interval = interval
        self._peak: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                for tag, value in self._cursor.execute(
                    "SELECT tag, memory_usage_bytes FROM duckdb_memory()"
                ).fetchall():
                    if value and value > self._peak.get(tag, 0):
                        self._peak[tag] = int(value)
            except Exception:
                # Best-effort only - a failed sample (e.g. the
                # connection closing mid-poll) must never fail the
                # timed operation it is only observing.
                pass
            self._stop.wait(self._interval)

    def __enter__(self) -> "_DuckDBMemorySampler":
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def peak_by_tag(self) -> dict[str, int]:
        return {tag: bytes_ for tag, bytes_ in self._peak.items() if bytes_ > 0}


def _build_plan(kind: str):
    from data_engine.analysis_plan import AnalysisPlan, FilterCondition

    if kind == "global_agg":
        return AnalysisPlan(metric="amount", aggregation="sum")
    if kind == "grouped_agg":
        return AnalysisPlan(metric="amount", aggregation="sum", group_by=["category"])
    if kind == "filter":
        return AnalysisPlan(
            metric="amount",
            aggregation="sum",
            filters=[FilterCondition("amount", ">", 5000.0)],
        )
    if kind == "sort_limit":
        return AnalysisPlan(
            metric="amount",
            aggregation="sum",
            group_by=["category"],
            sort="desc",
            sort_by="metric",
            limit=10,
        )
    raise ValueError(f"Unknown plan kind: {kind}")


# =========================================================
# Worker operations - each one runs in its own subprocess so its peak
# RSS reading is never contaminated by a previous operation.
# =========================================================


def _op_gen_csv(args: dict) -> dict:
    t0 = time.perf_counter()
    rows_written = generate_synthetic_csv(
        args["csv_path"],
        args["rows"],
        seed=args.get("seed", 42),
        wide=bool(args.get("wide", False)),
    )
    elapsed = time.perf_counter() - t0
    return {
        "elapsed_s": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "rows": rows_written,
        "output_bytes": os.path.getsize(args["csv_path"]),
    }


def _op_ingest(args: dict) -> dict:
    from data_engine.ingestion import ingest_to_parquet

    input_bytes = os.path.getsize(args["csv_path"])
    t0 = time.perf_counter()
    with open(args["csv_path"], "rb") as fh:
        result = ingest_to_parquet(fh, args["dataset_id"], args["storage_root"])
    elapsed = time.perf_counter() - t0
    return {
        "elapsed_s": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "rows": result.row_count,
        "input_bytes": input_bytes,
        "output_bytes": os.path.getsize(result.parquet_path),
        "parquet_path": result.parquet_path,
    }


def _op_duckdb(args: dict) -> dict:
    _apply_duckdb_governance(args)
    from data_engine.dataset import Dataset
    from data_engine.plan_executor import execute_plan_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)
        plan = _build_plan(args["kind"])

        t0 = time.perf_counter()
        result_df = execute_plan_for_dataset(dataset, plan)
        elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(result_df.row_count),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_profile(args: dict) -> dict:
    _apply_duckdb_governance(args)
    from data_engine.dataset import Dataset
    from data_engine.profiling import basic_statistics_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)

        t0 = time.perf_counter()
        stats = basic_statistics_for_dataset(dataset)
        elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(stats["row_count"]),
            "duplicate_rows": int(stats.get("duplicate_rows") or 0),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_quality(args: dict) -> dict:
    """
    Runs the production DuckDB quality path (``data_engine.quality.
    selector.check_quality_for_dataset``) against the benchmark
    dataset. No quality logic is reimplemented here - this only calls
    the existing entry point, which itself routes duplicate-row
    detection through ``storage.distinct_row_count()`` (Step 33).
    """
    _apply_duckdb_governance(args)
    from data_engine.dataset import Dataset
    from data_engine.quality.selector import check_quality_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)

        sampler = _DuckDBMemorySampler(storage.connection)
        with sampler:
            t0 = time.perf_counter()
            report = check_quality_for_dataset(dataset)
            elapsed = time.perf_counter() - t0

        duplicate_issue = next(
            (
                issue
                for issue in report.get("issues", [])
                if issue.get("type") == "duplicate_rows"
            ),
            None,
        )

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(report.get("issue_count", 0)),
            "status": report.get("status"),
            "duplicate_rows": int(duplicate_issue["count"]) if duplicate_issue else 0,
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            "duckdb_memory_peak_by_tag": sampler.peak_by_tag(),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_duplicates(args: dict) -> dict:
    """
    Exercises the exact Step 33 shared duplicate-row computation
    (``storage.distinct_row_count()``) through the production DuckDB
    profiling path - the same ``basic_statistics_for_dataset`` call
    ``_op_duckdb_profile`` uses - but on its own fresh DuckDBStorage
    instance/subprocess, so the underlying `SELECT DISTINCT *` scan is
    genuinely (re-)run here rather than reusing another op's cached
    scalar. No new duplicate-detection query is written in this file.
    """
    _apply_duckdb_governance(args)
    from data_engine.dataset import Dataset
    from data_engine.profiling import basic_statistics_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)

        t0 = time.perf_counter()
        stats = basic_statistics_for_dataset(dataset)
        elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(stats["row_count"]),
            "duplicate_rows": int(stats.get("duplicate_rows") or 0),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_column_statistics(args: dict) -> dict:
    """
    Isolates the exact Step 35 shared ``column_statistics()`` scan
    (per-column non-null count, ``COUNT(DISTINCT)``, min, max -
    memoized on ``DuckDBStorage``; see ``DuckDBStorage.
    column_statistics()``/``_compute_column_statistics()``) on its own
    fresh DuckDBStorage instance/subprocess, so its cost is measured
    independently of profiling's or quality's own use of the cached
    result. No new statistics query is written anywhere in this script
    - this only calls the existing production method.
    """
    _apply_duckdb_governance(args)

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        sampler = _DuckDBMemorySampler(storage.connection)
        with sampler:
            t0 = time.perf_counter()
            stats = storage.column_statistics()
            elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": len(stats),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            "duckdb_memory_peak_by_tag": sampler.peak_by_tag(),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_quality_iqr(args: dict) -> dict:
    """
    Isolates the quality path's IQR ``quantile_cont``/outlier-count cost
    (``data_engine.quality.duckdb_quality.DuckDBQualityEngine.
    check_quality``'s Q1/Q3 and outlier-count aggregates) from the
    ``column_statistics()``/``distinct_row_count()`` scans
    ``check_quality_for_dataset`` also performs.

    Pre-warms this storage instance's memoized ``column_statistics()``/
    ``distinct_row_count()`` (Steps 33/35) *before* starting the timer,
    so the timed ``check_quality_for_dataset()`` call below reuses
    those already-cached scalars instead of recomputing them - leaving
    the IQR quantile scan and the outlier ``COUNT(*) FILTER`` scan (the
    only aggregates ``check_quality_for_dataset`` still has left to
    run) as the cost inside the timed window. No new quality/quantile
    query is written anywhere in this script - this only calls the
    existing production entry point, with its own memoization doing the
    isolation.
    """
    _apply_duckdb_governance(args)
    from data_engine.dataset import Dataset
    from data_engine.quality.selector import check_quality_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)

        # Pre-warm outside the timed window - see docstring above.
        storage.column_statistics()
        storage.distinct_row_count(lambda: 0)

        sampler = _DuckDBMemorySampler(storage.connection)
        with sampler:
            t0 = time.perf_counter()
            report = check_quality_for_dataset(dataset)
            elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(report.get("issue_count", 0)),
            "status": report.get("status"),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            "duckdb_memory_peak_by_tag": sampler.peak_by_tag(),
            **spill,
        }
    finally:
        storage.close()


def _op_duckdb_column_statistics_breakdown(args: dict) -> dict:
    """
    STEP 41B - opt-in diagnostic (``--column-breakdown``), not part of
    the default per-size run: re-runs the same non-null/``COUNT
    (DISTINCT)``/min/max aggregate ``DuckDBStorage.
    _compute_column_statistics()`` computes, but as one single-column
    query per column instead of one fused multi-column query.

    ``EXPLAIN ANALYZE`` against the production fused query (verified
    interactively while auditing this bottleneck, not committed
    anywhere) showed DuckDB folds every column's ``COUNT(DISTINCT
    ...)``/``MIN``/``MAX`` into a single ``UNGROUPED_AGGREGATE``
    operator with one combined timing for the whole node - so neither
    ``EXPLAIN ANALYZE`` nor the production method itself can attribute
    cost to an individual column. Running each column as its own
    query is the only way to get a per-column cost breakdown, and is
    intentionally kept out of the default run (it re-scans the table
    once per column instead of once total, which is far slower and
    would misrepresent the production op's own cost).

    No production code is called for this query - only
    ``storage.execute_one()`` with hand-built SQL mirroring
    ``DuckDBStorage._compute_column_statistics()``'s own per-column
    SELECT list, so ``COUNT(DISTINCT)``'s cost is isolated from
    ``MIN``/``MAX`` exactly as it is in the real aggregate.
    """
    _apply_duckdb_governance(args)
    from data_engine.storage.duckdb_storage import _quote_identifier

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        table = _quote_identifier(storage.table_name)
        per_column = []

        for column in storage.column_names():
            quoted = _quote_identifier(column)
            t0 = time.perf_counter()
            row = storage.execute_one(
                f"SELECT COUNT({quoted}) AS non_null, "
                f"COUNT(DISTINCT {quoted}) AS distinct_count, "
                f"MIN({quoted}) AS min_value, MAX({quoted}) AS max_value "
                f"FROM {table}"
            )
            elapsed = time.perf_counter() - t0
            per_column.append(
                {
                    "column": column,
                    "elapsed_s": elapsed,
                    "distinct_count": int(row[1] or 0),
                }
            )

        return {
            "peak_rss_bytes": peak_rss_bytes(),
            "per_column": per_column,
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
        }
    finally:
        storage.close()


def _op_duckdb_quality_iqr_breakdown(args: dict) -> dict:
    """
    STEP 41B - opt-in diagnostic (``--column-breakdown``), not part of
    the default per-size run: re-runs the IQR path's ``quantile_cont``
    Q1/Q3 aggregate one numeric column at a time instead of as the
    single fused multi-column query
    ``DuckDBQualityEngine.check_quality`` builds, for the same reason
    and via the same ``EXPLAIN ANALYZE`` finding documented on
    ``_op_duckdb_column_statistics_breakdown`` above (DuckDB fuses
    every column's aggregates into one ``UNGROUPED_AGGREGATE``
    operator with one combined timing).

    Reuses ``data_engine.quality.duckdb_quality``'s own
    ``_is_numeric_duckdb_type`` so the numeric-column selection is
    identical to production's - no new numeric-type classification
    logic is written here. No production code is called for the
    per-column queries themselves; the outlier ``COUNT(*) FILTER``
    step is intentionally not reproduced here, since the audit
    identified ``quantile_cont`` (not the outlier count) as the
    IQR path's expensive aggregate.
    """
    _apply_duckdb_governance(args)
    from data_engine.storage.duckdb_storage import _quote_identifier
    from data_engine.quality.duckdb_quality import _is_numeric_duckdb_type

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        table = _quote_identifier(storage.table_name)
        schema = storage.schema_info()
        numeric_columns = [
            column
            for column in storage.column_names()
            if _is_numeric_duckdb_type(schema[column])
        ]
        per_column = []

        for column in numeric_columns:
            quoted = _quote_identifier(column)
            t0 = time.perf_counter()
            storage.execute_one(
                f"SELECT quantile_cont({quoted}, 0.25) AS q1, "
                f"quantile_cont({quoted}, 0.75) AS q3 FROM {table}"
            )
            elapsed = time.perf_counter() - t0
            per_column.append({"column": column, "elapsed_s": elapsed})

        return {
            "peak_rss_bytes": peak_rss_bytes(),
            "per_column": per_column,
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
        }
    finally:
        storage.close()


def _json_safe_value(value):
    """
    Best-effort JSON-serializable encoding for a raw DuckDB scalar
    (e.g. ``datetime.date``/``datetime.datetime``, ``decimal.Decimal``)
    returned by ``MIN``/``MAX``, so
    ``_op_duckdb_column_statistics_batched``'s exact per-column results
    can round-trip through this script's ``json.dump`` without crashing
    on a type the stdlib encoder doesn't know. ``None``/``bool``/``int``/
    ``float``/``str`` already round-trip and pass through unchanged.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _op_duckdb_column_statistics_batched(args: dict) -> dict:
    """
    STEP 43 - opt-in diagnostic (``--column-stat-batch-size``), not
    part of the default per-size run: recomputes the exact same
    non-null-count/``COUNT(DISTINCT)``/``MIN``/``MAX`` aggregate
    ``DuckDBStorage._compute_column_statistics()`` computes, but issues
    one fused query per fixed-size *batch* of columns instead of one
    query fusing every column at once.

    Each batch's SELECT list mirrors ``_compute_column_statistics()``'s
    own per-column shape exactly (``COUNT(col)`` for the non-null
    count, ``COUNT(DISTINCT col)``, ``MIN(col)``, ``MAX(col)``, with
    index-based aliases scoped to that batch), so the only variable
    being measured is how many columns share one query - not any
    change in aggregate semantics. No production code is called for
    the batched queries themselves (only ``storage.execute_one()`` with
    hand-built SQL); this exists purely to compare wall-clock time and
    DuckDB memory-tag peaks (``_DuckDBMemorySampler``, e.g.
    ``HASH_TABLE``) against the unbatched ``duckdb_column_statistics``
    op's single fused query, particularly at the wide (~27-column)
    stress schema.

    Returns the exact per-column ``(non_null_count, distinct_count,
    min_value, max_value)`` results (JSON-safe via
    ``_json_safe_value``) so they can be diffed against
    ``column_statistics()``'s own output to confirm batching changes
    only performance, never correctness.
    """
    _apply_duckdb_governance(args)
    from data_engine.storage.duckdb_storage import _quote_identifier

    batch_size = max(1, int(args.get("batch_size") or DEFAULT_COLUMN_STAT_BATCH_SIZE))

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        table = _quote_identifier(storage.table_name)
        columns = storage.column_names()
        batches = [
            columns[start : start + batch_size]
            for start in range(0, len(columns), batch_size)
        ]

        per_column: dict[str, dict] = {}
        batch_timings = []

        sampler = _DuckDBMemorySampler(storage.connection)
        with sampler:
            t0 = time.perf_counter()

            for batch in batches:
                batch_t0 = time.perf_counter()
                select_parts = []

                for index, column in enumerate(batch):
                    quoted = _quote_identifier(column)
                    select_parts.append(f"COUNT({quoted}) AS non_null_{index}")
                    select_parts.append(
                        f"COUNT(DISTINCT {quoted}) AS distinct_{index}"
                    )
                    select_parts.append(f"MIN({quoted}) AS min_{index}")
                    select_parts.append(f"MAX({quoted}) AS max_{index}")

                row = storage.execute_one(
                    f"SELECT {', '.join(select_parts)} FROM {table}"
                )
                batch_elapsed = time.perf_counter() - batch_t0
                batch_timings.append(
                    {"columns": list(batch), "elapsed_s": batch_elapsed}
                )

                for index, column in enumerate(batch):
                    non_null, distinct, min_value, max_value = row[
                        index * 4 : index * 4 + 4
                    ]
                    per_column[column] = {
                        "non_null_count": int(non_null or 0),
                        "distinct_count": int(distinct or 0),
                        "min_value": _json_safe_value(min_value),
                        "max_value": _json_safe_value(max_value),
                    }

            elapsed = time.perf_counter() - t0

        spill = _measure_spill(storage)
        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": len(per_column),
            "batch_size": batch_size,
            "batch_count": len(batches),
            "batch_timings": batch_timings,
            "per_column": per_column,
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
            "duckdb_memory_peak_by_tag": sampler.peak_by_tag(),
            **spill,
        }
    finally:
        storage.close()


def _op_pandas(args: dict) -> dict:
    # Legacy path deliberately, for the baseline comparison only - this
    # is the one place in the whole harness pd.read_csv is allowed,
    # because reproducing the *legacy* Pandas ingestion behavior is the
    # point of this measurement (the CSV -> Parquet benchmark above
    # never touches it).
    import pandas as pd

    from data_engine.dataset import Dataset
    from data_engine.plan_executor import execute_plan_for_dataset
    from data_engine.storage import PandasStorage

    t0 = time.perf_counter()
    try:
        df = pd.read_csv(args["csv_path"], engine="pyarrow")
    except Exception:
        df = pd.read_csv(args["csv_path"])
    storage = PandasStorage(df)
    dataset = Dataset(storage=storage)
    plan = _build_plan(args["kind"])
    result_df = execute_plan_for_dataset(dataset, plan)
    elapsed = time.perf_counter() - t0

    return {
        "elapsed_s": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "result_rows": int(result_df.row_count),
    }


def _op_pandas_profile(args: dict) -> dict:
    import pandas as pd

    from data_engine.dataset import Dataset
    from data_engine.profiling import basic_statistics_for_dataset
    from data_engine.storage import PandasStorage

    t0 = time.perf_counter()
    try:
        df = pd.read_csv(args["csv_path"], engine="pyarrow")
    except Exception:
        df = pd.read_csv(args["csv_path"])
    storage = PandasStorage(df)
    dataset = Dataset(storage=storage)
    stats = basic_statistics_for_dataset(dataset)
    elapsed = time.perf_counter() - t0

    return {
        "elapsed_s": elapsed,
        "peak_rss_bytes": peak_rss_bytes(),
        "result_rows": int(stats["row_count"]),
    }


_WORKER_OPS = {
    "gen_csv": _op_gen_csv,
    "ingest": _op_ingest,
    "duckdb": _op_duckdb,
    "duckdb_profile": _op_duckdb_profile,
    "duckdb_quality": _op_duckdb_quality,
    "duckdb_duplicates": _op_duckdb_duplicates,
    "duckdb_column_statistics": _op_duckdb_column_statistics,
    "duckdb_quality_iqr": _op_duckdb_quality_iqr,
    "duckdb_column_statistics_breakdown": _op_duckdb_column_statistics_breakdown,
    "duckdb_quality_iqr_breakdown": _op_duckdb_quality_iqr_breakdown,
    "duckdb_column_statistics_batched": _op_duckdb_column_statistics_batched,
    "pandas": _op_pandas,
    "pandas_profile": _op_pandas_profile,
}


def _run_worker(op: str, args: dict, result_path: str) -> None:
    try:
        payload = _WORKER_OPS[op](args)
        payload["ok"] = True
    except Exception as exc:  # noqa: BLE001 - report any failure to the parent
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


# =========================================================
# Orchestrator: spawns one subprocess per measured operation, tabulates
# results, cleans up artifacts, and applies the overall time budget.
# =========================================================


@dataclass
class OpResult:
    size: int
    operation: str
    engine: str
    ok: bool
    elapsed_s: Optional[float] = None
    peak_rss_bytes: Optional[int] = None
    result_rows: Optional[int] = None
    # Populated only for DuckDB-backed operations (see
    # _measure_spill/_apply_duckdb_governance); stays None for
    # generate_synthetic_csv/ingest_to_parquet/pandas rows, which is
    # backward compatible with any existing report consumer.
    spill_bytes: Optional[int] = None
    extra: dict = field(default_factory=dict)
    error: Optional[str] = None


def _run_subprocess_op(op: str, args: dict, workdir: str, timeout: float) -> dict:
    result_path = os.path.join(
        workdir, f"result_{op}_{args.get('kind', args.get('rows', 'x'))}_{time.time_ns()}.json"
    )
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--worker",
        "--op",
        op,
        "--args",
        json.dumps(args),
        "--result-file",
        result_path,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"worker timed out after {timeout:.0f}s"}

    if not os.path.exists(result_path):
        stderr_tail = (proc.stderr or "")[-2000:]
        return {"ok": False, "error": f"worker produced no result (stderr: {stderr_tail})"}

    with open(result_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    try:
        os.remove(result_path)
    except OSError:
        pass
    return payload


def _run_duckdb_op(
    op: str,
    base_args: dict,
    workdir: str,
    timeout: float,
    duckdb_memory_limit: str,
    duckdb_temp_root: str,
) -> dict:
    """
    Like ``_run_subprocess_op``, but for a DuckDB-backed op: gives it
    its own isolated spill directory under ``duckdb_temp_root`` (Step
    30 governance - see ``_apply_duckdb_governance``) and removes that
    directory here afterwards regardless of success, failure, or a
    subprocess timeout/kill.

    The worker's own ``storage.close()`` already removes it on the
    well-behaved path (a killed/timed-out subprocess never gets to run
    that ``finally`` block); this is the outer safety net for the
    paths where it doesn't, so no spill directory is ever left behind
    by this benchmark regardless of how the worker exits.
    """
    op_temp_root = os.path.join(workdir, f"duckdb_temp_{op}_{time.time_ns()}")
    os.makedirs(op_temp_root, exist_ok=True)
    full_args = dict(base_args)
    full_args["duckdb_memory_limit"] = duckdb_memory_limit
    full_args["duckdb_temp_root"] = op_temp_root
    try:
        return _run_subprocess_op(op, full_args, workdir, timeout)
    finally:
        shutil.rmtree(op_temp_root, ignore_errors=True)


def _disk_has_room(path: str, rows: int, wide: bool = False) -> bool:
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return True  # can't check - don't block the run over it
    bytes_per_row = WIDE_BYTES_PER_ROW_ESTIMATE if wide else BYTES_PER_ROW_ESTIMATE
    # CSV + Parquet coexist briefly; budget ~1.5x the CSV estimate for both.
    needed = int(rows * bytes_per_row * 1.5)
    return free > needed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--op", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--args", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--sizes",
        default=",".join(str(n) for n in DEFAULT_SIZES),
        help="Comma-separated row-count targets to benchmark.",
    )
    parser.add_argument(
        "--wide-schema",
        action="store_true",
        help="Generate the opt-in ~27-column stress schema (high-cardinality "
        "strings, extra numeric/categorical/date columns, nullable values, "
        "near-unique record_uuid) instead of the default narrow schema, to "
        "stress DuckDBStorage.column_statistics()/the quality_iqr op at "
        "scale. row_id, category, amount, is_active, and event_time are "
        "preserved so existing AnalysisPlan-based ops remain valid. Default "
        "generation is unaffected when this flag is omitted.",
    )
    parser.add_argument(
        "--column-breakdown",
        action="store_true",
        help="STEP 41B diagnostic: after column_statistics/quality_iqr run "
        "normally, also run each op's aggregate one column at a time (see "
        "_op_duckdb_column_statistics_breakdown/_op_duckdb_quality_iqr_breakdown) "
        "to attribute cost per column instead of one fused multi-column query. "
        "Re-scans the table once per column, so it is opt-in and excluded from "
        "the default run.",
    )
    parser.add_argument(
        "--column-stat-batch-size",
        type=int,
        nargs="?",
        const=DEFAULT_COLUMN_STAT_BATCH_SIZE,
        default=None,
        help="STEP 43 opt-in diagnostic: also run DuckDBStorage."
        "column_statistics()'s exact non-null-count/COUNT(DISTINCT)/MIN/MAX "
        "aggregate as fixed-size batches of N columns (one fused query per "
        "batch, via _op_duckdb_column_statistics_batched) instead of the "
        "single query fusing every column, to compare wall-clock time and "
        "per-tag DuckDB memory peaks against the unbatched "
        "duckdb_column_statistics op. Pass with no value to use the default "
        f"batch size ({DEFAULT_COLUMN_STAT_BATCH_SIZE}); omitting this flag "
        "entirely skips the batched op and leaves every other op's behavior "
        "unchanged.",
    )
    parser.add_argument(
        "--pandas-max-rows",
        type=int,
        default=DEFAULT_PANDAS_MAX_ROWS,
        help="Largest size to also run through the legacy Pandas baseline.",
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=DEFAULT_TIME_BUDGET_SECONDS,
        help="Overall wall-clock budget (seconds) before the run stops early and "
        "records a cap.",
    )
    parser.add_argument(
        "--op-timeout",
        type=float,
        default=DEFAULT_OP_TIMEOUT_SECONDS,
        help="Per-operation subprocess timeout ceiling (seconds), still bounded by "
        "the remaining --time-budget. Replaces the previous hardcoded 600s "
        "(gen/ingest) and 300s (duckdb/profiling/pandas) ceilings with one "
        "configurable value, defaulted to the larger of the two so existing "
        "behavior is preserved.",
    )
    parser.add_argument(
        "--duckdb-memory-limit",
        default=DEFAULT_DUCKDB_MEMORY_LIMIT,
        help="DuckDB memory_limit applied to every DuckDB-backed worker via the "
        "DUCKDB_MEMORY_LIMIT env var (matches production's own default).",
    )
    parser.add_argument(
        "--duckdb-temp-root",
        default=DEFAULT_DUCKDB_TEMP_ROOT,
        help="Parent directory for each DuckDB-backed worker's isolated spill "
        "directory, via the DUCKDB_TEMP_ROOT env var (matches production's own "
        "default: the system temp directory).",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "scripts", "benchmark_report.json"),
        help="Where to write the JSON report.",
    )
    args = parser.parse_args()

    if args.worker:
        _run_worker(args.op, json.loads(args.args), args.result_file)
        return 0

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    workdir = tempfile.mkdtemp(prefix="scale_bench_")
    start = time.time()
    deadline = start + args.time_budget

    report: dict[str, Any] = {
        "sizes_requested": sizes,
        "wide_schema": args.wide_schema,
        "column_stat_batch_size": args.column_stat_batch_size,
        "pandas_max_rows": args.pandas_max_rows,
        "time_budget_s": args.time_budget,
        "results": [],
        "cap_reached": None,
    }

    try:
        for size in sizes:
            if time.time() > deadline:
                report["cap_reached"] = f"time budget exhausted before size={size}"
                break

            if not _disk_has_room(workdir, size, wide=args.wide_schema):
                report["cap_reached"] = f"insufficient free disk before size={size}"
                break

            size_dir = os.path.join(workdir, f"size_{size}")
            os.makedirs(size_dir, exist_ok=True)
            csv_path = os.path.join(size_dir, "data.csv")
            storage_root = os.path.join(size_dir, "storage")

            remaining = max(60.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)

            gen = _run_subprocess_op(
                "gen_csv",
                {
                    "csv_path": csv_path,
                    "rows": size,
                    "seed": 42,
                    "wide": args.wide_schema,
                },
                workdir,
                op_timeout,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="generate_synthetic_csv",
                        engine="pyarrow",
                        ok=gen.get("ok", False),
                        elapsed_s=gen.get("elapsed_s"),
                        peak_rss_bytes=gen.get("peak_rss_bytes"),
                        result_rows=gen.get("rows"),
                        extra={"output_bytes": gen.get("output_bytes")},
                        error=gen.get("error"),
                    )
                )
            )
            if not gen.get("ok"):
                report["cap_reached"] = f"CSV generation failed/timed out at size={size}"
                break

            remaining = max(60.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            ing = _run_subprocess_op(
                "ingest",
                {
                    "csv_path": csv_path,
                    "dataset_id": f"bench_{size}",
                    "storage_root": storage_root,
                },
                workdir,
                op_timeout,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="ingest_to_parquet",
                        engine="pyarrow",
                        ok=ing.get("ok", False),
                        elapsed_s=ing.get("elapsed_s"),
                        peak_rss_bytes=ing.get("peak_rss_bytes"),
                        result_rows=ing.get("rows"),
                        extra={
                            "input_bytes": ing.get("input_bytes"),
                            "output_bytes": ing.get("output_bytes"),
                        },
                        error=ing.get("error"),
                    )
                )
            )
            if not ing.get("ok"):
                report["cap_reached"] = f"ingestion failed/timed out at size={size}"
                break

            parquet_path = ing["parquet_path"]

            for kind in ("global_agg", "grouped_agg", "filter", "sort_limit"):
                remaining = max(30.0, deadline - time.time())
                op_timeout = min(args.op_timeout, remaining)
                res = _run_duckdb_op(
                    "duckdb",
                    {"parquet_path": parquet_path, "kind": kind},
                    workdir,
                    op_timeout,
                    args.duckdb_memory_limit,
                    args.duckdb_temp_root,
                )
                report["results"].append(
                    asdict(
                        OpResult(
                            size=size,
                            operation=f"duckdb_{kind}",
                            engine="duckdb",
                            ok=res.get("ok", False),
                            elapsed_s=res.get("elapsed_s"),
                            peak_rss_bytes=res.get("peak_rss_bytes"),
                            result_rows=res.get("result_rows"),
                            spill_bytes=res.get("spill_bytes"),
                            extra={
                                "to_dataframe_calls": res.get("to_dataframe_calls"),
                                "spill_file_count": res.get("spill_file_count"),
                            },
                            error=res.get("error"),
                        )
                    )
                )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            prof = _run_duckdb_op(
                "duckdb_profile",
                {"parquet_path": parquet_path},
                workdir,
                op_timeout,
                args.duckdb_memory_limit,
                args.duckdb_temp_root,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="basic_statistics",
                        engine="duckdb",
                        ok=prof.get("ok", False),
                        elapsed_s=prof.get("elapsed_s"),
                        peak_rss_bytes=prof.get("peak_rss_bytes"),
                        result_rows=prof.get("result_rows"),
                        spill_bytes=prof.get("spill_bytes"),
                        extra={
                            "to_dataframe_calls": prof.get("to_dataframe_calls"),
                            "duplicate_rows": prof.get("duplicate_rows"),
                            "spill_file_count": prof.get("spill_file_count"),
                        },
                        error=prof.get("error"),
                    )
                )
            )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            qual = _run_duckdb_op(
                "duckdb_quality",
                {"parquet_path": parquet_path},
                workdir,
                op_timeout,
                args.duckdb_memory_limit,
                args.duckdb_temp_root,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="quality",
                        engine="duckdb",
                        ok=qual.get("ok", False),
                        elapsed_s=qual.get("elapsed_s"),
                        peak_rss_bytes=qual.get("peak_rss_bytes"),
                        result_rows=qual.get("result_rows"),
                        spill_bytes=qual.get("spill_bytes"),
                        extra={
                            "status": qual.get("status"),
                            "duplicate_rows": qual.get("duplicate_rows"),
                            "to_dataframe_calls": qual.get("to_dataframe_calls"),
                            "spill_file_count": qual.get("spill_file_count"),
                            "duckdb_memory_peak_by_tag": qual.get(
                                "duckdb_memory_peak_by_tag"
                            ),
                        },
                        error=qual.get("error"),
                    )
                )
            )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            dupes = _run_duckdb_op(
                "duckdb_duplicates",
                {"parquet_path": parquet_path},
                workdir,
                op_timeout,
                args.duckdb_memory_limit,
                args.duckdb_temp_root,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="duplicate_detection",
                        engine="duckdb",
                        ok=dupes.get("ok", False),
                        elapsed_s=dupes.get("elapsed_s"),
                        peak_rss_bytes=dupes.get("peak_rss_bytes"),
                        result_rows=dupes.get("result_rows"),
                        spill_bytes=dupes.get("spill_bytes"),
                        extra={
                            "duplicate_rows": dupes.get("duplicate_rows"),
                            "to_dataframe_calls": dupes.get("to_dataframe_calls"),
                            "spill_file_count": dupes.get("spill_file_count"),
                        },
                        error=dupes.get("error"),
                    )
                )
            )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            colstats = _run_duckdb_op(
                "duckdb_column_statistics",
                {"parquet_path": parquet_path},
                workdir,
                op_timeout,
                args.duckdb_memory_limit,
                args.duckdb_temp_root,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="column_statistics",
                        engine="duckdb",
                        ok=colstats.get("ok", False),
                        elapsed_s=colstats.get("elapsed_s"),
                        peak_rss_bytes=colstats.get("peak_rss_bytes"),
                        result_rows=colstats.get("result_rows"),
                        spill_bytes=colstats.get("spill_bytes"),
                        extra={
                            "to_dataframe_calls": colstats.get("to_dataframe_calls"),
                            "spill_file_count": colstats.get("spill_file_count"),
                            "duckdb_memory_peak_by_tag": colstats.get(
                                "duckdb_memory_peak_by_tag"
                            ),
                        },
                        error=colstats.get("error"),
                    )
                )
            )

            if args.column_stat_batch_size is not None:
                remaining = max(30.0, deadline - time.time())
                op_timeout = min(args.op_timeout, remaining)
                colbatch = _run_duckdb_op(
                    "duckdb_column_statistics_batched",
                    {
                        "parquet_path": parquet_path,
                        "batch_size": args.column_stat_batch_size,
                    },
                    workdir,
                    op_timeout,
                    args.duckdb_memory_limit,
                    args.duckdb_temp_root,
                )
                report["results"].append(
                    asdict(
                        OpResult(
                            size=size,
                            operation="column_statistics_batched",
                            engine="duckdb",
                            ok=colbatch.get("ok", False),
                            elapsed_s=colbatch.get("elapsed_s"),
                            peak_rss_bytes=colbatch.get("peak_rss_bytes"),
                            result_rows=colbatch.get("result_rows"),
                            spill_bytes=colbatch.get("spill_bytes"),
                            extra={
                                "batch_size": colbatch.get("batch_size"),
                                "batch_count": colbatch.get("batch_count"),
                                "batch_timings": colbatch.get("batch_timings"),
                                "per_column": colbatch.get("per_column"),
                                "to_dataframe_calls": colbatch.get(
                                    "to_dataframe_calls"
                                ),
                                "spill_file_count": colbatch.get("spill_file_count"),
                                "duckdb_memory_peak_by_tag": colbatch.get(
                                    "duckdb_memory_peak_by_tag"
                                ),
                            },
                            error=colbatch.get("error"),
                        )
                    )
                )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(args.op_timeout, remaining)
            iqr = _run_duckdb_op(
                "duckdb_quality_iqr",
                {"parquet_path": parquet_path},
                workdir,
                op_timeout,
                args.duckdb_memory_limit,
                args.duckdb_temp_root,
            )
            report["results"].append(
                asdict(
                    OpResult(
                        size=size,
                        operation="quality_iqr",
                        engine="duckdb",
                        ok=iqr.get("ok", False),
                        elapsed_s=iqr.get("elapsed_s"),
                        peak_rss_bytes=iqr.get("peak_rss_bytes"),
                        result_rows=iqr.get("result_rows"),
                        spill_bytes=iqr.get("spill_bytes"),
                        extra={
                            "status": iqr.get("status"),
                            "to_dataframe_calls": iqr.get("to_dataframe_calls"),
                            "spill_file_count": iqr.get("spill_file_count"),
                            "duckdb_memory_peak_by_tag": iqr.get(
                                "duckdb_memory_peak_by_tag"
                            ),
                        },
                        error=iqr.get("error"),
                    )
                )
            )

            if args.column_breakdown:
                remaining = max(30.0, deadline - time.time())
                op_timeout = min(args.op_timeout, remaining)
                colbreak = _run_duckdb_op(
                    "duckdb_column_statistics_breakdown",
                    {"parquet_path": parquet_path},
                    workdir,
                    op_timeout,
                    args.duckdb_memory_limit,
                    args.duckdb_temp_root,
                )
                report["results"].append(
                    asdict(
                        OpResult(
                            size=size,
                            operation="column_statistics_breakdown",
                            engine="duckdb",
                            ok=colbreak.get("ok", False),
                            peak_rss_bytes=colbreak.get("peak_rss_bytes"),
                            extra={"per_column": colbreak.get("per_column")},
                            error=colbreak.get("error"),
                        )
                    )
                )

                remaining = max(30.0, deadline - time.time())
                op_timeout = min(args.op_timeout, remaining)
                iqrbreak = _run_duckdb_op(
                    "duckdb_quality_iqr_breakdown",
                    {"parquet_path": parquet_path},
                    workdir,
                    op_timeout,
                    args.duckdb_memory_limit,
                    args.duckdb_temp_root,
                )
                report["results"].append(
                    asdict(
                        OpResult(
                            size=size,
                            operation="quality_iqr_breakdown",
                            engine="duckdb",
                            ok=iqrbreak.get("ok", False),
                            peak_rss_bytes=iqrbreak.get("peak_rss_bytes"),
                            extra={"per_column": iqrbreak.get("per_column")},
                            error=iqrbreak.get("error"),
                        )
                    )
                )

            if size <= args.pandas_max_rows:
                for kind in ("global_agg", "grouped_agg", "filter", "sort_limit"):
                    remaining = max(30.0, deadline - time.time())
                    op_timeout = min(args.op_timeout, remaining)
                    res = _run_subprocess_op(
                        "pandas", {"csv_path": csv_path, "kind": kind}, workdir, op_timeout
                    )
                    report["results"].append(
                        asdict(
                            OpResult(
                                size=size,
                                operation=f"pandas_{kind}",
                                engine="pandas",
                                ok=res.get("ok", False),
                                elapsed_s=res.get("elapsed_s"),
                                peak_rss_bytes=res.get("peak_rss_bytes"),
                                result_rows=res.get("result_rows"),
                                error=res.get("error"),
                            )
                        )
                    )

                remaining = max(30.0, deadline - time.time())
                op_timeout = min(args.op_timeout, remaining)
                pprof = _run_subprocess_op(
                    "pandas_profile", {"csv_path": csv_path}, workdir, op_timeout
                )
                report["results"].append(
                    asdict(
                        OpResult(
                            size=size,
                            operation="pandas_basic_statistics",
                            engine="pandas",
                            ok=pprof.get("ok", False),
                            elapsed_s=pprof.get("elapsed_s"),
                            peak_rss_bytes=pprof.get("peak_rss_bytes"),
                            result_rows=pprof.get("result_rows"),
                            error=pprof.get("error"),
                        )
                    )
                )

            # Multi-gigabyte artifact cleanup - immediate, not deferred
            # to end-of-run.
            shutil.rmtree(size_dir, ignore_errors=True)

        report["total_elapsed_s"] = time.time() - start

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
