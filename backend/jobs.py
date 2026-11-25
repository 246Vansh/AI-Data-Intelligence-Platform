"""
Step 56: minimal in-process asynchronous job manager.

Runs expensive work on a bounded thread pool inside the API process so
an HTTP request can return immediately with a job_id and the caller can
poll for the result. Deliberately in-memory only - no broker, no
external queue, no cross-process state - so jobs do not survive a
restart and are only visible to the process that created them.

The manager is storage/analysis agnostic: it runs whatever callable it
is handed and records the outcome. Translating that outcome into a
client-safe error is the caller's job (see backend/routes/jobs.py).
"""

import logging
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_for_futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from data_engine.storage import QueryTimeoutError, query_deadline


logger = logging.getLogger(__name__)


JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"

_TERMINAL_STATUSES = (JOB_COMPLETED, JOB_FAILED)


def _read_positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default

    return value if value > 0 else default


# Overridable via plain env vars, matching MAX_UPLOAD_BYTES in
# backend/routes/dataset.py (the project has no config system yet).
DEFAULT_MAX_WORKERS = _read_positive_int_env("ANALYSIS_JOB_WORKERS", 2)
DEFAULT_MAX_RETAINED_JOBS = _read_positive_int_env("ANALYSIS_JOB_RETENTION", 1000)

# R4: queue protection. Tasks admitted but not yet finished (running +
# waiting) are capped at max_workers + ANALYSIS_JOB_MAX_QUEUE; past
# that, submit()/run() raise QueueFullError (the routes answer 503)
# instead of growing ThreadPoolExecutor's unbounded queue forever.
DEFAULT_MAX_QUEUE = _read_positive_int_env("ANALYSIS_JOB_MAX_QUEUE", 32)

# R4: every task on the pool runs under this query deadline (seconds
# from when it starts running, not from when it was queued). DuckDB
# queries still running at the deadline are interrupted, so a slow
# analysis can't hold a worker indefinitely. Sized well above the
# slowest measured single operations (~15s per quality/statistics op at
# 10M rows) and above the AI planner's own worst case (60s x 3
# attempts).
DEFAULT_TASK_TIMEOUT_SECONDS = _read_positive_int_env("ANALYSIS_JOB_TIMEOUT_SECONDS", 300)

# Retry-After hint (seconds) for a rejected submission.
QUEUE_FULL_RETRY_AFTER_SECONDS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobError(Exception):
    """
    A job failure whose status_code/detail are already safe to return
    to the client. Any other exception raised by a job's work is
    treated as internal and never surfaced.
    """

    def __init__(self, status_code: int, detail: Any):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Job:
    job_id: str
    owner_id: str
    dataset_id: str
    status: str = JOB_QUEUED
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = ""
    result: Any = None
    error: dict | None = None

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "owner_id": self.owner_id,
            "dataset_id": self.dataset_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


GENERIC_JOB_ERROR = {
    "status_code": 500,
    "detail": "The analysis job failed due to an internal error.",
}

TIMEOUT_JOB_ERROR = {
    "status_code": 504,
    "detail": "The analysis exceeded the server's time limit and was stopped.",
}

SHUTDOWN_JOB_ERROR = {
    "status_code": 503,
    "detail": "The server shut down before the analysis job could run.",
}


class QueueFullError(RuntimeError):
    """
    R4: the analysis pool is at capacity (or shutting down) and the
    work was NOT queued. Safe to retry later; routes answer 503 with a
    Retry-After header.
    """

    def __init__(self, message: str, retry_after: int = QUEUE_FULL_RETRY_AFTER_SECONDS):
        super().__init__(message)
        self.retry_after = retry_after


