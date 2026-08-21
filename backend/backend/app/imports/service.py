import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.imports.schemas import ImportCreatedResponse, ReprocessRequest
from app.infrastructure.file_storage import FileSizeLimitExceeded, FileStorage
from app.processing.models import IdempotencyRecord, ProcessingRun
from app.worker import celery_app

ALLOWED_EXTENSIONS = {"csv", "json", "tsv", "txt"}
MAX_IMPORT_FILE_BYTES = get_settings().max_import_file_bytes
storage = FileStorage(get_settings().file_storage_root)


async def list_batches(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> list[dict]:
    values = (
        await db.execute(
            select(ImportBatch, DataSource)
            .join(DataSource, DataSource.id == ImportBatch.source_id)
            .order_by(ImportBatch.created_at.desc(), ImportBatch.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_batch_data(batch, source) for batch, source in values]


async def get_batch(db: AsyncSession, batch_id: UUID) -> tuple[ImportBatch, DataSource]:
    value = await db.execute(
        select(ImportBatch, DataSource)
        .join(DataSource, DataSource.id == ImportBatch.source_id)
        .where(ImportBatch.id == batch_id)
    )
    result = value.one_or_none()
    if result is None:
        raise APIError(404, "RESOURCE_NOT_FOUND", "导入批次不存在")
    return result


async def list_rows(
    db: AsyncSession,
    batch_id: UUID,
    *,
    include_raw_payload: bool,
    include_full_text: bool,
    page: int,
    page_size: int,
) -> list[dict]:
    raw_and_normalized = (
        await db.execute(
            select(RawJobPosting, NormalizedJobPosting)
            .outerjoin(
                NormalizedJobPosting,
                and_(
                    NormalizedJobPosting.raw_job_id == RawJobPosting.id,
                    NormalizedJobPosting.is_current.is_(True),
                ),
            )
            .where(RawJobPosting.batch_id == batch_id)
            .order_by(RawJobPosting.row_number, RawJobPosting.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [
        _row_data(
            raw,
            normalized,
            include_raw_payload=include_raw_payload,
            include_full_text=include_full_text,
        )
        for raw, normalized in raw_and_normalized
    ]


async def list_warnings(db: AsyncSession, batch_id: UUID) -> dict:
    rows = (
        await db.scalars(
            select(RawJobPosting)
            .where(RawJobPosting.batch_id == batch_id)
            .order_by(RawJobPosting.row_number)
        )
    ).all()
    normalized = (
        await db.scalars(
            select(NormalizedJobPosting)
            .join(RawJobPosting, NormalizedJobPosting.raw_job_id == RawJobPosting.id)
            .where(
                RawJobPosting.batch_id == batch_id,
                NormalizedJobPosting.is_current.is_(True),
            )
        )
    ).all()
    summary: dict[str, int] = {}
    row_values: list[dict] = []
    normalized_by_raw = {value.raw_job_id: value for value in normalized}
    for raw in rows:
        codes = list(raw.parse_warnings)
        current = normalized_by_raw.get(raw.id)
        if current is not None:
            codes.extend(current.quality_flags)
        for code in dict.fromkeys(codes):
            summary[code] = summary.get(code, 0) + 1
            row_values.append({"row_number": raw.row_number, "code": code})
    return {"summary": summary, "rows": row_values}


async def reprocess_batch(
    db: AsyncSession,
    actor: User,
    batch: ImportBatch,
    payload: ReprocessRequest,
    *,
    request_id: str,
    ip_address: str | None,
) -> ProcessingRun:
    active = await db.scalar(
        select(ProcessingRun).where(
            ProcessingRun.subject_type == "import_batch",
            ProcessingRun.subject_id == batch.id,
            ProcessingRun.status.in_({"pending", "running", "cancel_requested"}),
        )
    )
    if active is not None:
        raise APIError(409, "PROCESSING_ALREADY_RUNNING", "该批次已有任务正在运行")
    previous = await db.scalar(
        select(ProcessingRun)
        .where(
            ProcessingRun.subject_type == "import_batch",
            ProcessingRun.subject_id == batch.id,
        )
        .order_by(ProcessingRun.created_at.desc())
    )
    run = ProcessingRun(
        id=uuid4(),
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=batch.id,
        retry_of_run_id=previous.id if previous is not None else None,
        created_by_user_id=actor.id,
        owner_scope_type="admin_global",
        status="pending",
        pipeline_version=payload.pipeline_version,
        input_snapshot={
            "batch_id": str(batch.id),
            "file_id": str(batch.file_id),
            "source_code": "standard",
            "collected_at": batch.collected_at.isoformat(),
            "reprocess": True,
        },
        result_summary={},
    )
    db.add(run)
    record_audit(
        db,
        action="import.reprocess",
        resource_type="import_batch",
        resource_id=batch.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"run_id": str(run.id), "pipeline_version": payload.pipeline_version},
    )
    await db.commit()
    try:
        result = celery_app.send_task("app.import_market_jd", args=[str(run.id)])
        run.celery_task_id = result.id
        run.enqueued_at = datetime.now(UTC)
    except Exception:
        run.status = "enqueue_failed"
        run.error_code = "TASK_ENQUEUE_FAILED"
        run.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    await db.refresh(run)
    return run


async def archive_batch(
    db: AsyncSession,
    actor: User,
    batch: ImportBatch,
    *,
    request_id: str,
    ip_address: str | None,
) -> ImportBatch:
    if batch.status != "archived":
        active = await db.scalar(
            select(ProcessingRun).where(
                ProcessingRun.subject_type == "import_batch",
                ProcessingRun.subject_id == batch.id,
                ProcessingRun.status.in_({"pending", "running", "cancel_requested"}),
            )
        )
        if active is not None:
            raise APIError(409, "PROCESSING_ALREADY_RUNNING", "该批次已有任务正在运行")
        batch.status = "archived"
        record_audit(
            db,
            action="import.archive",
            resource_type="import_batch",
            resource_id=batch.id,
            actor_user_id=actor.id,
            outcome="success",
            request_id=request_id,
            ip_address=ip_address,
        )
        await db.commit()
        await db.refresh(batch)
    return batch


def _batch_data(batch: ImportBatch, source: DataSource) -> dict:
    return {
        "id": str(batch.id),
        "source_code": source.code,
        "source_display_name": source.display_name,
        "detected_adapter_code": batch.detected_adapter_code,
        "adapter_version": batch.adapter_version,
        "schema_version": batch.schema_version,
        "collected_at": batch.collected_at.isoformat(),
        "status": batch.status,
        "total_rows": batch.total_rows,
        "accepted_rows": batch.accepted_rows,
        "rejected_rows": batch.rejected_rows,
        "warning_rows": batch.warning_rows,
        "batch_summary": batch.batch_summary,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }


def _row_data(
    raw: RawJobPosting,
    normalized: NormalizedJobPosting | None,
    *,
    include_raw_payload: bool,
    include_full_text: bool,
) -> dict:
    raw_data = {
        "id": str(raw.id),
        "row_number": raw.row_number,
        "source_code": raw.source_code,
        "external_id": raw.external_id,
        "source_url": raw.source_url,
        "job_name": raw.job_name,
        "company_name": raw.company_name,
        "salary_text": raw.salary_text,
        "work_area_text": raw.work_area_text,
        "city_text": raw.city_text,
        "education_text": raw.education_text,
        "work_year_text": raw.work_year_text,
        "issue_date_text": raw.issue_date_text,
        "source_tags": raw.source_tags,
        "parse_warnings": raw.parse_warnings,
    }
    if include_raw_payload:
        raw_data["raw_payload"] = raw.raw_payload
    if include_full_text:
        raw_data["raw_text"] = raw.raw_text
    normalized_data = None
    if normalized is not None:
        normalized_data = {
            "id": str(normalized.id),
            "version_no": normalized.version_no,
            "normalization_version": normalized.normalization_version,
            "normalized_title": normalized.normalized_title,
            "company_name": normalized.company_name,
            "city_code": normalized.city_code,
            "city_name": normalized.city_name,
            "work_area": normalized.work_area,
            "salary_min_monthly": normalized.salary_min_monthly,
            "salary_max_monthly": normalized.salary_max_monthly,
            "salary_months": float(normalized.salary_months)
            if normalized.salary_months is not None
            else None,
            "education_level": normalized.education_level,
            "experience_min_months": normalized.experience_min_months,
            "experience_max_months": normalized.experience_max_months,
            "published_at": normalized.published_at.isoformat()
            if normalized.published_at is not None
            else None,
            "quality_score": float(normalized.quality_score),
            "quality_flags": normalized.quality_flags,
        }
        if include_full_text:
            normalized_data["normalized_text"] = normalized.normalized_text
    return {"raw": raw_data, "normalized": normalized_data}


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
