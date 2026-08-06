import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.imports.models import DataSource, ImportBatch
from app.imports.schemas import ImportCreatedResponse
from app.infrastructure.file_storage import FileSizeLimitExceeded, FileStorage
from app.processing.models import IdempotencyRecord, ProcessingRun
from app.worker import celery_app

ALLOWED_EXTENSIONS = {"csv", "json", "tsv", "txt"}
MAX_IMPORT_FILE_BYTES = get_settings().max_import_file_bytes
storage = FileStorage(get_settings().file_storage_root)


async def create_import(
    db: AsyncSession,
    actor: User,
    upload: UploadFile,
    *,
    source_code: str,
    collected_at: datetime,
    source_format: str,
    schema_version: str | None,
    idempotency_key: str | None,
    request_id: str,
    ip_address: str | None,
) -> ImportCreatedResponse:
    source = await db.scalar(
        select(DataSource).where(
            DataSource.code == source_code.strip().lower(),
            DataSource.is_enabled.is_(True),
        )
    )
    if source is None:
        raise APIError(422, "IMPORT_SOURCE_UNSUPPORTED", "不支持的数据来源")

    extension = Path(upload.filename or "").suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise APIError(422, "IMPORT_FILE_TYPE_UNSUPPORTED", "文件格式不受支持")
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=UTC)

    file_id = uuid4()
    batch_id = uuid4()
    run_id = uuid4()
    storage_key = f"market-jd/{file_id}.{extension}"
    try:
        size_bytes, sha256 = await storage.save_stream(
            upload,
            storage_key,
            MAX_IMPORT_FILE_BYTES,
        )
    except FileSizeLimitExceeded:
        raise APIError(413, "IMPORT_FILE_TOO_LARGE", "导入文件超过大小限制") from None
    except ValueError as error:
        if str(error) == "empty file":
            raise APIError(422, "IMPORT_EMPTY_FILE", "导入文件不能为空") from None
        raise

    request_hash = _request_hash(
        sha256,
        source_code=source.code,
        collected_at=collected_at,
        source_format=source_format,
        schema_version=schema_version,
    )
    if idempotency_key:
        existing = await db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == actor.id,
                IdempotencyRecord.endpoint_key == "imports.create",
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            _remove_file(storage_key)
            if existing.request_hash != request_hash:
                raise APIError(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "幂等键已用于其他请求",
                )
            if existing.response_body:
                return ImportCreatedResponse.model_validate(existing.response_body)
            raise APIError(409, "REQUEST_IN_PROGRESS", "相同请求正在处理")

    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=actor.id,
        original_name=upload.filename or f"import.{extension}",
        storage_key=storage_key,
        media_type=upload.content_type or "application/octet-stream",
        extension=extension,
        size_bytes=size_bytes,
        sha256=sha256,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=batch_id,
        source_id=source.id,
        file_id=file_id,
        uploaded_by_user_id=actor.id,
        schema_version=schema_version,
        collected_at=collected_at,
        status="uploaded",
        batch_summary={"source_format": source_format},
    )
    run = ProcessingRun(
        id=run_id,
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=batch_id,
        created_by_user_id=actor.id,
        owner_scope_type="admin_global",
        status="pending",
        pipeline_version=schema_version or source.adapter_code,
        input_snapshot={
            "batch_id": str(batch_id),
            "file_id": str(file_id),
            "source_code": source.code,
            "adapter_code": source.adapter_code,
            "adapter_version": source.adapter_version,
            "collected_at": collected_at.isoformat(),
        },
        result_summary={},
    )
    response = ImportCreatedResponse(
        resource_id=batch_id,
        run_id=run_id,
        status="processing",
        poll_url=f"/api/v1/processing-runs/{run_id}",
    )
    idempotency = None
    if idempotency_key:
        idempotency = IdempotencyRecord(
            user_id=actor.id,
            endpoint_key="imports.create",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=202,
            response_body=response.model_dump(mode="json"),
            resource_type="import_batch",
            resource_id=batch_id,
            state="completed",
        )
        db.add(idempotency)
    db.add_all([stored_file, batch, run])
    record_audit(
        db,
        action="import.create",
        resource_type="import_batch",
        resource_id=batch_id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"source_code": source.code, "file_id": str(file_id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _remove_file(storage_key)
        if idempotency_key:
            existing = await db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == actor.id,
                    IdempotencyRecord.endpoint_key == "imports.create",
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None and existing.request_hash == request_hash:
                return ImportCreatedResponse.model_validate(existing.response_body)
        raise

    try:
        result = celery_app.send_task("app.import_market_jd", args=[str(run_id)])
        run.celery_task_id = result.id
        run.enqueued_at = datetime.now(UTC)
    except Exception:
        run.status = "enqueue_failed"
        run.error_code = "TASK_ENQUEUE_FAILED"
        run.error_message = "任务暂时无法投递，可稍后重试"
    if idempotency is not None:
        idempotency.response_body = response.model_dump(mode="json")
    await db.commit()
    return response


def _request_hash(
    file_sha256: str,
    *,
    source_code: str,
    collected_at: datetime,
    source_format: str,
    schema_version: str | None,
) -> str:
    payload = {
        "file_sha256": file_sha256,
        "source_code": source_code,
        "collected_at": collected_at.isoformat(),
        "source_format": source_format,
        "schema_version": schema_version,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _remove_file(storage_key: str) -> None:
    try:
        storage.resolve(storage_key).unlink(missing_ok=True)
    except ValueError:
        return
