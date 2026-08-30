"""STEP 13 - Scale benchmarking harness (empirical verification only).

Isolated, explicitly-executable benchmarking script. It lives outside
``tests/`` on purpose: pytest's default collection (``test_*.py`` /
``*_test.py``) never picks this file up, and it is never imported by
production code, so it cannot affect the regression suite.

Usage:
    python scripts/run_scale_benchmark.py
    python scripts/run_scale_benchmark.py --sizes 10000,100000,1000000
    python scripts/run_scale_benchmark.py --out my_report.json

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
) -> int:
    """Stream ``num_rows`` of deterministic, typed synthetic data to a
    CSV file at ``path``, ``chunk_size`` rows at a time.

    Never holds more than one chunk's worth of columns in memory -
    each chunk is built as numpy arrays, handed to pyarrow as a
    RecordBatch, and serialized straight to the open file handle via
    ``pyarrow.csv.write_csv`` (only the first chunk writes a header).
    Deterministic: the same (num_rows, seed) always produces
    byte-identical output, via ``numpy.random.default_rng(seed)``.

    Columns: row_id (int64), category (string), amount (float64),
    is_active (bool), event_time (datetime/timestamp[s]).
    """

    rng = np.random.default_rng(seed)
    base_ts = np.datetime64("2020-01-01T00:00:00", "s")
    five_years_seconds = 60 * 60 * 24 * 365 * 5

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
        args["csv_path"], args["rows"], seed=args.get("seed", 42)
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

        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(len(result_df)),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
        }
    finally:
        storage.close()


def _op_duckdb_profile(args: dict) -> dict:
    from data_engine.dataset import Dataset
    from data_engine.profiling import basic_statistics_for_dataset

    spy_cls = _make_spy_duckdb_storage()
    storage = spy_cls.from_parquet(args["parquet_path"])
    try:
        dataset = Dataset(storage=storage)

        t0 = time.perf_counter()
        stats = basic_statistics_for_dataset(dataset)
        elapsed = time.perf_counter() - t0

        return {
            "elapsed_s": elapsed,
            "peak_rss_bytes": peak_rss_bytes(),
            "result_rows": int(stats["row_count"]),
            "to_dataframe_calls": int(getattr(storage, "to_dataframe_calls", 0)),
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
        "result_rows": int(len(result_df)),
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


def _disk_has_room(path: str, rows: int) -> bool:
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return True  # can't check - don't block the run over it
    # CSV + Parquet coexist briefly; budget ~1.5x the CSV estimate for both.
    needed = int(rows * BYTES_PER_ROW_ESTIMATE * 1.5)
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

            if not _disk_has_room(workdir, size):
                report["cap_reached"] = f"insufficient free disk before size={size}"
                break

            size_dir = os.path.join(workdir, f"size_{size}")
            os.makedirs(size_dir, exist_ok=True)
            csv_path = os.path.join(size_dir, "data.csv")
            storage_root = os.path.join(size_dir, "storage")

            remaining = max(60.0, deadline - time.time())
            op_timeout = min(600.0, remaining)

            gen = _run_subprocess_op(
                "gen_csv", {"csv_path": csv_path, "rows": size, "seed": 42}, workdir, op_timeout
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
            op_timeout = min(600.0, remaining)
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
                op_timeout = min(300.0, remaining)
                res = _run_subprocess_op(
                    "duckdb", {"parquet_path": parquet_path, "kind": kind}, workdir, op_timeout
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
                            extra={"to_dataframe_calls": res.get("to_dataframe_calls")},
                            error=res.get("error"),
                        )
                    )
                )

            remaining = max(30.0, deadline - time.time())
            op_timeout = min(300.0, remaining)
            prof = _run_subprocess_op(
                "duckdb_profile", {"parquet_path": parquet_path}, workdir, op_timeout
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
                        extra={"to_dataframe_calls": prof.get("to_dataframe_calls")},
                        error=prof.get("error"),
                    )
                )
            )

            if size <= args.pandas_max_rows:
                for kind in ("global_agg", "grouped_agg", "filter", "sort_limit"):
                    remaining = max(30.0, deadline - time.time())
                    op_timeout = min(300.0, remaining)
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
                op_timeout = min(300.0, remaining)
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
