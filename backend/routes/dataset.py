from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path

from backend.dependencies import (
    get_current_dataset,
    get_current_dataset_name,
    has_dataset_loaded,
)
from data_engine.dataset import Dataset
from data_engine.dataset_manager import dataset_manager, get_cached_on
from data_engine.dataset_registry import dataset_registry, DatasetNotFoundError
from data_engine.profiler import profile_dataset
from data_engine.metadata import get_metadata
from data_engine.data_quality import check_data_quality
from data_engine.json_safety import sanitize_records


router = APIRouter(
    prefix="/api/dataset",
    tags=["Dataset"],
)


def require_dataset():
    """
    Return the active dataset or a clean 404 when
    nothing has been uploaded yet - instead of a 500.

    Legacy "implicit active dataset" path, kept for the existing
    no-dataset_id routes below (still what the current frontend
    calls). See resolve_dataset() for the explicit-dataset_id
    equivalent used by the /{dataset_id}/... routes.
    """

    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    return get_current_dataset()


def resolve_dataset(dataset_id: str) -> Dataset:
    """
    Resolve dataset_id to its Dataset via the registry, or raise a
    clean, controlled 404 - the API-layer translation of
    DatasetRegistry's framework-free DatasetNotFoundError. Any
    dataset_id that doesn't currently resolve to a registered
    dataset (malformed, never issued, or already deleted) gets the
    same controlled response; the registry itself never needs to
    know HTTP exists.
    """

    try:
        return dataset_registry.get(dataset_id)

    except DatasetNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No dataset found for dataset_id: {dataset_id!r}",
        ) from exc


# =========================================================
# UPLOAD
# =========================================================


MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB limit


# Read in fixed-size chunks so an oversized upload is rejected as
# soon as it crosses the limit, instead of being buffered into
# memory in full first.
UPLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB


@router.post("/upload")
def upload_dataset(file: UploadFile = File(...)):
    """
    Upload a CSV dataset and make it the active dataset.

    Defined as a plain (sync) endpoint rather than `async def` on
    purpose: FastAPI dispatches sync endpoints to a worker thread
    automatically, so the blocking file read and the CPU-bound CSV
    parse below don't stall the event loop for other requests. An
    `async def` version that calls `dataset_manager.load_csv()`
    directly would run that parse inline on the loop instead.
    """

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file was provided.",
        )

    if Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are currently supported.",
        )

    try:
        chunks = []
        total_bytes = 0

        while True:
            chunk = file.file.read(UPLOAD_CHUNK_BYTES)

            if not chunk:
                break

            total_bytes += len(chunk)

            if total_bytes > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded file exceeds maximum allowed size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )

            chunks.append(chunk)

        contents = b"".join(chunks)

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The uploaded CSV file is empty.",
            )

        # A CSV is text. Null bytes are the cheapest signal that
        # this is actually a binary file wearing a ".csv" extension
        # (pandas would otherwise fail deep inside the C parser with
        # a much more confusing error).
        if b"\x00" in contents[:UPLOAD_CHUNK_BYTES]:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file does not look like a text CSV file.",
            )

        # Parse directly from the bytes already in memory - no
        # temp-file round-trip. Measured ~7x faster on a 22MB file
        # by itself (pyarrow engine inside register_csv_bytes), plus
        # this removes a disk write + read + unlink on top of that.
        #
        # register_csv_bytes() (rather than load_csv_bytes()) because
        # this route needs the assigned dataset_id back - each upload
        # creates an independent Dataset in the registry, it never
        # overwrites a previously uploaded one. It also still becomes
        # "the active dataset" for every existing endpoint below and
        # in analysis.py, which don't take a dataset_id yet - that's
        # unchanged in this step.
        dataset = dataset_manager.register_csv_bytes(
            contents,
            filename=file.filename,
        )
        df = dataset.storage.to_dataframe()

        return {
            "message": "Dataset uploaded successfully.",
            "filename": file.filename,
            "rows": len(df),
            "columns": len(df.columns),
            "dataset_id": dataset.dataset_id,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to load dataset: {str(exc)}",
        )


