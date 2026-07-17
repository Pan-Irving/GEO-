import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import PublishingStore
from app.routes import router
from app.sync_service import auto_sync_once


settings = get_settings()
logger = logging.getLogger("publishing.auto_sync")
auto_sync_task: asyncio.Task | None = None

app = FastAPI(title="GEO Publishing Workbench", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


async def auto_sync_loop() -> None:
    interval = max(settings.publishing_auto_sync_interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        try:
            result = await asyncio.to_thread(auto_sync_once, PublishingStore(settings), settings)
            if result["total"]:
                logger.info(
                    "auto sync finished: total=%s succeeded=%s failed=%s",
                    result["total"],
                    result["succeeded"],
                    result["failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("auto sync failed")


@app.on_event("startup")
async def start_auto_sync() -> None:
    global auto_sync_task
    if not settings.publishing_auto_sync_enabled:
        return
    auto_sync_task = asyncio.create_task(auto_sync_loop())


@app.on_event("shutdown")
async def stop_auto_sync() -> None:
    if not auto_sync_task:
        return
    auto_sync_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await auto_sync_task