class JobManager:
    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_retained_jobs: int = DEFAULT_MAX_RETAINED_JOBS,
        max_queue: int = DEFAULT_MAX_QUEUE,
        task_timeout_seconds: float | None = DEFAULT_TASK_TIMEOUT_SECONDS,
    ):
        self._max_workers = max_workers
        self._max_retained_jobs = max_retained_jobs
        self._capacity = max_workers + max_queue
        self._task_timeout_seconds = task_timeout_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        # Futures admitted and not yet done - the admission count, and
        # what shutdown waits on.
        self._pending: set[Future] = set()
        self._executor = self._new_executor()
        self._accepting = True

    def _new_executor(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="analysis-job",
        )

    # -----------------------------------------------------
    # Admission (R4)
    # -----------------------------------------------------

    def _bounded(self, work: Callable[[], Any]) -> Callable[[], Any]:
        timeout = self._task_timeout_seconds

        def _call():
            with query_deadline(timeout):
                return work()

        return _call

    def _admit_and_submit(self, fn: Callable, *args) -> Future:
        """
        Submit fn(*args) if the pool has capacity, else raise
        QueueFullError without queueing anything. The capacity check
        and the submission happen under one lock, so concurrent callers
        can never overshoot the cap.
        """
        with self._lock:
            if not self._accepting:
                raise QueueFullError("The analysis service is shutting down.")

            if len(self._pending) >= self._capacity:
                raise QueueFullError("The analysis queue is full.")

            try:
                future = self._executor.submit(fn, *args)
            except RuntimeError as exc:  # executor shut down underneath us
                raise QueueFullError("The analysis service is shutting down.") from exc

            self._pending.add(future)

        future.add_done_callback(self._release)
        return future

    def _release(self, future: Future) -> None:
        with self._lock:
            self._pending.discard(future)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def submit(
        self,
        owner_id: str,
        dataset_id: str,
        work: Callable[[], Any],
    ) -> dict:
        """
        Queue `work` and return a snapshot of the new job. owner_id and
        dataset_id are fixed at creation and never change afterwards.

        R4: raises QueueFullError (and records no job) when the pool is
        at capacity. The work runs under the task deadline; a DuckDB
        query still running when it expires is interrupted and the job
        fails with a 504 error.
        """

        job = Job(
            job_id=str(uuid.uuid4()),
            owner_id=owner_id,
            dataset_id=dataset_id,
        )

        with self._lock:
            self._jobs[job.job_id] = job
            self._evict_finished_locked()
            snapshot = job.to_dict()

        try:
            future = self._admit_and_submit(self._run, job, self._bounded(work))
        except QueueFullError:
            with self._lock:
                self._jobs.pop(job.job_id, None)
            raise

        future.add_done_callback(lambda done: self._fail_if_cancelled(job, done))
        return snapshot

    def run(self, work: Callable[[], Any]) -> Future:
        """
        Step 84: run `work` on the same bounded pool as tracked jobs,
        without creating a Job record, and return its Future.

        Used by the synchronous /api/analyze route so both analysis
        entry points share one ANALYSIS_JOB_WORKERS budget instead of
        the sync route drawing on the web server's general threadpool.
        Exceptions raised by `work` propagate unchanged through the
        Future; cancelling it before a worker picks it up drops the work.

        R4: raises QueueFullError when the pool is at capacity, and the
        work runs under the task deadline (QueryTimeoutError propagates
        through the Future like any other exception).
        """

        return self._admit_and_submit(self._bounded(work))

    def get(self, job_id: str, owner_id: str) -> dict | None:
        """
        Return a snapshot of the job only if `owner_id` owns it. A job
        owned by someone else is indistinguishable from one that does
        not exist.
        """

        with self._lock:
            job = self._jobs.get(job_id)

            if job is None or not owner_id or job.owner_id != owner_id:
                return None

            return job.to_dict()

    # -----------------------------------------------------
    # Lifecycle (R6)
    # -----------------------------------------------------

    def start(self) -> None:
        """
        Accept work again after shutdown()/begin_shutdown(), with a
        fresh executor. No-op while already accepting. Lets the
        process-wide manager survive repeated app lifespans (tests,
        reloads).
        """
        with self._lock:
            if self._accepting:
                return
            self._executor = self._new_executor()
            self._accepting = True

    def begin_shutdown(self) -> None:
        """
        Stop accepting work and cancel everything still queued (their
        callers see a cancelled Future; tracked jobs are marked failed
        with a 503 error). Running work is left to finish or to be
        interrupted - see wait_for_running().
        """
        with self._lock:
            self._accepting = False
            executor = self._executor

        executor.shutdown(wait=False, cancel_futures=True)

    def wait_for_running(self, timeout: float | None) -> bool:
        """Wait up to `timeout` seconds for admitted work; True if all done."""
        with self._lock:
            pending = list(self._pending)

        if not pending:
            return True

        _, not_done = wait_for_futures(pending, timeout=timeout)
        return not not_done

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._accepting = False
            executor = self._executor

        executor.shutdown(wait=wait)

    def _fail_if_cancelled(self, job: Job, future: Future) -> None:
        if future.cancelled():
            self._transition(job, JOB_FAILED, error=dict(SHUTDOWN_JOB_ERROR))

    def _run(self, job: Job, work: Callable[[], Any]) -> None:
        self._transition(job, JOB_RUNNING)

        try:
            result = work()

        except JobError as exc:
            self._transition(
                job,
                JOB_FAILED,
                error={"status_code": exc.status_code, "detail": exc.detail},
            )

        except QueryTimeoutError:
            # Only raised once the query was confirmed stopped (or was
            # never started because the deadline had already passed).
            logger.warning(
                "Analysis job %s exceeded its time limit (dataset_id=%r).",
                job.job_id,
                job.dataset_id,
            )
            self._transition(job, JOB_FAILED, error=dict(TIMEOUT_JOB_ERROR))

        except Exception:
            logger.exception(
                "Analysis job %s failed (dataset_id=%r)",
                job.job_id,
                job.dataset_id,
            )
            self._transition(job, JOB_FAILED, error=dict(GENERIC_JOB_ERROR))

        else:
            self._transition(job, JOB_COMPLETED, result=result)

    def _transition(self, job: Job, status: str, *, result=None, error=None) -> None:
        with self._lock:
            job.status = status
            job.result = result
            job.error = error
            job.updated_at = _utc_now()

    def _evict_finished_locked(self) -> None:
        # Bound memory: drop the oldest finished jobs once over the
        # retention cap. Queued/running jobs are never evicted.
        excess = len(self._jobs) - self._max_retained_jobs

        if excess <= 0:
            return

        for job_id in [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in _TERMINAL_STATUSES
        ][:excess]:
            del self._jobs[job_id]


job_manager = JobManager()
