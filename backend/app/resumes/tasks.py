import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.infrastructure.database import SessionFactory
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun
from app.resumes.analysis import analyze_resume_document
from app.resumes.llm import ResponsesClient, ResumeLLMError
from app.resumes.models import Resume, ResumeProfile
from app.resumes.service import (
    complete_run_for_profile,
    get_existing_extracted_profile,
    map_resume_skills,
    persist_extracted_profile,
)
from app.worker import celery_app

logger = logging.getLogger(__name__)
storage = FileStorage(get_settings().file_storage_root)
PIPELINE_VERSION = "resume_parse_v1"
STAGES = {
    "extract_text": 10,
    "redact_text": 20,
    "call_llm": 40,
    "validate_response": 65,
    "validate_evidence": 75,
    "map_capabilities": 85,
    "persist_profile": 95,
    "completed": 100,
}
SAFE_MESSAGES = {
    "FILE_CONTENT_MISSING": "简历文件内容不存在",
    "RESUME_DOCUMENT_INVALID": "简历文档无法解析",
    "RESUME_TEXT_EMPTY": "简历中没有可提取文字",
    "RESUME_TEXT_TOO_LONG": "简历正文超过处理上限",
    "LLM_NOT_CONFIGURED": "简历解析服务尚未配置",
    "LLM_TIMEOUT": "简历解析服务请求超时",
    "LLM_RATE_LIMITED": "简历解析服务暂时繁忙",
    "LLM_UPSTREAM_ERROR": "简历解析服务暂时不可用",
    "LLM_REQUEST_REJECTED": "简历解析请求被上游拒绝",
    "LLM_RESPONSE_REFUSED": "简历解析服务拒绝处理该内容",
    "LLM_RESPONSE_INCOMPLETE": "简历解析结果不完整",
    "LLM_RESPONSE_INVALID": "简历解析结果格式无效",
    "RESUME_EVIDENCE_EMPTY": "解析结果无法定位到简历原文",
    "RESUME_PERSISTENCE_FAILED": "简历画像保存失败",
}


class RunFailure(Exception):
    def __init__(self, code: str, stage: str, retryable: bool) -> None:
        self.code = code
        self.stage = stage
        self.retryable = retryable
        super().__init__(code)


async def run_parse_resume(
    db: AsyncSession,
    run_id: UUID,
    *,
    responses_client: ResponsesClient | None = None,
) -> dict:
    stage = "extract_text"
    run = None
    resume = None
    try:
        run = await db.scalar(
            select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
        )
        if run is None:
            return {}
        resume = await db.scalar(
            select(Resume).where(Resume.id == run.subject_id).with_for_update()
        )
        if resume is None:
            return {}
        if run.status == "completed":
            await db.rollback()
            return dict(run.result_summary)
        if run.status in {"failed", "enqueue_failed"}:
            await db.rollback()
            return dict(run.result_summary)
        if run.status == "cancelled" or run.cancel_requested:
            return await _cancel_run(db, run, resume)

        existing = await get_existing_extracted_profile(
            db,
            resume.id,
            run.pipeline_version,
        )
        if existing is not None:
            return await complete_run_for_profile(
                db,
                resume=resume,
                run=run,
                profile=existing,
            )

        now = datetime.now(UTC)
        run.status = "running"
        run.current_stage = stage
        run.progress_percent = STAGES[stage]
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.attempt_count += 1
        resume.parse_status = "processing"
        resume.latest_run_id = run.id
        await db.commit()

        stored_file = await db.get(StoredFile, resume.file_id)
        await db.commit()
        if stored_file is None:
            raise RunFailure("FILE_CONTENT_MISSING", stage, False)
        try:
            path = storage.resolve(stored_file.storage_key)
        except ValueError as error:
            raise RunFailure("FILE_CONTENT_MISSING", stage, False) from error
        if not path.is_file():
            raise RunFailure("FILE_CONTENT_MISSING", stage, False)
        settings = get_settings()

        async def update_stage(value: str) -> None:
            nonlocal stage
            stage = value
            current = await db.get(ProcessingRun, run.id)
            await _set_stage(db, current, value)

        analysis = await analyze_resume_document(
            path,
            filename=stored_file.original_name,
            media_type=stored_file.media_type,
            processing_run_id=run.id,
            responses_client=responses_client,
            settings=settings,
            on_stage=update_stage,
        )

        refreshed = await _refresh_run(db, run.id)
        if refreshed.cancel_requested or refreshed.status == "cancel_requested":
            return await _cancel_run(db, refreshed, resume)

        stage = "map_capabilities"
        await _set_stage(db, refreshed, stage)
        mapping = await map_resume_skills(db, analysis.validated.skills)
        await db.commit()

        stage = "persist_profile"
        await _set_stage(db, refreshed, stage)
        profile = await persist_extracted_profile(
            db,
            resume=resume,
            run=refreshed,
            extracted_text=analysis.extracted_text,
            extraction_method=analysis.extraction_method,
            validated=analysis.validated,
            mapping=mapping,
            llm_result=analysis.llm_result,
            requested_model=analysis.requested_model,
            current_month=datetime.now(UTC).date().replace(day=1),
        )
        return dict(refreshed.result_summary) | {"profile_id": str(profile.id)}
    except APIError as error:
        failure = RunFailure(
            error.code,
            stage,
            error.code in {"LLM_NOT_CONFIGURED", "RESUME_EVIDENCE_EMPTY"},
        )
        cause = error
    except ResumeLLMError as error:
        failure = RunFailure(
            error.code,
            "validate_response" if error.stage == "validate_response" else stage,
            True,
        )
        cause = error
    except RunFailure as error:
        failure = error
        cause = error
    except SQLAlchemyError as error:
        failure = RunFailure("RESUME_PERSISTENCE_FAILED", stage, True)
        cause = error

    await db.rollback()
    return await _fail_run(
        db,
        run_id,
        failure=failure,
        cause=cause,
    )


