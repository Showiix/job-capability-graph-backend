import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.database import engine
from app.infrastructure.neo4j import neo4j_driver
from app.infrastructure.redis import redis_client
from app.processing.models import ProcessingRun

logger = logging.getLogger(__name__)
Probe = Callable[[], Awaitable["DependencyStatus"]]


@dataclass(frozen=True)
class DependencyStatus:
    status: Literal["ok", "degraded", "down"]
    latency_ms: float | None


def elapsed_ms(started: float) -> float:
    return round((monotonic() - started) * 1000, 2)


async def probe_postgres() -> DependencyStatus:
    started = monotonic()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_redis() -> DependencyStatus:
    started = monotonic()
    await redis_client.ping()
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_neo4j() -> DependencyStatus:
    started = monotonic()
    await neo4j_driver.verify_connectivity()
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_file_volume() -> DependencyStatus:
    started = monotonic()
    await asyncio.to_thread(_write_volume_probe, get_settings().file_storage_root)
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_algorithm_service() -> DependencyStatus:
    started = monotonic()
    url = f"{str(get_settings().algorithm_service_url).rstrip('/')}/health"
    await asyncio.to_thread(_request_health, url)
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_dependencies() -> dict[str, DependencyStatus]:
    names = (
        "postgresql",
        "redis",
        "neo4j",
        "file_volume",
        "algorithm_service",
    )
    results = await asyncio.gather(
        _safe_probe(probe_postgres),
        _safe_probe(probe_redis),
        _safe_probe(probe_neo4j),
        _safe_probe(probe_file_volume),
        _safe_probe(probe_algorithm_service, failure_status="degraded"),
    )
    return dict(zip(names, results, strict=True))


async def dependency_diagnostics(db: AsyncSession) -> dict:
    statuses = await probe_dependencies()
    pending = await _run_count(
        db,
        ProcessingRun.status.in_({"pending", "enqueue_failed"}),
    )
    running = await _run_count(db, ProcessingRun.status == "running")
    stale = await _run_count(
        db,
        ProcessingRun.status == "running",
        ProcessingRun.heartbeat_at < datetime.now(UTC) - timedelta(minutes=5),
    )
    queue_length = None
    if statuses["redis"].status == "ok":
        try:
            queue_length = await asyncio.wait_for(redis_client.llen("celery"), 2)
        except Exception as error:
            logger.warning("celery queue probe failed: %s", type(error).__name__)
    return {
        "dependencies": {
            name: {"status": value.status, "latency_ms": value.latency_ms}
            for name, value in statuses.items()
        },
        "processing_runs": {
            "pending": pending,
            "running": running,
            "stale": stale,
        },
        "celery_queue_length": queue_length,
    }


async def system_versions(db: AsyncSession) -> dict:
    revision = await db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return {
        "api_version": "0.1.0",
        "alembic_revision": revision,
        "prompt_version": None,
        "model_version": None,
        "catalog_version": None,
        "graph_version": None,
        "weight_version": None,
    }


async def _safe_probe(
    probe: Probe,
    *,
    failure_status: Literal["degraded", "down"] = "down",
) -> DependencyStatus:
    try:
        return await asyncio.wait_for(probe(), timeout=2)
    except Exception as error:
        logger.warning("dependency probe failed: %s", type(error).__name__)
        return DependencyStatus(failure_status, None)


async def _run_count(db: AsyncSession, *filters) -> int:
    count = await db.scalar(select(func.count(ProcessingRun.id)).where(*filters))
    return int(count or 0)


def _write_volume_probe(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".health-{uuid4().hex}"
    probe.write_bytes(b"ok")
    probe.unlink()


def _request_health(url: str) -> None:
    request = Request(url, method="GET")
    with urlopen(request, timeout=2) as response:  # noqa: S310
        if response.status >= 400:
            raise OSError("algorithm service is unhealthy")
