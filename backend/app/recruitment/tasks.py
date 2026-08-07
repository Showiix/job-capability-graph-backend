import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.mapping import resolve_capability_labels
from app.core.config import get_settings
from app.core.errors import APIError
from app.discovery.mining import normalize_skill_label
from app.files.models import StoredFile
from app.infrastructure.database import SessionFactory
from app.infrastructure.file_storage import FileStorage
from app.llm.responses import create_responses_http_client
from app.processing.models import ProcessingError, ProcessingRun
from app.recruitment.llm import (
    PROMPT_VERSION,
    RecruitmentJDLLMError,
    RecruitmentJDResponsesClient,
)
from app.recruitment.models import (
    CandidateProfile,
    CandidateSkill,
    RecruitmentCandidate,
    RecruitmentProject,
)
from app.recruitment.parsing import extract_jd_text, validate_jd_evidence
from app.recruitment.service import load_active_capability_catalog
from app.resumes.analysis import analyze_resume_document
from app.resumes.llm import ResponsesClient, ResumeLLMError
from app.resumes.parsing import (
    derive_highest_education,
    derive_total_experience_months,
)
from app.resumes.service import map_resume_skills
from app.worker import celery_app

logger = logging.getLogger(__name__)
storage = FileStorage(get_settings().file_storage_root)
STAGES = {
    "extract_text": 10,
    "call_llm": 35,
    "validate_response": 60,
    "validate_evidence": 70,
    "map_capabilities": 85,
    "persist_draft": 95,
    "completed": 100,
}
SAFE_MESSAGES = {
    "RUN_SUPERSEDED": "任务已被更新的 JD 解析替代",
    "FILE_CONTENT_MISSING": "JD 文件内容不存在",
    "RECRUITMENT_JD_INPUT_INVALID": "JD 文件格式或内容无效",
    "RECRUITMENT_JD_TOO_LARGE": "JD 文件或正文超过限制",
    "RECRUITMENT_JD_EVIDENCE_EMPTY": "JD 抽取结果缺少可追溯证据",
    "LLM_NOT_CONFIGURED": "JD 解析服务尚未配置",
    "LLM_TIMEOUT": "JD 解析服务请求超时",
    "LLM_RATE_LIMITED": "JD 解析服务暂时繁忙",
    "LLM_UPSTREAM_ERROR": "JD 解析服务暂时不可用",
    "LLM_REQUEST_REJECTED": "JD 解析请求被上游拒绝",
    "LLM_RESPONSE_REFUSED": "JD 解析服务拒绝处理该内容",
    "LLM_RESPONSE_INCOMPLETE": "JD 解析结果不完整",
    "LLM_RESPONSE_INVALID": "JD 解析结果格式无效",
    "RECRUITMENT_JD_PERSISTENCE_FAILED": "JD 解析结果保存失败",
}
CANDIDATE_SAFE_MESSAGES = {
    "RUN_SUPERSEDED": "任务已被更新的候选解析替代",
    "FILE_CONTENT_MISSING": "候选简历文件内容不存在",
    "RESUME_FILE_TYPE_UNSUPPORTED": "候选简历格式或结构无效",
    "RESUME_DOCUMENT_INVALID": "候选简历格式或结构无效",
    "RESUME_TEXT_EMPTY": "候选简历中没有可提取文字",
    "RESUME_TEXT_TOO_LONG": "候选简历正文超过处理上限",
    "LLM_NOT_CONFIGURED": "候选简历解析服务尚未配置",
    "LLM_TIMEOUT": "候选简历解析服务请求超时",
    "LLM_RATE_LIMITED": "候选简历解析服务暂时繁忙",
    "LLM_UPSTREAM_ERROR": "候选简历解析服务暂时不可用",
    "LLM_REQUEST_REJECTED": "候选简历解析请求被上游拒绝",
    "LLM_RESPONSE_REFUSED": "候选简历解析服务拒绝处理该内容",
    "LLM_RESPONSE_INCOMPLETE": "候选简历解析结果不完整",
    "LLM_RESPONSE_INVALID": "候选简历解析结果格式无效",
    "RESUME_EVIDENCE_EMPTY": "候选简历解析结果缺少可追溯证据",
    "CANDIDATE_PERSISTENCE_FAILED": "候选画像保存失败",
}


class RunFailure(Exception):
    def __init__(self, code: str, stage: str, retryable: bool) -> None:
        self.code = code
        self.stage = stage
        self.retryable = retryable
        super().__init__(code)


