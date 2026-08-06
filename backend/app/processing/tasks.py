import asyncio
from collections.abc import Awaitable, Callable

from app.infrastructure.database import SessionFactory
from app.processing.service import (
    clean_expired_sessions,
    clean_unattached_files,
    mark_stale_runs,
    redispatch_pending_runs,
)
from app.worker import celery_app


async def _with_session(operation: Callable[..., Awaitable[int]]) -> int:
    async with SessionFactory() as db:
        return await operation(db)


@celery_app.task(name="app.redispatch_pending_runs")
def redispatch_pending_runs_task() -> int:
    return asyncio.run(_with_session(redispatch_pending_runs))


@celery_app.task(name="app.mark_stale_runs")
def mark_stale_runs_task() -> int:
    return asyncio.run(_with_session(mark_stale_runs))


@celery_app.task(name="app.clean_expired_sessions")
def clean_expired_sessions_task() -> int:
    return asyncio.run(_with_session(clean_expired_sessions))


@celery_app.task(name="app.clean_unattached_files")
def clean_unattached_files_task() -> int:
    return asyncio.run(_with_session(clean_unattached_files))
