from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.metadata_repository import MetadataRepository


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.datasets_dir.mkdir(parents=True, exist_ok=True)
    MetadataRepository(settings.metadata_database_path).initialize()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Natural-language analytics over user-provided datasets.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ai-sql-analyst-api",
        "version": app.version,
    }
