"""
R6: storage lifecycle - shutdown closes every storage and the analysis
pool cleanly, abandoned spill directories are removed at startup while
live ones (in this or another process) and unrelated files never are,
and a failed storage initialisation leaves nothing behind.

All data is tiny; spill directories are created under per-test temp
roots (DUCKDB_TEMP_ROOT), never the real system temp directory.
"""

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.jobs as jobs
import backend.main as main
import data_engine.storage.duckdb_storage as duckdb_storage_module
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetRegistry
from data_engine.storage import DuckDBStorage, StorageClosedError
from data_engine.storage.duckdb_storage import cleanup_abandoned_spill_directories

REPO_ROOT = Path(__file__).resolve().parent.parent
SLOW_QUERY = "SELECT count(*) FROM range(100000000000) t(i) WHERE i % 7 = 3"
OLD = time.time() - 3 * 24 * 60 * 60  # three days ago


def _df() -> pd.DataFrame:
    return pd.DataFrame({"region": ["north", "south"], "quantity": [1, 2]})


@pytest.fixture
def spill_root(tmp_path, monkeypatch):
    root = tmp_path / "spill_root"
    root.mkdir()
    monkeypatch.setenv("DUCKDB_TEMP_ROOT", str(root))
    return root


def _spill_dir(root: Path, *, lock_file: bool, files=(), mtime=OLD) -> Path:
    path = root / f"duckdb_spill_dataset_{uuid.uuid4().hex}"
    path.mkdir()
    names = list(files) + ([".owner.lock"] if lock_file else [])
    for name in names:
        (path / name).write_bytes(b"x")
        os.utime(path / name, (mtime, mtime))
    os.utime(path, (mtime, mtime))
    return path


def _parquet(tmp_path: Path, name: str = "data.parquet") -> Path:
    path = tmp_path / name
    _df().to_parquet(path)
    return path


# =========================================================
# Startup spill cleanup
# =========================================================


def test_abandoned_locked_format_directory_is_removed(spill_root):
    abandoned = _spill_dir(spill_root, lock_file=True, files=["duckdb_temp_block-1.block"])

    counts = cleanup_abandoned_spill_directories(str(spill_root))

    assert not abandoned.exists()
    assert counts["removed"] == 1


def test_active_storage_spill_directory_is_never_removed(spill_root):
    storage = DuckDBStorage(_df())
    try:
        live = Path(storage._temp_dir)
        os.utime(live, (OLD, OLD))  # old enough to be a candidate

        counts = cleanup_abandoned_spill_directories(
            str(spill_root), min_age_seconds=0, legacy_min_age_seconds=0
        )

        assert live.is_dir()
        assert counts["skipped_active"] == 1
        assert counts["removed"] == 0
        # And the storage still works, including spilling into it.
        assert storage.execute_one("SELECT count(*) FROM range(10)")[0] == 10
    finally:
        storage.close()

    assert not live.exists()


def test_spill_directory_live_in_another_process_is_never_removed(spill_root):
    # The child "crashes" with os._exit(): no close(), no finally/atexit
    # cleanup. (Killing it from here is not equivalent on Windows: a
    # venv's python.exe is a launcher, and kill() would only stop the
    # launcher, leaving the real interpreter - and its lock - alive.)
    code = (
        "import os, sys, pandas as pd\n"
        "from data_engine.storage import DuckDBStorage\n"
        "s = DuckDBStorage(pd.DataFrame({'a': [1]}))\n"
        "print(s._temp_dir, flush=True)\n"
        "sys.stdin.readline()\n"
        "os._exit(1)\n"
    )
    env = {**os.environ, "DUCKDB_TEMP_ROOT": str(spill_root), "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        other = Path(proc.stdout.readline().strip())
        assert other.is_dir() and other.parent == spill_root
        os.utime(other, (OLD, OLD))

        counts = cleanup_abandoned_spill_directories(str(spill_root), min_age_seconds=0)
        assert other.is_dir()
        assert counts["skipped_active"] == 1

        # The other process dies without closing anything (crash).
        proc.stdin.write("\n")
        proc.stdin.flush()
        assert proc.wait(timeout=30) == 1

        counts = cleanup_abandoned_spill_directories(str(spill_root), min_age_seconds=0)
        assert counts["removed"] == 1, counts
        assert not other.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)


def test_recently_modified_directories_are_skipped(spill_root):
    recent_locked = _spill_dir(spill_root, lock_file=True, mtime=time.time())
    recent_legacy = _spill_dir(spill_root, lock_file=False, mtime=time.time())

    counts = cleanup_abandoned_spill_directories(str(spill_root))

    assert recent_locked.is_dir() and recent_legacy.is_dir()
    assert counts["skipped_recent"] == 2