async def run_parse_recruitment_jd(
    db: AsyncSession,
    run_id: UUID,
    *,
    responses_client: RecruitmentJDResponsesClient | None = None,
) -> dict:
    stage = "extract_text"
    try:
        run = await db.scalar(
            select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
        )
        if run is None:
            return {}
        project = await db.scalar(
            select(RecruitmentProject)
            .where(RecruitmentProject.id == run.subject_id)
            .with_for_update()
        )
        if project is None:
            return {}
        if run.status == "completed":
            await db.rollback()
            return dict(run.result_summary)
        if run.status in {"failed", "enqueue_failed", "cancelled"}:
            await db.rollback()
            return dict(run.result_summary)
        if project.latest_jd_run_id not in {run.id, run.retry_of_run_id}:
            raise RunFailure("RUN_SUPERSEDED", stage, False)
        project.latest_jd_run_id = run.id
        now = datetime.now(UTC)
        run.status = "running"
        run.current_stage = stage
        run.progress_percent = STAGES[stage]
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        run.attempt_count += 1
        project.jd_parse_status = "processing"
        await db.commit()

        source_text = project.jd_source_text
        if project.jd_source_type == "file":
            stored_file = await db.get(StoredFile, project.jd_file_id)
            if stored_file is None:
                raise RunFailure("FILE_CONTENT_MISSING", stage, False)
            try:
                path = storage.resolve(stored_file.storage_key)
            except ValueError as error:
                raise RunFailure("FILE_CONTENT_MISSING", stage, False) from error
            if not path.is_file():
                raise RunFailure("FILE_CONTENT_MISSING", stage, False)
            extracted = await extract_jd_text(path, stored_file.extension.lower())
            source_text = extracted.text
            project.jd_source_text = source_text
            await db.commit()
        if not source_text:
            raise RunFailure("RECRUITMENT_JD_INPUT_INVALID", stage, False)

        stage = "call_llm"
        await _set_stage(db, run, stage)
        settings = get_settings()
        if not all(
            (settings.llm_responses_url, settings.llm_api_key, settings.llm_model)
        ):
            raise RunFailure("LLM_NOT_CONFIGURED", stage, True)
        request = {
            "url": str(settings.llm_responses_url),
            "api_key": settings.llm_api_key.get_secret_value(),
            "model": settings.llm_model,
            "source_text": source_text,
            "processing_run_id": run.id,
        }
        if responses_client is None:
            async with create_responses_http_client() as http:
                llm_result = await RecruitmentJDResponsesClient(http=http).parse_jd(
                    **request
                )
        else:
            llm_result = await responses_client.parse_jd(**request)

        stage = "validate_response"
        await _set_stage(db, run, stage)
        stage = "validate_evidence"
        await _set_stage(db, run, stage)
        validated = validate_jd_evidence(llm_result.payload, source_text=source_text)

        stage = "map_capabilities"
        await _set_stage(db, run, stage)
        resolution = await resolve_capability_labels(
            db,
            [item["name"] for item in validated.skills],
        )
        draft = await _build_draft(db, run.id, validated, resolution, llm_result)

        stage = "persist_draft"
        await _set_stage(db, run, stage)
        project = await db.get(RecruitmentProject, project.id)
        run = await db.get(ProcessingRun, run.id)
        project.jd_draft_payload = draft
        project.jd_parse_status = "ready"
        project.latest_jd_run_id = run.id
        now = datetime.now(UTC)
        run.status = "completed"
        run.current_stage = "completed"
        run.processed_count = 1
        run.success_count = 1
        run.failed_count = 0
        run.progress_percent = Decimal("100")
        run.heartbeat_at = now
        run.completed_at = now
        run.error_code = None
        run.error_message = None
        result = {
            "project_id": str(project.id),
            "mapped_requirement_count": len(draft["requirements"]),
            "unmapped_skill_count": len(draft["unmapped_skills"]),
            "validation_warning_count": len(draft["validation_warnings"]),
            "result_url": f"/api/v1/recruitment-projects/{project.id}",
        }
        run.result_summary = result
        await db.commit()
        return result
    except APIError as error:
        failure = RunFailure(error.code, stage, False)
        cause = error
    except RecruitmentJDLLMError as error:
        failure = RunFailure(error.code, error.stage or stage, error.retryable)
        cause = error
    except RunFailure as error:
        failure = error
        cause = error
    except SQLAlchemyError as error:
        failure = RunFailure(
            "RECRUITMENT_JD_PERSISTENCE_FAILED",
            stage,
            True,
        )
        cause = error

    await db.rollback()
    return await _fail_run(db, run_id, failure=failure, cause=cause)


