import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.routes.dataset import PARQUET_STORAGE_ROOT, router as dataset_router
from backend.routes.analysis import router as analysis_router
from data_engine.dataset import Dataset
from data_engine.dataset_manifest import find_manifest_paths, read_manifest
from data_engine.dataset_registry import DatasetRegistry, dataset_registry
from data_engine.storage import DuckDBStorage


logger = logging.getLogger(__name__)


def _recover_datasets(
    storage_root: str = PARQUET_STORAGE_ROOT,
    registry: DatasetRegistry = dataset_registry,
) -> None:
    """
    Step 4 - restart durability: re-register every dataset whose
    manifest sidecar and Parquet artifact both still exist on disk, so
    datasets uploaded by a prior process remain reachable after a
    restart (DatasetRegistry is otherwise in-memory only).

    Never raises and never fails startup - a bad manifest, a missing
    Parquet file, an unreadable Parquet file, or a duplicate
    dataset_id is logged and that one dataset is skipped; every other
    valid dataset is still recovered.
    """

    seen_ids: set[str] = set()

    for manifest_path in find_manifest_paths(storage_root):
        try:
            manifest = read_manifest(manifest_path)

        except ValueError as exc:
            logger.error("Skipping unreadable manifest %r: %s", manifest_path, exc)
            continue

        if manifest.dataset_id in seen_ids:
            logger.error(
                "Skipping duplicate dataset_id=%r from manifest %r.",
                manifest.dataset_id,
                manifest_path,
            )
            continue

        if not os.path.exists(manifest.parquet_path):
            logger.warning(
                "Skipping dataset_id=%r: Parquet file missing at %r.",
                manifest.dataset_id,
                manifest.parquet_path,
            )
            continue

        try:
            storage = DuckDBStorage.from_parquet(manifest.parquet_path)

        except Exception as exc:
            logger.error(
                "Skipping dataset_id=%r: failed to open Parquet file %r: %s",
                manifest.dataset_id,
                manifest.parquet_path,
                exc,
            )
            continue

        registry.register(
            Dataset(
                storage=storage,
                name=manifest.name,
                dataset_id=manifest.dataset_id,
                created_at=manifest.created_at,
            )
        )
        seen_ids.add(manifest.dataset_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _recover_datasets()
    yield


app = FastAPI(
    title="AI Data Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)


# Keep in sync with MAX_UPLOAD_BYTES in backend/routes/dataset.py.
# A little headroom is added for multipart boundary/header overhead
# around the actual file bytes.
MAX_REQUEST_BODY_BYTES = 100 * 1024 * 1024 + 1024 * 1024


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """
    Reject an oversized request before its body is parsed at all.

    The upload route also enforces a size limit itself, but by the
    time that code runs, Starlette's multipart parser has already
    buffered the file. Checking Content-Length here up front avoids
    ever starting that work for a request that declares itself too
    large. (A client that omits Content-Length or lies about it
    still falls through to the route's own chunked-read check.)
    """

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                declared_size = int(content_length)

            except ValueError:
                declared_size = None

            if declared_size is not None and declared_size > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds the maximum allowed size."},
                )

        return await call_next(request)


app.add_middleware(MaxBodySizeMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(dataset_router)
app.include_router(analysis_router)


@app.get("/")
def root():
    return {
        "project": "AI Data Intelligence Platform",
        "status": "running",
    }