def test_legacy_directory_without_lock_needs_a_day_of_inactivity(spill_root):
    old_empty = _spill_dir(spill_root, lock_file=False)
    old_with_files = _spill_dir(spill_root, lock_file=False, files=["duckdb_temp_storage-0.tmp"])
    # Directory itself is old, but a file inside changed an hour ago.
    busy = _spill_dir(spill_root, lock_file=False, files=["duckdb_temp_storage-0.tmp"])
    hour_ago = time.time() - 3600
    os.utime(busy / "duckdb_temp_storage-0.tmp", (hour_ago, hour_ago))
    os.utime(busy, (OLD, OLD))

    counts = cleanup_abandoned_spill_directories(str(spill_root))

    assert not old_empty.exists()
    assert not old_with_files.exists()
    assert busy.is_dir()
    assert counts["removed"] == 2


def test_unrelated_files_and_directories_are_never_touched(spill_root):
    keep = [
        spill_root / "duckdb_spill_deqzrhk_",  # real-world near miss
        spill_root / "duckdb_spill_dataset_NOTHEX",
        spill_root / f"duckdb_spill_dataset_{uuid.uuid4().hex}_suffix",
        spill_root / f"duckdb_spill_dataset_{uuid.uuid4().hex[:31]}",
        spill_root / "uploads",
        spill_root / "data",
    ]
    for path in keep:
        path.mkdir()
        (path / "precious.txt").write_text("keep")
        os.utime(path, (OLD, OLD))

    dataset_file = spill_root / "dataset.parquet"
    dataset_file.write_bytes(b"PAR1")
    manifest = spill_root / "dataset.manifest.json"
    manifest.write_text("{}")
    # A *file* with an exactly matching name is not a spill directory.
    matching_file = spill_root / f"duckdb_spill_dataset_{uuid.uuid4().hex}"
    matching_file.write_text("not a directory")
    for path in (dataset_file, manifest, matching_file):
        os.utime(path, (OLD, OLD))

    counts = cleanup_abandoned_spill_directories(
        str(spill_root), min_age_seconds=0, legacy_min_age_seconds=0
    )

    for path in keep:
        assert (path / "precious.txt").read_text() == "keep"
    assert dataset_file.exists() and manifest.exists() and matching_file.exists()
    assert counts["removed"] == 0


