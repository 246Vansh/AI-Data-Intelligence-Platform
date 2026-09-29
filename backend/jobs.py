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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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


class JobManager:
    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_retained_jobs: int = DEFAULT_MAX_RETAINED_JOBS,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="analysis-job",
        )
        self._max_retained_jobs = max_retained_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        owner_id: str,
        dataset_id: str,
        work: Callable[[], Any],
    ) -> dict:
        """
        Queue `work` and return a snapshot of the new job. owner_id and
        dataset_id are fixed at creation and never change afterwards.
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

        self._executor.submit(self._run, job, work)
        return snapshot

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

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

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
