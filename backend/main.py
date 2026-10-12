import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.routes.dataset import (
    MAX_UPLOAD_BYTES,
    PARQUET_STORAGE_ROOT,
    router as dataset_router,
)
from backend.routes.analysis import router as analysis_router
from backend.routes.jobs import router as jobs_router
from data_engine.dataset import Dataset
from data_engine.dataset_manifest import (
    LegacyManifestError,
    find_manifest_paths,
    read_manifest,
)
from data_engine.dataset_registry import DatasetRegistry, dataset_registry
from data_engine.storage import UnsupportedStorageTypeError, open_storage


logger = logging.getLogger(__name__)


def _recover_datasets(
    storage_root: str = PARQUET_STORAGE_ROOT,
    registry: DatasetRegistry = dataset_registry,
) -> None:
    """
    Step 4 - restart durability: re-register every dataset whose
    manifest sidecar and storage artifact both still exist, so
    datasets uploaded by a prior process remain reachable after a
    restart (DatasetRegistry is otherwise in-memory only).

    Never raises and never fails startup - a bad manifest, a missing
    Parquet file, an unreadable Parquet file, or a duplicate
    dataset_id is logged and that one dataset is skipped; every other
    valid dataset is still recovered. An unsupported or malformed
    storage reference (Step 58) is skipped the same way.

    Opening goes through data_engine.storage.open_storage, which
    dispatches on the manifest's storage type ("parquet" ->
    DuckDBStorage.from_parquet) - this function never branches on it.

    Each recovered Dataset keeps the owner_id recorded in its
    manifest. A legacy manifest written before ownership existed is
    skipped with a warning rather than assigned an arbitrary owner -
    its Parquet file and manifest are left untouched on disk so
    ownership can be assigned deliberately later.
    """

    seen_ids: set[str] = set()

    for manifest_path in find_manifest_paths(storage_root):
        try:
            manifest = read_manifest(manifest_path)

        except LegacyManifestError:
            logger.warning(
                "Skipping legacy manifest %r: it has no owner_id, and no "
                "owner is assumed. Add an explicit owner_id to recover it.",
                manifest_path,
            )
            continue

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

        try:
            storage = open_storage(manifest.storage)

        except UnsupportedStorageTypeError as exc:
            logger.error("Skipping dataset_id=%r: %s", manifest.dataset_id, exc)
            continue

        except FileNotFoundError as exc:
            logger.warning("Skipping dataset_id=%r: %s", manifest.dataset_id, exc)
            continue

        except Exception as exc:
            logger.error(
                "Skipping dataset_id=%r: failed to open %s storage %r: %s",
                manifest.dataset_id,
                manifest.storage.type,
                manifest.storage.location,
                exc,
            )
            continue

        registry.register(
            Dataset(
                storage=storage,
                name=manifest.name,
                dataset_id=manifest.dataset_id,
                created_at=manifest.created_at,
                owner_id=manifest.owner_id,
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


# Derived from MAX_UPLOAD_BYTES (backend/routes/dataset.py) - the
# single source of truth for the upload-size policy - so this
# middleware ceiling and the route's own streaming enforcement can
# never silently disagree. A little headroom is added on top for
# multipart boundary/header overhead around the actual file bytes.
MAX_REQUEST_BODY_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024


class _RequestBodyTooLarge(Exception):
    """Raised from the wrapped receive() once the body limit is crossed."""


def _request_body_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": "Request body exceeds the maximum allowed size."},
    )


class MaxBodySizeMiddleware:
    """
    Reject an oversized request body while it is being received,
    before it can be spooled to disk.

    Plain ASGI rather than BaseHTTPMiddleware on purpose: the limit
    has to be enforced on the ``receive`` channel itself. FastAPI
    parses a multipart upload (``await request.form()``) to completion
    before the route runs, and Starlette spools every file part to a
    temporary file with no size cap of its own - so a check in the
    route, or one that only looks at Content-Length, cannot stop a
    chunked request that omits Content-Length from writing its whole
    body to disk first.

    Two checks, both against ``MAX_REQUEST_BODY_BYTES`` read per
    request (so tests can override it):

    1. A declared Content-Length over the limit is rejected up front,
       without reading any of the body.
    2. Every ``http.request`` message passing through ``receive`` is
       counted; once the running total exceeds the limit, receive
       raises and the body is never read further.

    FastAPI converts an error raised while reading the body into its
    own 400 response, so once the limit is crossed this middleware
    discards whatever response the inner app produces and sends the
    413 itself - unless the inner app had already started a response
    before the limit was crossed, in which case nothing is replaced
    (no second response start) and the error is left to propagate.
    Only the middleware's own limit signal is ever suppressed; any
    other exception from the inner app propagates unchanged.

    The upload route keeps its own per-file size check as the exact
    file-bytes limit; this is the request-level ceiling around it.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = MAX_REQUEST_BODY_BYTES

        content_length = Headers(scope=scope).get("content-length")

        if content_length is not None:
            try:
                declared_size = int(content_length)

            except ValueError:
                declared_size = None

            if declared_size is not None and declared_size > limit:
                await _request_body_too_large_response()(scope, receive, send)
                return

        received_bytes = 0
        exceeded = False
        response_started = False
        # Whether the inner app's response was already on the wire
        # when the limit was crossed - only then is it left alone.
        started_before_exceeded = False

        async def limited_receive() -> Message:
            nonlocal received_bytes, exceeded, started_before_exceeded

            if exceeded:
                raise _RequestBodyTooLarge()

            message = await receive()

            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))

                if received_bytes > limit:
                    exceeded = True
                    started_before_exceeded = response_started
                    raise _RequestBodyTooLarge()

            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started

            if exceeded and not started_before_exceeded:
                # The inner app is answering a request this middleware
                # is rejecting (e.g. FastAPI's 400 for an unreadable
                # body) - drop it; the 413 is sent below instead.
                return

            if message["type"] == "http.response.start":
                response_started = True

            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)

        except _RequestBodyTooLarge:
            # Only this middleware's own signal is handled here. Under
            # FastAPI it never arrives: FastAPI turns it into a 400 that
            # guarded_send() drops, and the inner app returns normally.
            # It does arrive from plain ASGI/Starlette code that lets it
            # propagate. Any other exception - even after the limit was
            # crossed - is an unrelated failure and propagates as-is.
            if started_before_exceeded:
                raise

        if exceeded and not started_before_exceeded:
            await _request_body_too_large_response()(scope, receive, send)


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
app.include_router(jobs_router)


@app.get("/")
def root():
    return {
        "project": "AI Data Intelligence Platform",
        "status": "running",
    }