# =========================================================
# PROFILE
# =========================================================


@router.get("/profile")
def get_dataset_profile():

    require_dataset()

    profile = dataset_manager.get_cached(
        "profile",
        profile_dataset,
    )

    return {
        **profile,
        "filename": get_current_dataset_name(),
    }


@router.get("/{dataset_id}/profile")
def get_dataset_profile_by_id(dataset_id: str):
    """
    Same response shape as GET /profile, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    profile = get_cached_on(
        dataset,
        "profile",
        profile_dataset,
    )

    return {
        **profile,
        "filename": dataset.name,
    }


# =========================================================
# PREVIEW
# =========================================================


@router.get("/preview")
def get_dataset_preview():

    df = require_dataset()

    preview = df.head(10)

    rows = sanitize_records(preview.to_dict(orient="records"))

    return {
        "filename": get_current_dataset_name(),
        "columns": preview.columns.tolist(),
        "rows": rows,
    }


@router.get("/{dataset_id}/preview")
def get_dataset_preview_by_id(dataset_id: str):
    """
    Same response shape as GET /preview, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    preview = dataset.storage.to_dataframe().head(10)

    rows = sanitize_records(preview.to_dict(orient="records"))

    return {
        "filename": dataset.name,
        "columns": preview.columns.tolist(),
        "rows": rows,
    }


# =========================================================
# DATA QUALITY
# =========================================================


@router.get("/quality")
def get_dataset_quality():

    require_dataset()

    return dataset_manager.get_cached(
        "quality",
        check_data_quality,
    )


@router.get("/{dataset_id}/quality")
def get_dataset_quality_by_id(dataset_id: str):
    """
    Same response shape as GET /quality, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    return get_cached_on(
        dataset,
        "quality",
        check_data_quality,
    )


# =========================================================
# METADATA
# =========================================================


@router.get("/metadata")
def get_dataset_metadata():

    require_dataset()

    return dataset_manager.get_cached(
        "metadata",
        get_metadata,
    )


@router.get("/{dataset_id}/metadata")
def get_dataset_metadata_by_id(dataset_id: str):
    """
    Same response shape as GET /metadata, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    return get_cached_on(
        dataset,
        "metadata",
        get_metadata,
    )


# =========================================================
# REGISTRY: LIST / GET / DELETE
#
# Registry-level views over every uploaded dataset, independent of
# which one (if any) is currently active. These never materialize a
# dataset's DataFrame - they only read the identity/lifecycle fields
# Dataset and DatasetStorage already expose (dataset_id, filename,
# row_count, column_count, created_at).
# =========================================================


def _dataset_summary(dataset: Dataset) -> dict:
    """
    Build the summary shape shared by GET /api/dataset and
    GET /api/dataset/{dataset_id}.
    """

    return {
        "dataset_id": dataset.dataset_id,
        "filename": dataset.name,
        "rows": dataset.row_count,
        "columns": dataset.column_count,
        "created_at": dataset.created_at.isoformat(),
    }


@router.get("")
def list_datasets():
    """
    List every dataset currently registered, independent of the
    active dataset.
    """

    return {
        "datasets": [
            _dataset_summary(dataset)
            for dataset in dataset_registry.list()
        ]
    }


@router.get("/{dataset_id}")
def get_dataset_by_id(dataset_id: str):
    """
    Return registry-level metadata for a single dataset without
    materializing its DataFrame.
    """

    dataset = resolve_dataset(dataset_id)

    return _dataset_summary(dataset)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str):
    """
    Remove a dataset from the registry.

    Only the in-memory registry entry is removed - no on-disk source
    files (e.g. under data/raw) are touched. If dataset_id is the
    currently active dataset, the active pointer is cleared too, so
    DatasetManager never keeps resolving to a dataset that no longer
    exists in the registry.
    """

    resolve_dataset(dataset_id)

    dataset_registry.delete(dataset_id)
    dataset_manager.clear_dataset(dataset_id)

    return {
        "message": "Dataset deleted successfully.",
        "dataset_id": dataset_id,
    }
