from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import router
from app.patch_processing import router as patch_processing_router
from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.redis_client import close_redis, init_redis, redis_is_healthy
from app.schemas import HealthResponse
from app.observability import (
    RequestObservabilityMiddleware,
    configure_logging,
    metrics_payload,
)

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_redis()
    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()


app = FastAPI(title="VibeStore API", version="0.2.0", lifespan=lifespan)
app.add_middleware(RequestObservabilityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(patch_processing_router, prefix=settings.api_v1_prefix)


@app.get("/health", response_model=HealthResponse, tags=["operations"])
async def health():
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_status = "ok"
    except SQLAlchemyError:
        database_status = "unavailable"
    redis_status = "ok" if await redis_is_healthy() else "unavailable"
    status = "ok" if database_status == "ok" and redis_status == "ok" else "degraded"
    return HealthResponse(
        status=status,
        service="vibestore-api",
        database=database_status,
        redis=redis_status,
    )



@app.get("/metrics", include_in_schema=False)
async def metrics():
    if not settings.metrics_enabled:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled")
    from fastapi.responses import Response

    payload, media_type = metrics_payload()
    return Response(content=payload, media_type=media_type)
