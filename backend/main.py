from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.routes.dataset import router as dataset_router
from backend.routes.analysis import router as analysis_router


app = FastAPI(
    title="AI Data Intelligence Platform",
    version="0.1.0",
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