async def _set_stage(
    db: AsyncSession,
    run: ProcessingRun,
    stage: str,
) -> None:
    run.current_stage = stage
    run.progress_percent = STAGES[stage]
    run.heartbeat_at = datetime.now(UTC)
    await db.commit()


async def _refresh_run(db: AsyncSession, run_id: UUID) -> ProcessingRun:
    run = await db.get(ProcessingRun, run_id)
    await db.refresh(run)
    await db.commit()
    return run


async def _cancel_run(
    db: AsyncSession,
    run: ProcessingRun,
    resume: Resume,
) -> dict:
    has_profile = bool(
        await db.scalar(
            select(ResumeProfile.id)
            .where(ResumeProfile.resume_id == resume.id)
            .limit(1)
        )
    )
    now = datetime.now(UTC)
    run.status = "cancelled"
    run.current_stage = "cancelled"
    run.completed_at = now
    run.heartbeat_at = now
    resume.parse_status = "ready" if has_profile else "uploaded"
    resume.latest_run_id = run.id
    await db.commit()
    return dict(run.result_summary)


async def _fail_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    failure: RunFailure,
    cause: Exception,
) -> dict:
    run = await db.get(ProcessingRun, run_id)
    if run is None:
        return {}
    resume = await db.get(Resume, run.subject_id)
    message = SAFE_MESSAGES.get(failure.code, "简历处理失败")
    now = datetime.now(UTC)
    run.status = "failed"
    run.current_stage = failure.stage
    run.processed_count = 1
    run.success_count = 0
    run.failed_count = 1
    run.heartbeat_at = now
    run.completed_at = now
    run.error_code = failure.code
    run.error_message = message
    if resume is not None:
        resume.parse_status = "failed"
        resume.latest_run_id = run.id
    db.add(
        ProcessingError(
            run_id=run.id,
            stage=failure.stage,
            error_code=failure.code,
            message=message,
            retryable=failure.retryable,
            details={},
        )
    )
    logger.warning(
        "resume processing failed: run_id=%s stage=%s code=%s error=%s",
        run.id,
        failure.stage,
        failure.code,
        type(cause).__name__,
    )
    await db.commit()
    return {}


async def _run_with_session(run_id: UUID) -> None:
    async with SessionFactory() as db:
        await run_parse_resume(db, run_id)


@celery_app.task(name="app.parse_resume")
def parse_resume_task(run_id: str) -> None:
    asyncio.run(_run_with_session(UUID(run_id)))
