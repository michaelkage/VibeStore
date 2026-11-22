from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.schemas import HealthResponse
from app.api import router

settings = get_settings()
@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engine()

app = FastAPI(title="VibeStore API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
  allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"],
  allow_headers=["Authorization", "Content-Type"])
app.include_router(router, prefix=settings.api_v1_prefix)

@app.get("/health", response_model=HealthResponse, tags=["operations"])
async def health():
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return HealthResponse(status="ok", service="vibestore-api", database="ok")
    except SQLAlchemyError:
        return HealthResponse(status="degraded", service="vibestore-api", database="unavailable")
