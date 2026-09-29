from fastapi import APIRouter, Depends, HTTPException

import backend.jobs as jobs
import backend.routes.analysis as analysis_route
from backend.dependencies import (
    AuthenticatedUser,
    authorize_dataset,
    get_current_user,
)
from backend.routes.analysis import AnalysisRequest


router = APIRouter(
    prefix="/api/jobs",
    tags=["Jobs"],
)


def _run_analysis(request: AnalysisRequest, user: AuthenticatedUser):
    """
    Job body: the exact synchronous /api/analyze pipeline, unchanged.

    Resolved through the analysis module at call time, so the job path
    and the sync route can never drift apart. That pipeline raises
    HTTPException with details that are already client-safe (Step 55),
    so those are carried over as-is; anything else is treated as
    internal by the JobManager and never surfaced.
    """

    try:
        return analysis_route.analyze_dataset(request, user)

    except HTTPException as exc:
        raise jobs.JobError(exc.status_code, exc.detail) from exc


@router.post("/analysis", status_code=202)
def create_analysis_job(
    request: AnalysisRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    # Reject a dataset the caller doesn't own before anything is
    # queued. The pipeline re-checks ownership when the job runs, so a
    # dataset deleted in between also fails cleanly.
    authorize_dataset(analysis_route.dataset_registry, request.dataset_id, user)

    return jobs.job_manager.submit(
        owner_id=user.user_id,
        dataset_id=request.dataset_id,
        work=lambda: _run_analysis(request, user),
    )


@router.get("/{job_id}")
def get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    job = jobs.job_manager.get(job_id, user.user_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    return job