async def _build_draft(db, run_id, validated, resolution, llm_result) -> dict:
    by_name = {item.normalized_label: item for item in resolution.resolutions}
    capability_ids = [
        item.capability_id
        for item in resolution.resolutions
        if item.capability_id is not None
    ]
    catalog = await load_active_capability_catalog(db, capability_ids)
    requirements = []
    unmapped = []
    seen_capabilities = set()
    seen_unmapped = set()
    for skill in validated.skills:
        normalized_name = normalize_skill_label(skill["name"])
        mapped = by_name[normalized_name]
        if mapped.capability_id is not None:
            if mapped.capability_id in seen_capabilities:
                continue
            seen_capabilities.add(mapped.capability_id)
            requirements.append(
                {
                    **catalog[mapped.capability_id],
                    "raw_name": skill["name"],
                    "requirement_type": skill["requirement_type"],
                    "importance": skill["importance"],
                    "mapping_method": mapped.mapping_method,
                    "evidence_quote": skill["evidence_quote"],
                    "confidence": skill["confidence"],
                }
            )
        elif normalized_name not in seen_unmapped:
            seen_unmapped.add(normalized_name)
            unmapped.append(
                {
                    "raw_name": skill["name"],
                    "normalized_name": normalized_name,
                    "requirement_type": skill["requirement_type"],
                    "evidence_quote": skill["evidence_quote"],
                    "confidence": skill["confidence"],
                }
            )
    return {
        "schema_version": "recruitment_requirements_v1",
        "source_run_id": str(run_id),
        "job_title": validated.job_title,
        "summary": validated.summary,
        "responsibilities": [item["text"] for item in validated.responsibilities],
        "minimum_education_level": validated.minimum_education_level,
        "recommended_experience_months": validated.recommended_experience_months,
        "requirements": requirements,
        "unmapped_skills": unmapped,
        "validation_warnings": [
            *validated.warnings,
            *resolution.warnings,
        ],
        "extractor_metadata": {
            "provider": "responses_api",
            "prompt_version": PROMPT_VERSION,
            "response_id": llm_result.response_id,
            "returned_model": llm_result.returned_model,
            "response_sha256": llm_result.response_sha256,
        },
    }


async def _set_stage(db: AsyncSession, run: ProcessingRun, stage: str) -> None:
    run.current_stage = stage
    run.progress_percent = STAGES[stage]
    run.heartbeat_at = datetime.now(UTC)
    await db.commit()


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
    project = await db.get(RecruitmentProject, run.subject_id)
    now = datetime.now(UTC)
    message = SAFE_MESSAGES.get(failure.code, "JD 解析失败")
    run.status = "failed"
    run.current_stage = failure.stage
    run.failed_count = 1
    run.processed_count = 1
    run.progress_percent = Decimal("100")
    run.heartbeat_at = now
    run.completed_at = now
    run.error_code = failure.code
    run.error_message = message
    if project is not None and project.latest_jd_run_id == run.id:
        project.jd_parse_status = "failed"
    db.add(
        ProcessingError(
            run_id=run.id,
            stage=failure.stage,
            item_type="recruitment_project",
            item_id=project.id if project is not None else None,
            error_code=failure.code,
            message=message,
            retryable=failure.retryable,
            details={},
        )
    )
    logger.warning(
        "recruitment JD processing failed: run_id=%s stage=%s code=%s error=%s",
        run.id,
        failure.stage,
        failure.code,
        type(cause).__name__,
    )
    await db.commit()
    return {}


async def _run_with_session(run_id: UUID) -> None:
    async with SessionFactory() as db:
        await run_parse_recruitment_jd(db, run_id)


@celery_app.task(name="app.parse_recruitment_jd")
def parse_recruitment_jd_task(run_id: str) -> None:
    asyncio.run(_run_with_session(UUID(run_id)))


