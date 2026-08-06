import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.files.models import StoredFile
from app.imports.adapters import AdapterError, detect_adapter, detect_encoding
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.imports.normalization import normalize_row
from app.infrastructure.database import SessionFactory
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun
from app.worker import celery_app

CHUNK_SIZE = 100
MAX_IMPORT_ROWS = get_settings().max_import_rows
storage = FileStorage(get_settings().file_storage_root)


async def process_market_import(db: AsyncSession, run_id: UUID) -> dict:
    run = await db.get(ProcessingRun, run_id)
    if run is None:
        return {"total_rows": 0, "accepted_rows": 0, "rejected_rows": 0}
    batch = await db.get(ImportBatch, run.subject_id)
    if batch is None:
        return await _fail_run(
            db,
            run,
            None,
            "IMPORT_BATCH_NOT_FOUND",
            "导入批次不存在",
        )
    if run.status in {"completed", "failed", "cancelled"}:
        return dict(run.result_summary)
    if batch.status in {"processed", "partial"}:
        return await _finish_existing(db, run, batch)

    stored_file = await db.get(StoredFile, batch.file_id)
    source = await db.get(DataSource, batch.source_id)
    if stored_file is None or source is None:
        return await _fail_run(
            db,
            run,
            batch,
            "IMPORT_INPUT_NOT_FOUND",
            "导入输入不存在",
        )

    run.status = "running"
    run.current_stage = "parsing"
    run.started_at = datetime.now(UTC)
    run.heartbeat_at = run.started_at
    run.attempt_count += 1
    batch.status = "processing"
    await db.commit()

    try:
        path = storage.resolve(stored_file.storage_key)
        if not path.is_file():
            return await _fail_run(
                db,
                run,
                batch,
                "FILE_CONTENT_MISSING",
                "导入文件内容不存在",
            )
        encoding, text = detect_encoding(path.read_bytes())
        header = text.partition("\n")[0]
        delimiter = "\t" if header.count("\t") else ","
        headers = header.split(delimiter)
        adapter = detect_adapter(headers, source.code)
        rows = list(adapter.iter_rows(text, source_code=source.code))
    except AdapterError as error:
        return await _fail_run(db, run, batch, error.code, str(error))
    except ValueError as error:
        return await _fail_run(db, run, batch, "FILE_CONTENT_INVALID", str(error))
    except OSError:
        return await _fail_run(
            db,
            run,
            batch,
            "FILE_CONTENT_MISSING",
            "导入文件内容不可读取",
        )

    if not rows:
        return await _fail_run(db, run, batch, "IMPORT_EMPTY", "导入文件没有有效数据行")
    if len(rows) > MAX_IMPORT_ROWS:
        return await _fail_run(
            db,
            run,
            batch,
            "IMPORT_ROW_LIMIT_EXCEEDED",
            "导入行数超过限制",
        )

    batch.detected_adapter_code = adapter.code
    batch.adapter_version = source.adapter_version
    batch.total_rows = len(rows)
    run.total_count = len(rows)
    await db.commit()

    accepted = 0
    rejected = 0
    warning_rows = 0
    processed = 0
    for row in rows:
        if await _cancel_requested(db, run.id):
            batch.accepted_rows = accepted
            batch.rejected_rows = rejected
            batch.warning_rows = warning_rows
            batch.status = "partial"
            run.status = "cancelled"
            run.current_stage = "cancelled"
            run.completed_at = datetime.now(UTC)
            result = _result(len(rows), accepted, rejected, warning_rows)
            run.result_summary = result
            await db.commit()
            return result

        if row.is_rejected:
            rejected += 1
            db.add(
                ProcessingError(
                    run_id=run.id,
                    stage="parsing",
                    item_type="row",
                    item_key=str(row.row_number),
                    error_code="ROW_MISSING_JOB_NAME",
                    message="岗位名称不能为空",
                    retryable=False,
                    details={"warnings": row.parse_warnings},
                )
            )
        else:
            normalized = normalize_row(row, batch.collected_at)
            raw_id = uuid4()
            db.add(
                RawJobPosting(
                    id=raw_id,
                    batch_id=batch.id,
                    row_number=row.row_number,
                    source_code=row.source_code,
                    external_id=row.external_id,
                    source_url=row.source_url,
                    job_name=row.job_name,
                    company_name=row.company_name,
                    salary_text=row.salary_text,
                    work_area_text=row.work_area_text,
                    city_text=row.city_text,
                    education_text=row.education_text,
                    work_year_text=row.work_year_text,
                    issue_date_text=row.issue_date_text,
                    raw_text=row.raw_text,
                    source_tags=row.source_tags,
                    raw_payload=row.raw_payload,
                    source_encoding=encoding,
                    parse_warnings=row.parse_warnings,
                    content_hash=_content_hash(row.raw_payload),
                )
            )
            await db.flush()
            db.add(
                NormalizedJobPosting(
                    id=uuid4(),
                    raw_job_id=raw_id,
                    version_no=1,
                    normalization_version="jd_normalization_v1",
                    normalized_title=normalized.normalized_title,
                    company_name=normalized.company_name,
                    city_code=normalized.city_code,
                    city_name=normalized.city_name,
                    work_area=normalized.work_area,
                    salary_min_monthly=normalized.salary_min_monthly,
                    salary_max_monthly=normalized.salary_max_monthly,
                    salary_months=normalized.salary_months,
                    education_level=normalized.education_level,
                    experience_min_months=normalized.experience_min_months,
                    experience_max_months=normalized.experience_max_months,
                    published_at=normalized.published_at,
                    normalized_text=normalized.normalized_text,
                    quality_score=normalized.quality_score,
                    quality_flags=normalized.quality_flags,
                    is_current=True,
                    created_by_run_id=run.id,
                )
            )
            if normalized.quality_flags:
                warning_rows += 1
            else:
                accepted += 1

        processed += 1
        run.processed_count = processed
        run.success_count = accepted + warning_rows
        run.failed_count = rejected
        run.progress_percent = _progress(processed, len(rows))
        run.heartbeat_at = datetime.now(UTC)
        if processed % CHUNK_SIZE == 0:
            await db.commit()

    batch.accepted_rows = accepted
    batch.rejected_rows = rejected
    batch.warning_rows = warning_rows
    batch.status = "partial" if rejected else "processed"
    run.status = "completed"
    run.current_stage = "completed"
    run.processed_count = processed
    run.success_count = accepted + warning_rows
    run.failed_count = rejected
    run.progress_percent = Decimal("100")
    run.heartbeat_at = datetime.now(UTC)
    run.completed_at = run.heartbeat_at
    result = _result(len(rows), accepted, rejected, warning_rows)
    run.result_summary = result
    batch.batch_summary = {
        "adapter_code": adapter.code,
        "adapter_version": source.adapter_version,
        "encoding": encoding,
        "counts": result,
    }
    await db.commit()
    return result


