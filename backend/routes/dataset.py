from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import tempfile
import math

from backend.dependencies import (
    get_current_dataset,
    get_current_dataset_name,
    has_dataset_loaded,
)
from data_engine.dataset_manager import dataset_manager
from data_engine.profiler import profile_dataset
from data_engine.metadata import get_metadata
from data_engine.data_quality import check_data_quality


router = APIRouter(
    prefix="/api/dataset",
    tags=["Dataset"],
)


def make_json_safe(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            return None

    return value


def require_dataset():
    """
    Return the active dataset or a clean 404 when
    nothing has been uploaded yet - instead of a 500.
    """

    if not has_dataset_loaded():
        raise HTTPException(
            status_code=404,
            detail="No dataset has been uploaded yet.",
        )

    return get_current_dataset()


# =========================================================
# UPLOAD
# =========================================================


MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB limit


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """
    Upload a CSV dataset and make it the active dataset.
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
        contents = await file.read()

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The uploaded CSV file is empty.",
            )

        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file exceeds maximum allowed size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        # Store temporarily so DatasetManager remains
        # responsible for loading and validating the CSV.
        with tempfile.NamedTemporaryFile(
            suffix=".csv",
            delete=False,
        ) as temp_file:
            temp_file.write(contents)
            temp_path = temp_file.name

        try:
            df = dataset_manager.load_csv(
                temp_path,
                filename=file.filename,
            )

        finally:
            Path(temp_path).unlink(missing_ok=True)

        return {
            "message": "Dataset uploaded successfully.",
            "filename": file.filename,
            "rows": len(df),
            "columns": len(df.columns),
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


# =========================================================
# PREVIEW
# =========================================================


@router.get("/preview")
def get_dataset_preview():

    df = require_dataset()

    preview = df.head(10)

    rows = preview.to_dict(orient="records")

    rows = [{key: make_json_safe(value) for key, value in row.items()} for row in rows]

    return {
        "filename": get_current_dataset_name(),
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