async def run_parse_recruitment_candidates(
    db: AsyncSession,
    run_id: UUID,
    *,
    responses_client: ResponsesClient | None = None,
) -> dict:
    run = await db.scalar(
        select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update()
    )
    if run is None:
        return {}
    if run.status == "completed":
        await db.rollback()
        return dict(run.result_summary)
    if run.status in {"failed", "enqueue_failed", "cancelled"}:
        await db.rollback()
        return dict(run.result_summary)
    project = await db.get(RecruitmentProject, run.subject_id)
    if project is None:
        await db.rollback()
        return {}

    candidate_ids = sorted(UUID(value) for value in run.input_snapshot["candidate_ids"])
    if run.cancel_requested or run.status == "cancel_requested":
        return await _cancel_candidate_run(db, run, [], [])
    now = datetime.now(UTC)
    run.status = "running"
    run.current_stage = "parse_candidates"
    run.started_at = run.started_at or now
    run.heartbeat_at = now
    run.attempt_count += 1
    run.total_count = len(candidate_ids)
    await db.commit()

    success_ids: list[str] = []
    failed_candidates: list[dict] = []
    for candidate_id in candidate_ids:
        current = await db.get(ProcessingRun, run.id)
        await db.refresh(current)
        if current.cancel_requested or current.status == "cancel_requested":
            return await _cancel_candidate_run(
                db,
                current,
                success_ids,
                failed_candidates,
            )
        outcome = await _process_candidate(
            db,
            current,
            project.id,
            candidate_id,
            responses_client=responses_client,
        )
        if outcome["ok"]:
            success_ids.append(str(candidate_id))
        else:
            failed_candidates.append(
                {
                    "candidate_id": str(candidate_id),
                    "error_code": outcome["error_code"],
                }
            )
        processed = len(success_ids) + len(failed_candidates)
        current = await db.get(ProcessingRun, run.id)
        current.processed_count = processed
        current.success_count = len(success_ids)
        current.failed_count = len(failed_candidates)
        current.progress_percent = (
            Decimal(processed * 100) / Decimal(len(candidate_ids))
        ).quantize(Decimal("0.01"))
        current.heartbeat_at = datetime.now(UTC)
        await db.commit()

    run = await db.get(ProcessingRun, run.id)
    result = _candidate_batch_result(project.id, success_ids, failed_candidates)
    run.result_summary = result
    run.current_stage = "completed"
    run.progress_percent = Decimal("100")
    run.completed_at = datetime.now(UTC)
    run.heartbeat_at = run.completed_at
    if failed_candidates:
        run.status = "failed"
        run.error_code = "CANDIDATE_BATCH_PARTIAL_FAILURE"
        run.error_message = "部分候选简历解析失败"
    else:
        run.status = "completed"
        run.error_code = None
        run.error_message = None
    await db.commit()
    return result


