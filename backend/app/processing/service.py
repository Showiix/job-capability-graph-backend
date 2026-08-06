import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import AuthSession, User
from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun
from app.worker import celery_app

logger = logging.getLogger(__name__)


def visible_run_predicate(actor: User):
    if actor.role == "admin":
        return true()
    return and_(
        ProcessingRun.owner_scope_type == "user",
        ProcessingRun.owner_scope_id == actor.id,
    )


async def get_visible_run(
    db: AsyncSession,
    run_id: UUID,
    actor: User,
) -> ProcessingRun:
    run = await db.scalar(
        select(ProcessingRun).where(
            ProcessingRun.id == run_id,
            visible_run_predicate(actor),
        )
    )
    if run is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "任务不存在")
    return run


async def cancel_run(
    db: AsyncSession,
    run: ProcessingRun,
    actor: User,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> tuple[ProcessingRun, int]:
    if run.status == "pending":
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        status_code = 200
    elif run.status in {"running", "waiting_review"}:
        run.status = "cancel_requested"
        run.cancel_requested = True
        status_code = 202
    else:
        status_code = 200
    record_audit(
        db,
        action="processing_run.cancel",
        resource_type="processing_run",
        resource_id=run.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"status": run.status},
    )
    await db.commit()
    await db.refresh(run)
    return run, status_code


async def retry_run(
    db: AsyncSession,
    old: ProcessingRun,
    actor: User,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> ProcessingRun:
    if old.status not in {"failed", "enqueue_failed"}:
        raise APIError(409, "RUN_NOT_RETRYABLE", "当前任务状态不能重试")
    new = ProcessingRun(
        run_type=old.run_type,
        subject_type=old.subject_type,
        subject_id=old.subject_id,
        retry_of_run_id=old.id,
        created_by_user_id=actor.id,
        owner_scope_type=old.owner_scope_type,
        owner_scope_id=old.owner_scope_id,
        status="pending",
        pipeline_version=old.pipeline_version,
        max_attempts=old.max_attempts,
        input_snapshot=dict(old.input_snapshot),
        result_summary={},
    )
    db.add(new)
    await db.flush()
    record_audit(
        db,
        action="processing_run.retry",
        resource_type="processing_run",
        resource_id=new.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"retry_of_run_id": str(old.id)},
    )
    await db.commit()
    try:
        result = celery_app.send_task(f"app.{new.run_type}", args=[str(new.id)])
        new.celery_task_id = result.id
        new.enqueued_at = datetime.now(UTC)
    except Exception as error:
        logger.error(
            "processing run enqueue failed: %s request_id=%s",
            type(error).__name__,
            request_id or "-",
        )
        new.status = "enqueue_failed"
        new.error_code = "TASK_ENQUEUE_FAILED"
        new.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    await db.refresh(new)
    return new


async def redispatch_pending_runs(db: AsyncSession) -> int:
    runs = (
        await db.scalars(
            select(ProcessingRun).where(
                ProcessingRun.status.in_({"pending", "enqueue_failed"}),
                ProcessingRun.celery_task_id.is_(None),
            )
        )
    ).all()
    dispatched = 0
    for run in runs:
        try:
            result = celery_app.send_task(f"app.{run.run_type}", args=[str(run.id)])
            run.celery_task_id = result.id
            run.enqueued_at = datetime.now(UTC)
            run.status = "pending"
            run.error_code = None
            run.error_message = None
            dispatched += 1
        except Exception as error:
            run.status = "enqueue_failed"
            run.error_code = "TASK_ENQUEUE_FAILED"
            run.error_message = "任务暂时无法投递，可稍后重试"
            logger.error("run redispatch failed: %s", type(error).__name__)
    await db.commit()
    return dispatched


async def mark_stale_runs(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    runs = (
        await db.scalars(
            select(ProcessingRun).where(
                ProcessingRun.status == "running",
                ProcessingRun.heartbeat_at < now - timedelta(minutes=5),
            )
        )
    ).all()
    for run in runs:
        run.status = "failed"
        run.error_code = "WORKER_HEARTBEAT_STALE"
        run.error_message = "任务执行进程失去心跳，可重试"
        run.completed_at = now
        db.add(
            ProcessingError(
                run_id=run.id,
                stage=run.current_stage or "unknown",
                error_code="WORKER_HEARTBEAT_STALE",
                message="任务执行进程失去心跳",
                retryable=True,
            )
        )
    await db.commit()
    return len(runs)


async def clean_expired_sessions(db: AsyncSession) -> int:
    result = await db.execute(
        delete(AuthSession).where(
            or_(
                AuthSession.expires_at < datetime.now(UTC),
                AuthSession.revoked_at.is_not(None),
            )
        )
    )
    await db.commit()
    return result.rowcount or 0


async def clean_unattached_files(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    files = (
        await db.scalars(
            select(StoredFile).where(
                StoredFile.status == "uploaded",
                StoredFile.expires_at < now,
            )
        )
    ).all()
    storage = FileStorage(get_settings().file_storage_root)
    cleaned = 0
    for stored_file in files:
        try:
            path = storage.resolve(stored_file.storage_key)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            await db.delete(stored_file)
            cleaned += 1
        except Exception as error:
            logger.error(
                "expired file cleanup failed: file_id=%s error=%s",
                stored_file.id,
                type(error).__name__,
            )
    await db.commit()
    return cleaned
