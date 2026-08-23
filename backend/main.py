from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.dataset import router as dataset_router
from backend.routes.analysis import router as analysis_router


app = FastAPI(
    title="AI Data Intelligence Platform",
    version="0.1.0",
)


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
