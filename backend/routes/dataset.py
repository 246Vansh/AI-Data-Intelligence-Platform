from fastapi import APIRouter

from backend.dependencies import get_walmart_data
from data_engine.profiler import profile_dataset
from data_engine.metadata import get_metadata

router = APIRouter(
    prefix="/api/dataset",
    tags=["Dataset"],
)


@router.get("/profile")
def get_dataset_profile():

    df = get_walmart_data()

    profile = profile_dataset(df)

    return profile


@router.get("/preview")
def get_dataset_preview():

    df = get_walmart_data()

    # Get one representative row from each store
    preview = df.drop_duplicates(subset=["Store"]).head(10)

    return {
        "columns": preview.columns.tolist(),
        "rows": preview.to_dict(orient="records"),
    }


@router.get("/metadata")
def get_dataset_metadata():

    df = get_walmart_data()

    metadata = get_metadata(df)

    return metadata
