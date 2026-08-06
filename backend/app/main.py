from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.infrastructure.database import engine
from app.infrastructure.neo4j import neo4j_driver
from app.infrastructure.redis import redis_client
from app.system.router import health_router


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
    await redis_client.aclose()
    await neo4j_driver.close()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    application = FastAPI(
        title="岗位能力图谱系统 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    application.add_middleware(RequestIDMiddleware)
    install_error_handlers(application)
    application.include_router(api_router)
    application.include_router(health_router)

    @application.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
