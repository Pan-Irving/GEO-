from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.storage.factory import create_project_repository


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_project_repository(settings).recover_interrupted_jobs()
    yield


app = FastAPI(title="GEO Writing Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