def _make_link(target: Path, link: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_directories_containing_links_or_junctions_are_never_followed(spill_root, tmp_path):
    precious = tmp_path / "precious_target"
    precious.mkdir()
    (precious / "important.txt").write_text("keep")

    # A spill-named candidate containing a junction/symlink...
    holder = _spill_dir(spill_root, lock_file=True)
    _make_link(precious, holder / "escape")
    os.utime(holder, (OLD, OLD))
    # ...and a spill-named junction/symlink pointing at real data.
    link_candidate = spill_root / f"duckdb_spill_dataset_{uuid.uuid4().hex}"
    _make_link(precious, link_candidate)

    counts = cleanup_abandoned_spill_directories(
        str(spill_root), min_age_seconds=0, legacy_min_age_seconds=0
    )

    assert (precious / "important.txt").read_text() == "keep"
    assert holder.exists() and link_candidate.exists()
    assert counts["skipped_unsafe"] == 2
    assert counts["removed"] == 0


def test_cleanup_never_raises_for_a_missing_root(tmp_path):
    counts = cleanup_abandoned_spill_directories(str(tmp_path / "does-not-exist"))
    assert counts["removed"] == 0


def test_startup_cleanup_can_be_disabled(spill_root, monkeypatch):
    abandoned = _spill_dir(spill_root, lock_file=True)
    monkeypatch.setenv("DUCKDB_SPILL_CLEANUP", "0")

    main._cleanup_spill_directories()

    assert abandoned.is_dir()


# =========================================================
# Failed initialisation cleans up after itself
# =========================================================


class _FailingCreateConnection:
    """Real DuckDB connection whose CREATE TABLE/VIEW fails."""

    created: list = []

    def __init__(self, *args, **kwargs):
        self._real = _real_connect(*args, **kwargs)
        _FailingCreateConnection.created.append(self)

    def execute(self, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith(("CREATE TABLE", "CREATE VIEW")):
            raise duckdb.Error("simulated failure after spill directory creation")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


_real_connect = duckdb.connect


@pytest.mark.parametrize("constructor", ["dataframe", "parquet"])
def test_failed_initialisation_removes_spill_dir_and_closes_connection(
    spill_root, tmp_path, monkeypatch, constructor
):
    _FailingCreateConnection.created = []
    monkeypatch.setattr(duckdb_storage_module.duckdb, "connect", _FailingCreateConnection)

    with pytest.raises(duckdb.Error):
        if constructor == "dataframe":
            DuckDBStorage(_df())
        else:
            DuckDBStorage.from_parquet(str(_parquet(tmp_path)))

    assert os.listdir(spill_root) == []  # directory and lock file gone
    [connection] = _FailingCreateConnection.created
    with pytest.raises(duckdb.ConnectionException):
        connection._real.execute("SELECT 1")


def test_unreadable_parquet_leaves_nothing_behind(spill_root, tmp_path):
    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_bytes(b"this is not parquet")

    with pytest.raises(Exception):
        DuckDBStorage.from_parquet(str(corrupt))

    assert os.listdir(spill_root) == []
    assert corrupt.exists()  # the source file itself is never deleted


# =========================================================
# Shutdown: registry.close_all() and the lifespan sequence
# =========================================================


def test_close_all_closes_storages_but_keeps_files_on_disk(spill_root, tmp_path, caplog):
    parquet_path = _parquet(tmp_path)
    manifest = tmp_path / "data.manifest.json"
    manifest.write_text("{}")
    registry = DatasetRegistry()
    storage = DuckDBStorage.from_parquet(str(parquet_path))
    temp_dir = storage._temp_dir
    registry.register(Dataset(storage=storage, owner_id="u"))

    class _BrokenStorage:
        artifact_path = None

        def close(self):
            raise RuntimeError("close failed")

    registry.register(Dataset(storage=_BrokenStorage(), owner_id="u"))
    other = DuckDBStorage(_df())
    registry.register(Dataset(storage=other, owner_id="u"))

    assert registry.close_all() == 3

    assert len(registry) == 0
    assert storage._closed and other._closed  # the failure didn't stop the rest
    assert not os.path.exists(temp_dir)
    assert parquet_path.exists() and manifest.exists()
    assert "during shutdown" in caplog.text


def _wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_shutdown_interrupts_running_query_and_cancels_queued_jobs(spill_root, tmp_path):
    parquet_path = _parquet(tmp_path)
    registry = DatasetRegistry()
    storage = DuckDBStorage.from_parquet(str(parquet_path))
    registry.register(Dataset(storage=storage, owner_id="u"))
    # A short task deadline bounds how long the slow query can survive
    # even if close()-interruption regresses (the test still fails then:
    # the query would end with QueryTimeoutError, not StorageClosedError).
    manager = jobs.JobManager(max_workers=1, task_timeout_seconds=20)

    running = manager.run(lambda: storage.execute_one(SLOW_QUERY))
    assert _wait_until(lambda: storage._active_query_token is not None)
    queued_job = manager.submit("u", "d", lambda: "never runs")

    # Run shutdown in a thread with a bounded join: if interruption
    # regresses, close() would keep waiting on the storage lock - fail
    # within seconds instead of hanging.
    shutdown = threading.Thread(
        target=main._shutdown_analysis_and_storage,
        kwargs={"manager": manager, "registry": registry, "wait_seconds": 10},
        daemon=True,
    )
    started = time.monotonic()
    shutdown.start()
    shutdown.join(timeout=15)
    elapsed = time.monotonic() - started

    assert not shutdown.is_alive(), "shutdown blocked: running query was not interrupted"
    assert isinstance(running.exception(timeout=1), StorageClosedError)
    assert elapsed < 10
    job = manager.get(queued_job["job_id"], "u")
    assert job["status"] == "failed"
    assert job["error"] == jobs.SHUTDOWN_JOB_ERROR
    assert storage._closed and len(registry) == 0
    assert parquet_path.exists()
    assert manager.pending_count() == 0

    with pytest.raises(jobs.QueueFullError):
        manager.run(lambda: None)

    # The process-wide manager can be restarted (next lifespan).
    manager.start()
    try:
        assert manager.run(lambda: "again").result(timeout=5) == "again"
    finally:
        manager.shutdown(wait=True)


def test_shutdown_wait_is_bounded_for_uninterruptible_work(caplog):
    manager = jobs.JobManager(max_workers=1)
    gate = threading.Event()
    manager.run(lambda: gate.wait(timeout=15))

    started = time.monotonic()
    main._shutdown_analysis_and_storage(
        manager=manager, registry=DatasetRegistry(), wait_seconds=0.3
    )

    assert time.monotonic() - started < 5
    assert "still running" in caplog.text
    gate.set()
    manager.shutdown(wait=True)


def test_app_lifespan_cleans_spill_on_startup_and_closes_on_shutdown(
    spill_root, tmp_path, monkeypatch
):
    abandoned = _spill_dir(spill_root, lock_file=True)
    registry = DatasetRegistry()
    manager = jobs.JobManager(max_workers=1)
    monkeypatch.setattr(jobs, "job_manager", manager)
    monkeypatch.setattr(main, "dataset_registry", registry)
    monkeypatch.setattr(main, "_cleanup_expired_sessions", lambda: None)

    recovered = []

    def _recover():
        # Recovery runs after cleanup, so a live storage opened here
        # must survive the cleanup that already happened.
        storage = DuckDBStorage.from_parquet(str(_parquet(tmp_path)))
        registry.register(Dataset(storage=storage, owner_id="dev-user"))
        recovered.append(storage)

    monkeypatch.setattr(main, "_recover_datasets", _recover)
    manager.shutdown(wait=True)  # simulate a previous lifespan's shutdown

    with TestClient(main.app) as http:
        assert not abandoned.exists()
        [storage] = recovered
        assert os.path.isdir(storage._temp_dir)
        assert http.get("/").status_code == 200
        # start() re-opened the manager for this lifespan.
        assert manager.run(lambda: "ok").result(timeout=5) == "ok"

    assert storage._closed
    assert not os.path.exists(storage._temp_dir)
    assert len(registry) == 0
    with pytest.raises(jobs.QueueFullError):
        manager.run(lambda: None)

    manager.start()
    manager.shutdown(wait=True)
