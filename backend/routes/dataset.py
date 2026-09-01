import io
import os
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path

from backend.dependencies import (
    get_current_dataset,
    get_current_dataset_name,
    has_dataset_loaded,
)
from data_engine.dataset import Dataset
from data_engine.dataset_manager import (
    dataset_manager,
    get_cached_on_dataset,
)
from data_engine.dataset_registry import dataset_registry, DatasetNotFoundError
from data_engine.ingestion import ingest_to_parquet
from data_engine.profiling import basic_statistics_for_dataset
from data_engine.metadata_engine import metadata_for_dataset
from data_engine.quality import check_quality_for_dataset
from data_engine.preview import preview_dataset


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


# Where ingest_to_parquet persists each uploaded dataset's Parquet
# file, named "{dataset_id}.parquet". Module-level so tests can point
# it at a scratch directory instead of the real one.
PARQUET_STORAGE_ROOT = os.path.join("data", "uploads")


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

        # Stream straight to Parquet through the bounded-memory
        # ingestion pipeline (data_engine.ingestion.ingest_to_parquet)
        # instead of parsing the bytes into a full Pandas DataFrame
        # here. The dataset_id is minted up front because
        # ingest_to_parquet names its output "{dataset_id}.parquet" -
        # DatasetManager then registers the Dataset under that same
        # id, so the registry entry and the on-disk Parquet file always
        # agree.
        #
        # Storage-backend choice for the ingested Parquet file is not
        # decided here: register_ingested_dataset delegates that to
        # select_storage_for_ingestion in the storage/selector tier, so
        # this route never branches on storage/engine type itself.
        #
        # It also still becomes "the active dataset" for every existing
        # endpoint below and in analysis.py, which don't take a
        # dataset_id yet - that's unchanged in this step.
        dataset_id = str(uuid.uuid4())

        ingestion_result = ingest_to_parquet(
            source_stream=io.BytesIO(contents),
            dataset_id=dataset_id,
            storage_root=PARQUET_STORAGE_ROOT,
        )

        dataset = dataset_manager.register_ingested_dataset(
            ingestion_result,
            filename=file.filename,
        )

        return {
            "message": "Dataset uploaded successfully.",
            "filename": file.filename,
            "rows": dataset.row_count,
            "columns": dataset.column_count,
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


def _legacy_profile_from_stats(stats: dict) -> dict:
    """
    Reshape basic_statistics_for_dataset()'s Step 9 contract output
    into the historical data_engine.profiler.profile_dataset()
    response shape, so existing /profile API consumers see no schema
    change from this route now funneling through the storage-aware
    profiling boundary instead of always materializing a DataFrame.

    duplicate_rows and memory_usage_bytes are not part of the Step 9
    "basic statistics" contract itself - they are bridged in as a
    legacy fallback because basic_statistics_for_dataset() carries them
    anyway precisely so callers like this one never have to trigger a
    second, separate materialization to get them. memory_usage_bytes
    is None for a DuckDB-backed dataset (no faithful native equivalent
    to pandas' memory_usage(deep=True) - see
    data_engine/profiling/duckdb_profiling.py).
    """

    columns = stats["columns"]

    return {
        "rows": stats["row_count"],
        "columns": stats["column_count"],
        "column_names": list(columns.keys()),
        "data_types": {
            name: info["data_type"] for name, info in columns.items()
        },
        "missing_values": {
            name: info["missing_count"] for name, info in columns.items()
        },
        "duplicate_rows": stats["duplicate_rows"],
        "memory_usage_bytes": stats["memory_usage_bytes"],
        "column_details": {
            name: {
                "data_type": info["data_type"],
                "missing_count": info["missing_count"],
                "missing_percentage": info["missing_percentage"],
                "unique_values": info["distinct_count"],
            }
            for name, info in columns.items()
        },
    }


@router.get("/profile")
def get_dataset_profile():

    # Not require_dataset(): that helper's return value
    # (get_current_dataset()) unconditionally materializes the active
    # dataset's full DataFrame via dataset_manager.get_dataframe() -
    # exactly the raw-record pull this route no longer needs. Only the
    # cheap "is anything loaded" gate check is wanted here.
    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    stats = dataset_manager.get_cached_dataset_aware(
        "basic_statistics",
        basic_statistics_for_dataset,
    )

    return {
        **_legacy_profile_from_stats(stats),
        "filename": get_current_dataset_name(),
    }


@router.get("/{dataset_id}/profile")
def get_dataset_profile_by_id(dataset_id: str):
    """
    Same response shape as GET /profile, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    stats = get_cached_on_dataset(
        dataset,
        "basic_statistics",
        basic_statistics_for_dataset,
    )

    return {
        **_legacy_profile_from_stats(stats),
        "filename": dataset.name,
    }


# =========================================================
# PREVIEW
# =========================================================


@router.get("/preview")
def get_dataset_preview():

    # Not require_dataset(): that helper's return value
    # (get_current_dataset()) unconditionally materializes the active
    # dataset's full DataFrame via dataset_manager.get_dataframe() -
    # exactly the raw-record pull this route no longer needs. Only the
    # cheap "is anything loaded" gate check is wanted here.
    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    dataset = dataset_manager.get_active_dataset()

    return {
        "filename": get_current_dataset_name(),
        **preview_dataset(dataset),
    }


@router.get("/{dataset_id}/preview")
def get_dataset_preview_by_id(dataset_id: str):
    """
    Same response shape as GET /preview, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    return {
        "filename": dataset.name,
        **preview_dataset(dataset),
    }


# =========================================================
# DATA QUALITY
# =========================================================


@router.get("/quality")
def get_dataset_quality():

    # Not require_dataset(): see get_dataset_preview() above - only
    # the cheap "is anything loaded" gate check is wanted here.
    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    return dataset_manager.get_cached_dataset_aware(
        "quality",
        check_quality_for_dataset,
    )


@router.get("/{dataset_id}/quality")
def get_dataset_quality_by_id(dataset_id: str):
    """
    Same response shape as GET /quality, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    return get_cached_on_dataset(
        dataset,
        "quality",
        check_quality_for_dataset,
    )


# =========================================================
# METADATA
# =========================================================


@router.get("/metadata")
def get_dataset_metadata():

    # Not require_dataset(): see get_dataset_preview() above - only
    # the cheap "is anything loaded" gate check is wanted here.
    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    return dataset_manager.get_cached_dataset_aware(
        "metadata",
        metadata_for_dataset,
    )


@router.get("/{dataset_id}/metadata")
def get_dataset_metadata_by_id(dataset_id: str):
    """
    Same response shape as GET /metadata, but scoped to an explicit
    dataset_id instead of implicitly targeting "the active dataset".
    """

    dataset = resolve_dataset(dataset_id)

    return get_cached_on_dataset(
        dataset,
        "metadata",
        metadata_for_dataset,
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
    Remove a dataset from the registry and release everything it
    holds: the registry entry, its storage's resources (e.g. a
    DuckDB connection), and its on-disk artifact (e.g. a Parquet
    file), if it has one.

    This route stays storage-agnostic on purpose: it never imports a
    concrete storage/execution engine and never touches the
    filesystem itself. It only calls dataset_registry.delete(), which
    triggers storage.close() and artifact cleanup through the
    DatasetStorage contract (DatasetStorage.close() /
    DatasetStorage.artifact_path) - the same abstraction every other
    route in this module already depends on, never a concrete
    backend. A storage-close or filesystem-cleanup failure there is
    logged and does not surface as an error response here; the
    registry entry itself is still gone either way.

    If dataset_id is the currently active dataset, the active pointer
    is cleared too, so DatasetManager never keeps resolving to a
    dataset that no longer exists in the registry. Deleting a dataset
    that isn't the active one leaves the active pointer untouched.
    """

    resolve_dataset(dataset_id)

    dataset_registry.delete(dataset_id)
    dataset_manager.clear_dataset(dataset_id)

    return {
        "message": "Dataset deleted successfully.",
        "dataset_id": dataset_id,
    }