async def _cancel_requested(db: AsyncSession, run_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ProcessingRun.cancel_requested).where(ProcessingRun.id == run_id)
        )
    )


async def _finish_existing(
    db: AsyncSession,
    run: ProcessingRun,
    batch: ImportBatch,
) -> dict:
    result = _result(
        batch.total_rows,
        batch.accepted_rows,
        batch.rejected_rows,
        batch.warning_rows,
    )
    run.status = "completed"
    run.result_summary = result
    run.completed_at = datetime.now(UTC)
    await db.commit()
    return result


async def _fail_run(
    db: AsyncSession,
    run: ProcessingRun,
    batch: ImportBatch | None,
    code: str,
    message: str,
) -> dict:
    run.status = "failed"
    run.error_code = code
    run.error_message = message
    run.current_stage = "failed"
    run.completed_at = datetime.now(UTC)
    result = _result(
        batch.total_rows if batch is not None else 0,
        batch.accepted_rows if batch is not None else 0,
        batch.rejected_rows if batch is not None else 0,
        batch.warning_rows if batch is not None else 0,
    )
    run.result_summary = result
    if batch is not None:
        batch.status = "failed"
    db.add(
        ProcessingError(
            run_id=run.id,
            stage="parsing",
            error_code=code,
            message=message,
            retryable=code in {"FILE_CONTENT_MISSING", "TASK_ENQUEUE_FAILED"},
            details={},
        )
    )
    await db.commit()
    return result


def _result(total: int, accepted: int, rejected: int, warning_rows: int) -> dict:
    return {
        "total_rows": total,
        "accepted_rows": accepted,
        "rejected_rows": rejected,
        "warning_rows": warning_rows,
    }


def _progress(processed: int, total: int) -> Decimal:
    value = Decimal(processed * 100) / Decimal(total)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _content_hash(payload: dict[str, str | None]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


async def _run_with_session(run_id: str) -> dict:
    async with SessionFactory() as db:
        return await process_market_import(db, UUID(run_id))


@celery_app.task(name="app.import_market_jd")
def process_market_import_task(run_id: str) -> dict:
    return asyncio.run(_run_with_session(run_id))