async def _process_candidate(
    db: AsyncSession,
    run: ProcessingRun,
    project_id: UUID,
    candidate_id: UUID,
    *,
    responses_client: ResponsesClient | None,
) -> dict:
    stage = "extract_text"
    try:
        candidate = await db.scalar(
            select(RecruitmentCandidate)
            .where(
                RecruitmentCandidate.id == candidate_id,
                RecruitmentCandidate.project_id == project_id,
            )
            .with_for_update()
        )
        if candidate is None:
            raise RunFailure("RUN_SUPERSEDED", stage, False)
        if candidate.latest_run_id not in {run.id, run.retry_of_run_id}:
            raise RunFailure("RUN_SUPERSEDED", stage, False)
        existing = await db.scalar(
            select(CandidateProfile).where(
                CandidateProfile.candidate_id == candidate.id
            )
        )
        if existing is not None:
            candidate.parse_status = "ready"
            candidate.latest_run_id = run.id
            await db.commit()
            return {"ok": True}

        candidate.parse_status = "processing"
        candidate.latest_run_id = run.id
        stored_file = await db.get(StoredFile, candidate.file_id)
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
        analysis = await analyze_resume_document(
            path,
            filename=stored_file.original_name,
            media_type=stored_file.media_type,
            processing_run_id=run.id,
            responses_client=responses_client,
            settings=settings,
        )
        stage = "map_capabilities"
        mapping = await map_resume_skills(db, analysis.validated.skills)
        total_experience, date_warnings = derive_total_experience_months(
            analysis.validated.experiences,
            current_month=datetime.now(UTC).date().replace(day=1),
        )
        validation_warnings = [
            *analysis.validated.warnings,
            *mapping.warnings,
            *date_warnings,
        ]
        candidate = await db.scalar(
            select(RecruitmentCandidate)
            .where(RecruitmentCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate.latest_run_id != run.id:
            raise RunFailure("RUN_SUPERSEDED", stage, False)
        profile = CandidateProfile(
            candidate_id=candidate.id,
            extraction_version=run.pipeline_version,
            extracted_text=analysis.extracted_text,
            text_extraction_method=analysis.extraction_method,
            highest_education_level=derive_highest_education(
                analysis.validated.educations
            ),
            total_experience_months=total_experience,
            structured_payload={
                "schema_version": "resume_parse_v1",
                "document_language": analysis.validated.document_language,
                "summary": analysis.validated.summary,
                "educations": analysis.validated.educations,
                "experiences": analysis.validated.experiences,
                "projects": analysis.validated.projects,
                "validation_warnings": validation_warnings,
                "source_sha256": analysis.source_sha256,
                "llm_metadata": {
                    "response_id": analysis.llm_result.response_id,
                    "requested_model": analysis.requested_model,
                    "returned_model": analysis.llm_result.returned_model,
                    "status": analysis.llm_result.status,
                    "input_tokens": analysis.llm_result.usage.get("input_tokens"),
                    "output_tokens": analysis.llm_result.usage.get("output_tokens"),
                    "total_tokens": analysis.llm_result.usage.get("total_tokens"),
                    "provider_attempts": analysis.llm_result.provider_attempts,
                    "prompt_version": "resume_parse_v1",
                    "response_sha256": analysis.llm_result.response_sha256,
                },
            },
            created_by_run_id=run.id,
        )
        db.add(profile)
        await db.flush()
        db.add_all(
            [
                CandidateSkill(
                    profile_id=profile.id,
                    capability_id=skill.capability_id,
                    raw_name=skill.raw_name,
                    normalized_name=skill.normalized_name,
                    proficiency=skill.proficiency,
                    explicit_experience_months=skill.explicit_experience_months,
                    evidence_strength=skill.evidence_strength,
                    evidence_quote=skill.evidence_quote,
                    evidence_start=skill.evidence_start,
                    evidence_end=skill.evidence_end,
                    mapping_method=skill.mapping_method,
                    mapping_status=skill.mapping_status,
                    confidence=Decimal(str(skill.confidence)),
                )
                for skill in mapping.skills
            ]
        )
        candidate.parse_status = "ready"
        await db.commit()
        return {"ok": True}
    except APIError as error:
        failure = RunFailure(
            error.code,
            stage,
            error.code in {"LLM_NOT_CONFIGURED", "RESUME_EVIDENCE_EMPTY"},
        )
        cause = error
    except ResumeLLMError as error:
        failure = RunFailure(error.code, error.stage or stage, error.retryable)
        cause = error
    except RunFailure as error:
        failure = error
        cause = error
    except SQLAlchemyError as error:
        failure = RunFailure("CANDIDATE_PERSISTENCE_FAILED", stage, True)
        cause = error

    await db.rollback()
    return await _fail_candidate(
        db,
        run,
        project_id,
        candidate_id,
        failure=failure,
        cause=cause,
    )


async def _fail_candidate(
    db: AsyncSession,
    run: ProcessingRun,
    project_id: UUID,
    candidate_id: UUID,
    *,
    failure: RunFailure,
    cause: Exception,
) -> dict:
    candidate = await db.scalar(
        select(RecruitmentCandidate).where(
            RecruitmentCandidate.id == candidate_id,
            RecruitmentCandidate.project_id == project_id,
        )
    )
    if candidate is not None and candidate.latest_run_id in {
        run.id,
        run.retry_of_run_id,
    }:
        candidate.parse_status = "failed"
        candidate.latest_run_id = run.id
    message = CANDIDATE_SAFE_MESSAGES.get(failure.code, "候选简历解析失败")
    db.add(
        ProcessingError(
            run_id=run.id,
            stage=failure.stage,
            item_type="recruitment_candidate",
            item_id=candidate_id,
            error_code=failure.code,
            message=message,
            retryable=failure.retryable,
            details={},
        )
    )
    logger.warning(
        "candidate processing failed: run_id=%s candidate_id=%s code=%s error=%s",
        run.id,
        candidate_id,
        failure.code,
        type(cause).__name__,
    )
    await db.commit()
    return {"ok": False, "error_code": failure.code}


async def _cancel_candidate_run(
    db: AsyncSession,
    run: ProcessingRun,
    success_ids: list[str],
    failed_candidates: list[dict],
) -> dict:
    result = _candidate_batch_result(
        run.subject_id,
        success_ids,
        failed_candidates,
    )
    now = datetime.now(UTC)
    run.status = "cancelled"
    run.current_stage = "cancelled"
    run.completed_at = now
    run.heartbeat_at = now
    run.result_summary = result
    await db.commit()
    return result


def _candidate_batch_result(
    project_id: UUID,
    success_ids: list[str],
    failed_candidates: list[dict],
) -> dict:
    return {
        "project_id": str(project_id),
        "success_candidate_ids": sorted(success_ids),
        "failed_candidates": sorted(
            failed_candidates,
            key=lambda item: item["candidate_id"],
        ),
        "result_url": f"/api/v1/recruitment-projects/{project_id}/candidates",
    }


async def _run_candidates_with_session(run_id: UUID) -> None:
    async with SessionFactory() as db:
        await run_parse_recruitment_candidates(db, run_id)


@celery_app.task(name="app.parse_recruitment_candidates")
def parse_recruitment_candidates_task(run_id: str) -> None:
    asyncio.run(_run_candidates_with_session(UUID(run_id)))
