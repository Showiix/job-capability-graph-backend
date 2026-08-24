import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithm.lgf import LGFClient, LGFMatchRequest
from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.models import Capability, Domain
from app.core.config import get_settings
from app.core.errors import APIError
from app.discovery.mining import normalize_skill_label
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileSizeLimitExceeded, FileStorage
from app.matching.scoring import (
    WEIGHT_VERSION,
    MatchCatalogInconsistent,
    weight_snapshot,
)
from app.processing.models import IdempotencyRecord, ProcessingRun
from app.recruitment.matching import (
    RecruitmentCandidateMatchInput,
    candidate_snapshot,
    canonical_candidate_selection,
    profile_input,
    rank_candidate_matches,
    requirement_inputs,
    sha256_json,
)
from app.recruitment.models import (
    CandidateProfile,
    CandidateSkill,
    RecruitmentCandidate,
    RecruitmentMatchResult,
    RecruitmentMatchRun,
    RecruitmentProject,
)
from app.recruitment.parsing import MAX_JD_FILE_BYTES, detect_jd_document
from app.recruitment.schemas import (
    RecruitmentCandidateCreatedResponse,
    RecruitmentCandidateUploadResponse,
    RecruitmentJDSubmitResponse,
    RecruitmentProjectCreateRequest,
    RecruitmentProjectResponse,
    RequirementsConfirmResponse,
    RequirementsReplaceRequest,
)
from app.resumes.parsing import (
    DOCX_MEDIA_TYPE,
    MAX_RESUME_FILE_BYTES,
    detect_resume_document,
    normalize_extracted_text,
)
from app.worker import celery_app

storage = FileStorage(get_settings().file_storage_root)
MAX_JD_TEXT_CHARS = 100_000
MAX_CANDIDATE_FILES = 20
MAX_CANDIDATE_BATCH_BYTES = 100 * 1024 * 1024


def require_recruitment_role(actor: User) -> None:
    if actor.role not in {"hr", "admin"}:
        raise APIError(
            403,
            "RECRUITMENT_ROLE_REQUIRED",
            "当前角色不能使用招聘项目",
        )


async def _attach_lgf_signals(
    ranked: list,
    *,
    project_title: str,
    snapshot: dict,
    profiles_by_candidate: dict[UUID, CandidateProfile],
    skills_by_profile: dict[UUID, list[CandidateSkill]],
) -> None:
    settings = get_settings()
    if not settings.lgf_enabled:
        for value in ranked:
            value.scored.dimension_scores["lgf"] = {
                "status": "disabled",
                "score": None,
                "match_level": None,
                "error_code": None,
            }
        return
    if settings.lgf_match_url is None:
        status = {
            "status": "degraded",
            "score": None,
            "match_level": None,
            "error_code": "LGF_NOT_CONFIGURED",
        }
        for value in ranked:
            value.scored.dimension_scores["lgf"] = dict(status)
        return

    timeout = httpx.Timeout(settings.lgf_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as http:
        client = LGFClient(
            url=str(settings.lgf_match_url),
            api_key=(
                settings.lgf_api_key.get_secret_value()
                if settings.lgf_api_key
                else None
            ),
            http=http,
        )
        for value in ranked:
            profile = profiles_by_candidate[value.candidate.id]
            resume_skills = [
                {
                    "skill": skill.raw_name,
                    "mastery": skill.proficiency or "proficient",
                }
                for skill in skills_by_profile[profile.id]
                if skill.capability_id is not None
            ]
            result = await client.match(
                LGFMatchRequest(
                    job_id=str(snapshot.get("job_id") or project_title),
                    resume={
                        "skills": resume_skills,
                        "years_experience": (
                            profile.total_experience_months / 12
                            if profile.total_experience_months is not None
                            else None
                        ),
                    },
                )
            )
            value.scored.dimension_scores["lgf"] = {
                "status": result.status,
                "score": (
                    result.payload.match_score if result.payload is not None else None
                ),
                "match_level": (
                    result.payload.match_level if result.payload is not None else None
                ),
                "error_code": result.error_code,
            }


async def get_visible_project(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    for_update: bool = False,
) -> RecruitmentProject:
    statement = select(RecruitmentProject).where(RecruitmentProject.id == project_id)
    if actor.role != "admin":
        statement = statement.where(RecruitmentProject.owner_user_id == actor.id)
    if for_update:
        statement = statement.with_for_update()
    project = await db.scalar(statement)
    if project is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "招聘项目不存在")
    return project


async def create_project(
    db: AsyncSession,
    actor: User,
    payload: RecruitmentProjectCreateRequest,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    require_recruitment_role(actor)
    title = payload.title.strip()
    description = payload.description.strip() if payload.description else None
    if not title:
        raise APIError(422, "VALIDATION_FAILED", "项目名称不能为空")
    project = RecruitmentProject(
        owner_user_id=actor.id,
        title=title,
        description=description or None,
        jd_parse_status="empty",
        jd_draft_payload={},
        confirmed_requirement_snapshot={},
    )
    db.add(project)
    await db.flush()
    record_audit(
        db,
        action="recruitment_project.create",
        resource_type="recruitment_project",
        resource_id=project.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"project_id": str(project.id)},
    )
    await db.commit()
    await db.refresh(project)
    return await project_detail(db, project)


async def list_projects(
    db: AsyncSession,
    actor: User,
    *,
    page: int,
    page_size: int,
    query: str | None,
) -> list[dict]:
    require_recruitment_role(actor)
    statement = select(RecruitmentProject)
    if actor.role != "admin":
        statement = statement.where(RecruitmentProject.owner_user_id == actor.id)
    normalized_query = (query or "").strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                RecruitmentProject.title.ilike(pattern),
                RecruitmentProject.description.ilike(pattern),
            )
        )
    projects = (
        await db.scalars(
            statement.order_by(
                RecruitmentProject.created_at.desc(),
                RecruitmentProject.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [await project_detail(db, project) for project in projects]


async def project_detail(db: AsyncSession, project: RecruitmentProject) -> dict:
    candidate_counts = {
        status: 0 for status in ("uploaded", "processing", "ready", "failed")
    }
    candidate_counts.update(
        {
            status: int(count)
            for status, count in (
                await db.execute(
                    select(RecruitmentCandidate.parse_status, func.count())
                    .where(RecruitmentCandidate.project_id == project.id)
                    .group_by(RecruitmentCandidate.parse_status)
                )
            ).all()
        }
    )
    candidate_counts["total"] = sum(candidate_counts.values())
    latest_match = await db.scalar(
        select(RecruitmentMatchRun)
        .where(RecruitmentMatchRun.project_id == project.id)
        .order_by(RecruitmentMatchRun.created_at.desc(), RecruitmentMatchRun.id.desc())
        .limit(1)
    )
    latest_match_data = None
    if latest_match is not None:
        latest_match_data = {
            "id": str(latest_match.id),
            "requirements_revision": latest_match.requirements_revision,
            "result_count": latest_match.result_count,
            "high_count": latest_match.high_count,
            "medium_count": latest_match.medium_count,
            "low_count": latest_match.low_count,
            "created_at": latest_match.created_at.isoformat(),
        }
    latest_processing = await db.scalar(
        select(ProcessingRun)
        .where(
            ProcessingRun.owner_scope_type == "recruitment_project",
            ProcessingRun.owner_scope_id == project.id,
        )
        .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
        .limit(1)
    )
    latest_processing_data = None
    if latest_processing is not None:
        latest_processing_data = {
            "id": str(latest_processing.id),
            "run_type": latest_processing.run_type,
            "status": latest_processing.status,
            "processed_count": latest_processing.processed_count,
            "success_count": latest_processing.success_count,
            "failed_count": latest_processing.failed_count,
            "progress_percent": float(latest_processing.progress_percent),
            "error_code": latest_processing.error_code,
            "created_at": latest_processing.created_at.isoformat(),
        }
    return RecruitmentProjectResponse(
        id=project.id,
        owner_user_id=project.owner_user_id,
        title=project.title,
        description=project.description,
        jd_source_type=project.jd_source_type,
        jd_file_id=project.jd_file_id,
        jd_parse_status=project.jd_parse_status,
        jd_draft_payload=project.jd_draft_payload,
        confirmed_requirement_summary=_confirmed_requirement_summary(project),
        confirmed_requirement_sha256=project.confirmed_requirement_sha256,
        requirements_revision=project.requirements_revision,
        latest_jd_run_id=project.latest_jd_run_id,
        candidate_counts=candidate_counts,
        latest_processing_run=latest_processing_data,
        latest_match_run=latest_match_data,
        created_at=project.created_at,
        updated_at=project.updated_at,
    ).model_dump(mode="json")


def _confirmed_requirement_summary(project: RecruitmentProject) -> dict:
    snapshot = project.confirmed_requirement_snapshot
    if not snapshot:
        return {}
    requirements = snapshot.get("requirements", [])
    return {
        "job_title": snapshot.get("job_title"),
        "minimum_education_level": snapshot.get("minimum_education_level"),
        "recommended_experience_months": snapshot.get("recommended_experience_months"),
        "required_capability_count": sum(
            item.get("requirement_type") == "required" for item in requirements
        ),
        "bonus_capability_count": sum(
            item.get("requirement_type") == "bonus" for item in requirements
        ),
        "unmapped_skill_count": len(snapshot.get("unmapped_skills", [])),
        "confirmed_at": snapshot.get("confirmed_at"),
    }


async def submit_jd(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    text: str | None,
    upload: UploadFile | None,
    idempotency_key: str,
    request_id: str,
    ip_address: str | None,
) -> RecruitmentJDSubmitResponse:
    require_recruitment_role(actor)
    if (text is None) == (upload is None):
        raise _invalid_jd_input()
    project = await get_visible_project(db, project_id, actor, for_update=True)

    stored_file = None
    storage_key = None
    if text is not None:
        source_text = _normalize_jd_text(text)
        source_type = "text"
        source_sha256 = hashlib.sha256(source_text.encode()).hexdigest()
        source_size = len(source_text.encode())
        document_type = None
    else:
        stored_file, document_type, storage_key = await _store_jd_file(upload, actor)
        source_text = None
        source_type = "file"
        source_sha256 = stored_file.sha256
        source_size = stored_file.size_bytes

    request_hash = _jd_request_hash(
        project.id,
        source_type=source_type,
        source_sha256=source_sha256,
        source_size=source_size,
    )
    existing = await _find_jd_idempotency(db, actor.id, idempotency_key)
    if existing is not None:
        if storage_key:
            _remove_file(storage_key)
        return _reuse_jd_submission(existing, request_hash)

    active_run = await db.scalar(
        select(ProcessingRun.id).where(
            ProcessingRun.run_type == "parse_recruitment_jd",
            ProcessingRun.subject_type == "recruitment_project",
            ProcessingRun.subject_id == project.id,
            ProcessingRun.status.in_({"pending", "running"}),
        )
    )
    if active_run is not None:
        if storage_key:
            _remove_file(storage_key)
        raise APIError(409, "RECRUITMENT_JD_PROCESSING", "JD 正在解析中")

    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_jd",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=actor.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_jd_parse_v1",
        total_count=1,
        max_attempts=1,
        input_snapshot={
            "project_id": str(project.id),
            "source_type": source_type,
            "file_id": str(stored_file.id) if stored_file else None,
            "source_sha256": source_sha256,
            "document_type": document_type,
        },
        result_summary={},
    )
    response = RecruitmentJDSubmitResponse(
        project_id=project.id,
        run_id=run.id,
        run_url=f"/api/v1/processing-runs/{run.id}",
    )
    idempotency = IdempotencyRecord(
        user_id=actor.id,
        endpoint_key="recruitment.jd.submit",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_status=202,
        response_body=response.model_dump(mode="json"),
        resource_type="recruitment_project",
        resource_id=project.id,
        state="completed",
    )
    old_file = (
        await db.get(StoredFile, project.jd_file_id) if project.jd_file_id else None
    )
    if old_file is not None:
        old_file.status = "archived"
    if stored_file is not None:
        db.add(stored_file)
    db.add_all([run, idempotency])
    await db.flush()
    project.jd_source_type = source_type
    project.jd_file_id = stored_file.id if stored_file else None
    project.jd_source_text = source_text
    project.jd_parse_status = "processing"
    project.jd_draft_payload = {}
    project.latest_jd_run_id = run.id
    record_audit(
        db,
        action="recruitment_jd.submit",
        resource_type="recruitment_project",
        resource_id=project.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "project_id": str(project.id),
            "run_id": str(run.id),
            "file_id": str(stored_file.id) if stored_file else None,
            "source_type": source_type,
            "source_sha256": source_sha256,
            "source_size": source_size,
        },
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if storage_key:
            _remove_file(storage_key)
        existing = await _find_jd_idempotency(db, actor.id, idempotency_key)
        if existing is not None:
            return _reuse_jd_submission(existing, request_hash)
        raise
    except Exception:
        await db.rollback()
        if storage_key:
            _remove_file(storage_key)
        raise

    try:
        task = celery_app.send_task("app.parse_recruitment_jd", args=[str(run.id)])
        run.celery_task_id = task.id
        run.enqueued_at = datetime.now(UTC)
    except Exception:
        run.status = "enqueue_failed"
        run.error_code = "TASK_ENQUEUE_FAILED"
        run.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    return response


async def replace_requirements(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    payload: RequirementsReplaceRequest,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    require_recruitment_role(actor)
    project = await get_visible_project(db, project_id, actor, for_update=True)
    if not project.jd_draft_payload:
        raise APIError(409, "RECRUITMENT_JD_NOT_READY", "JD 草稿尚未就绪")
    catalog = await load_active_capability_catalog(
        db,
        [item.capability_id for item in payload.requirements],
    )
    existing = project.jd_draft_payload
    draft = {
        "schema_version": "recruitment_requirements_v1",
        "source_run_id": existing.get("source_run_id"),
        "job_title": payload.job_title.strip(),
        "summary": payload.summary.strip() if payload.summary else None,
        "responsibilities": [item.strip() for item in payload.responsibilities],
        "minimum_education_level": payload.minimum_education_level,
        "recommended_experience_months": payload.recommended_experience_months,
        "requirements": [
            {
                **catalog[item.capability_id],
                "raw_name": catalog[item.capability_id]["canonical_name"],
                "requirement_type": item.requirement_type,
                "importance": item.importance,
                "mapping_method": "manual",
                "evidence_quote": None,
                "confidence": None,
            }
            for item in payload.requirements
        ],
        "unmapped_skills": [
            {
                "raw_name": item.raw_name.strip(),
                "normalized_name": normalize_skill_label(item.raw_name),
                "requirement_type": item.requirement_type,
                "evidence_quote": None,
                "confidence": None,
            }
            for item in payload.unmapped_skills
        ],
        "validation_warnings": list(existing.get("validation_warnings", [])),
    }
    if existing.get("extractor_metadata") is not None:
        draft["extractor_metadata"] = existing["extractor_metadata"]
    project.jd_draft_payload = draft
    record_audit(
        db,
        action="recruitment_requirements.replace",
        resource_type="recruitment_project",
        resource_id=project.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"project_id": str(project.id)},
    )
    await db.commit()
    return draft


async def confirm_requirements(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    request_id: str,
    ip_address: str | None,
) -> RequirementsConfirmResponse:
    require_recruitment_role(actor)
    project = await get_visible_project(db, project_id, actor, for_update=True)
    draft = dict(project.jd_draft_payload)
    if not draft:
        raise APIError(409, "RECRUITMENT_JD_NOT_READY", "JD 草稿尚未就绪")
    requirements = list(draft.get("requirements", []))
    if not any(item.get("requirement_type") == "required" for item in requirements):
        raise APIError(
            422,
            "RECRUITMENT_REQUIRED_SKILL_MISSING",
            "至少需要一个已映射的必备技能",
        )
    capability_ids = [UUID(item["capability_id"]) for item in requirements]
    await load_active_capability_catalog(db, capability_ids)
    content = await _confirmation_content(db, project, draft)
    requirements_sha256 = hashlib.sha256(_canonical_json(content).encode()).hexdigest()
    reused = requirements_sha256 == project.confirmed_requirement_sha256
    if reused:
        snapshot = dict(project.confirmed_requirement_snapshot)
        confirmed_at = datetime.fromisoformat(snapshot["confirmed_at"])
    else:
        confirmed_at = datetime.now(UTC)
        revision = project.requirements_revision + 1
        snapshot = {
            **content,
            "revision_no": revision,
            "confirmed_at": confirmed_at.isoformat(),
            "confirmed_by_user_id": str(actor.id),
        }
        project.confirmed_requirement_snapshot = snapshot
        project.confirmed_requirement_sha256 = requirements_sha256
        project.requirements_revision = revision
    record_audit(
        db,
        action="recruitment_requirements.confirm",
        resource_type="recruitment_project",
        resource_id=project.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "project_id": str(project.id),
            "requirements_revision": project.requirements_revision,
            "requirements_sha256": requirements_sha256,
            "reused": reused,
        },
    )
    await db.commit()
    return RequirementsConfirmResponse(
        project_id=project.id,
        requirements_revision=project.requirements_revision,
        requirements_sha256=requirements_sha256,
        reused=reused,
        confirmed_at=confirmed_at,
        snapshot=snapshot,
    )


async def upload_candidates(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    uploads: list[UploadFile],
    *,
    idempotency_key: str,
    request_id: str,
    ip_address: str | None,
) -> RecruitmentCandidateUploadResponse:
    require_recruitment_role(actor)
    project = await get_visible_project(db, project_id, actor, for_update=True)
    if not 1 <= len(uploads) <= MAX_CANDIDATE_FILES:
        raise APIError(
            422,
            "CANDIDATE_FILE_COUNT_INVALID",
            "每批候选简历数量必须为 1 到 20",
        )

    prepared: list[tuple[StoredFile, str, str]] = []
    total_size = 0
    try:
        for upload in uploads:
            stored_file, display_name, storage_key = await _store_candidate_file(
                upload,
                actor,
            )
            prepared.append((stored_file, display_name, storage_key))
            total_size += stored_file.size_bytes
            if total_size > MAX_CANDIDATE_BATCH_BYTES:
                raise APIError(
                    413,
                    "CANDIDATE_BATCH_TOO_LARGE",
                    "候选简历批次超过 100 MB 限制",
                )
    except Exception:
        for _stored_file, _display_name, storage_key in prepared:
            _remove_file(storage_key)
        raise

    request_hash = _candidate_request_hash(project.id, prepared)
    existing = await _find_candidate_idempotency(db, actor.id, idempotency_key)
    if existing is not None:
        for _stored_file, _display_name, storage_key in prepared:
            _remove_file(storage_key)
        return _reuse_candidate_upload(existing, request_hash)

    run_id = uuid4()
    candidates = [
        RecruitmentCandidate(
            id=uuid4(),
            project_id=project.id,
            file_id=stored_file.id,
            display_name=display_name,
            parse_status="uploaded",
            latest_run_id=run_id,
            created_by_user_id=actor.id,
        )
        for stored_file, display_name, _storage_key in prepared
    ]
    candidate_ids = sorted(str(candidate.id) for candidate in candidates)
    run = ProcessingRun(
        id=run_id,
        run_type="parse_recruitment_candidates",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=actor.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_candidate_parse_v1",
        total_count=len(candidates),
        max_attempts=1,
        input_snapshot={"candidate_ids": candidate_ids},
        result_summary={},
    )
    response = RecruitmentCandidateUploadResponse(
        project_id=project.id,
        run_id=run.id,
        run_url=f"/api/v1/processing-runs/{run.id}",
        candidates=[
            RecruitmentCandidateCreatedResponse(
                id=candidate.id,
                display_name=candidate.display_name,
                parse_status="uploaded",
                file_id=candidate.file_id,
            )
            for candidate in candidates
        ],
    )
    idempotency = IdempotencyRecord(
        user_id=actor.id,
        endpoint_key="recruitment.candidates.upload",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_status=202,
        response_body=response.model_dump(mode="json"),
        resource_type="recruitment_project",
        resource_id=project.id,
        state="completed",
    )
    db.add_all([*(stored_file for stored_file, _name, _key in prepared), run])
    await db.flush()
    db.add_all([*candidates, idempotency])
    record_audit(
        db,
        action="recruitment_candidates.upload",
        resource_type="recruitment_project",
        resource_id=project.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "project_id": str(project.id),
            "run_id": str(run.id),
            "candidate_count": len(candidates),
            "total_size": total_size,
        },
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        for _stored_file, _display_name, storage_key in prepared:
            _remove_file(storage_key)
        existing = await _find_candidate_idempotency(
            db,
            actor.id,
            idempotency_key,
        )
        if existing is not None:
            return _reuse_candidate_upload(existing, request_hash)
        raise
    except Exception:
        await db.rollback()
        for _stored_file, _display_name, storage_key in prepared:
            _remove_file(storage_key)
        raise

    try:
        task = celery_app.send_task(
            "app.parse_recruitment_candidates",
            args=[str(run.id)],
        )
        run.celery_task_id = task.id
        run.enqueued_at = datetime.now(UTC)
    except Exception:
        run.status = "enqueue_failed"
        run.error_code = "TASK_ENQUEUE_FAILED"
        run.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    return response


async def list_candidates(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    page: int,
    page_size: int,
    parse_status: str | None,
    query: str | None,
) -> list[dict]:
    project = await get_visible_project(db, project_id, actor)
    statement = select(RecruitmentCandidate).where(
        RecruitmentCandidate.project_id == project.id
    )
    if parse_status is not None:
        statement = statement.where(RecruitmentCandidate.parse_status == parse_status)
    normalized_query = (query or "").strip()
    if normalized_query:
        statement = statement.where(
            RecruitmentCandidate.display_name.ilike(f"%{normalized_query}%")
        )
    candidates = (
        await db.scalars(
            statement.order_by(
                RecruitmentCandidate.created_at.desc(),
                RecruitmentCandidate.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_candidate_summary(candidate) for candidate in candidates]


async def candidate_detail(
    db: AsyncSession,
    project_id: UUID,
    candidate_id: UUID,
    actor: User,
) -> dict:
    project = await get_visible_project(db, project_id, actor)
    candidate = await db.scalar(
        select(RecruitmentCandidate).where(
            RecruitmentCandidate.id == candidate_id,
            RecruitmentCandidate.project_id == project.id,
        )
    )
    if candidate is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "候选人不存在")
    profile = await db.scalar(
        select(CandidateProfile).where(CandidateProfile.candidate_id == candidate.id)
    )
    profile_data = None
    if profile is not None:
        skill_rows = (
            await db.execute(
                select(CandidateSkill, Capability.canonical_name)
                .outerjoin(Capability, Capability.id == CandidateSkill.capability_id)
                .where(CandidateSkill.profile_id == profile.id)
                .order_by(CandidateSkill.normalized_name, CandidateSkill.id)
            )
        ).all()
        profile_data = {
            "id": str(profile.id),
            "extraction_version": profile.extraction_version,
            "text_extraction_method": profile.text_extraction_method,
            "highest_education_level": profile.highest_education_level,
            "total_experience_months": profile.total_experience_months,
            "profile": profile.structured_payload,
            "skills": [
                {
                    "id": str(skill.id),
                    "raw_name": skill.raw_name,
                    "normalized_name": skill.normalized_name,
                    "capability_id": (
                        str(skill.capability_id) if skill.capability_id else None
                    ),
                    "capability_name": capability_name,
                    "proficiency": skill.proficiency,
                    "explicit_experience_months": skill.explicit_experience_months,
                    "evidence_strength": skill.evidence_strength,
                    "evidence_quote": skill.evidence_quote,
                    "evidence_start": skill.evidence_start,
                    "evidence_end": skill.evidence_end,
                    "mapping_method": skill.mapping_method,
                    "mapping_status": skill.mapping_status,
                    "confidence": float(skill.confidence),
                }
                for skill, capability_name in skill_rows
            ],
            "created_at": profile.created_at.isoformat(),
        }
    data = _candidate_summary(candidate)
    file_url = f"/api/v1/files/{candidate.file_id}"
    data.update(
        {
            "file": {
                "id": str(candidate.file_id),
                "metadata_url": file_url,
                "content_url": f"{file_url}/content",
                "download_url": f"{file_url}/download",
            },
            "profile": profile_data,
        }
    )
    return data


async def create_match_run(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    require_recruitment_role(actor)
    project = await get_visible_project(db, project_id, actor, for_update=True)
    if (
        project.requirements_revision < 1
        or not project.confirmed_requirement_sha256
        or not project.confirmed_requirement_snapshot
    ):
        raise APIError(
            409,
            "REQUIREMENTS_NOT_CONFIRMED",
            "招聘要求尚未确认",
        )
    candidates = (
        await db.scalars(
            select(RecruitmentCandidate)
            .where(RecruitmentCandidate.project_id == project.id)
            .order_by(RecruitmentCandidate.id)
            .with_for_update()
        )
    ).all()
    if not candidates:
        raise APIError(422, "NO_MATCHABLE_CANDIDATES", "项目中没有候选人")
    if any(
        candidate.parse_status in {"uploaded", "processing"} for candidate in candidates
    ):
        raise APIError(409, "CANDIDATES_NOT_READY", "仍有候选简历尚未解析完成")

    ready = [candidate for candidate in candidates if candidate.parse_status == "ready"]
    profiles = (
        await db.scalars(
            select(CandidateProfile).where(
                CandidateProfile.candidate_id.in_([candidate.id for candidate in ready])
            )
        )
    ).all()
    profiles_by_candidate = {profile.candidate_id: profile for profile in profiles}
    if any(candidate.id not in profiles_by_candidate for candidate in ready):
        raise APIError(
            409,
            "CANDIDATE_PROFILE_MISSING",
            "ready 候选人缺少可匹配画像",
        )
    if not ready:
        raise APIError(422, "NO_MATCHABLE_CANDIDATES", "没有可匹配的 ready 候选人")

    selection = canonical_candidate_selection(candidates, profiles_by_candidate)
    selection_sha256 = sha256_json(selection)
    existing = await _find_match_run(
        db,
        project.id,
        project.confirmed_requirement_sha256,
        selection_sha256,
    )
    if existing is not None:
        return await _match_run_response(db, existing, reused=True)

    profile_ids = [profile.id for profile in profiles]
    skills = (
        await db.scalars(
            select(CandidateSkill)
            .where(CandidateSkill.profile_id.in_(profile_ids))
            .order_by(CandidateSkill.profile_id, CandidateSkill.normalized_name)
        )
    ).all()
    skills_by_profile: dict[UUID, list[CandidateSkill]] = defaultdict(list)
    for skill in skills:
        skills_by_profile[skill.profile_id].append(skill)
    match_inputs = [
        RecruitmentCandidateMatchInput(
            candidate=candidate,
            profile_record=profiles_by_candidate[candidate.id],
            profile=profile_input(
                profiles_by_candidate[candidate.id],
                skills_by_profile[profiles_by_candidate[candidate.id].id],
            ),
        )
        for candidate in ready
    ]
    snapshot = dict(project.confirmed_requirement_snapshot)
    try:
        requirements = requirement_inputs(snapshot)
        ranked = rank_candidate_matches(
            match_inputs,
            requirements,
            minimum_education_level=snapshot.get("minimum_education_level"),
            recommended_experience_months=snapshot.get("recommended_experience_months"),
        )
    except (KeyError, TypeError, ValueError, MatchCatalogInconsistent) as error:
        raise APIError(
            409,
            "MATCH_INPUT_CONFLICT",
            "确认要求或候选画像不满足匹配规则",
        ) from error
    await _attach_lgf_signals(
        ranked,
        project_title=project.title,
        snapshot=snapshot,
        profiles_by_candidate=profiles_by_candidate,
        skills_by_profile=skills_by_profile,
    )

    skipped = [
        {
            "candidate_id": str(candidate.id),
            "display_name": candidate.display_name,
            "parse_status": candidate.parse_status,
            "latest_run_id": (
                str(candidate.latest_run_id) if candidate.latest_run_id else None
            ),
        }
        for candidate in candidates
        if candidate.parse_status == "failed"
    ]
    counts = {level: 0 for level in ("high", "medium", "low")}
    for value in ranked:
        counts[value.scored.match_level] += 1
    match_run = RecruitmentMatchRun(
        id=uuid4(),
        project_id=project.id,
        requirements_revision=project.requirements_revision,
        requirements_sha256=project.confirmed_requirement_sha256,
        candidate_selection_sha256=selection_sha256,
        weight_version=WEIGHT_VERSION,
        weight_snapshot=weight_snapshot(),
        requirements_snapshot=snapshot,
        skipped_candidates=skipped,
        result_count=len(ranked),
        skipped_count=len(skipped),
        high_count=counts["high"],
        medium_count=counts["medium"],
        low_count=counts["low"],
        created_by_user_id=actor.id,
    )
    db.add(match_run)
    await db.flush()
    db.add_all(
        [
            RecruitmentMatchResult(
                match_run_id=match_run.id,
                candidate_id=value.candidate.id,
                candidate_profile_id=value.profile_record.id,
                rank=value.rank,
                total_score=value.scored.total_score,
                match_level=value.scored.match_level,
                dimension_scores=value.scored.dimension_scores,
                matched_capabilities=value.scored.matched_capabilities,
                missing_capabilities=value.scored.missing_capabilities,
                gap_summary=value.scored.gap_summary,
                candidate_snapshot=candidate_snapshot(
                    value.candidate,
                    value.profile_record,
                ),
            )
            for value in ranked
        ]
    )
    record_audit(
        db,
        action="recruitment_match.run",
        resource_type="recruitment_match_run",
        resource_id=match_run.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "project_id": str(project.id),
            "run_id": str(match_run.id),
            "requirements_revision": project.requirements_revision,
            "requirements_sha256": project.confirmed_requirement_sha256,
            "candidate_count": len(candidates),
            "weight_version": WEIGHT_VERSION,
            "skipped_count": len(skipped),
        },
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _find_match_run(
            db,
            project.id,
            project.confirmed_requirement_sha256,
            selection_sha256,
        )
        if existing is None:
            raise APIError(
                409,
                "MATCH_INPUT_CONFLICT",
                "匹配输入并发冲突",
            ) from None
        return await _match_run_response(db, existing, reused=True)
    return await _match_run_response(db, match_run, reused=False)


async def list_match_runs(
    db: AsyncSession,
    project_id: UUID,
    actor: User,
    *,
    page: int,
    page_size: int,
) -> list[dict]:
    project = await get_visible_project(db, project_id, actor)
    runs = (
        await db.scalars(
            select(RecruitmentMatchRun)
            .where(RecruitmentMatchRun.project_id == project.id)
            .order_by(
                RecruitmentMatchRun.created_at.desc(),
                RecruitmentMatchRun.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_match_run_data(run) for run in runs]


async def list_match_results(
    db: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    actor: User,
    *,
    page: int,
    page_size: int,
) -> list[dict]:
    run = await _visible_match_run(db, project_id, run_id, actor)
    results = (
        await db.scalars(
            select(RecruitmentMatchResult)
            .where(RecruitmentMatchResult.match_run_id == run.id)
            .order_by(RecruitmentMatchResult.rank)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_match_result_data(result) for result in results]


async def match_result_detail(
    db: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    candidate_id: UUID,
    actor: User,
) -> dict:
    run = await _visible_match_run(db, project_id, run_id, actor)
    result = await db.scalar(
        select(RecruitmentMatchResult).where(
            RecruitmentMatchResult.match_run_id == run.id,
            RecruitmentMatchResult.candidate_id == candidate_id,
        )
    )
    if result is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "匹配结果不存在")
    return {
        **_match_result_data(result),
        "requirements_snapshot": run.requirements_snapshot,
        "weight_snapshot": run.weight_snapshot,
        "matched_capabilities": result.matched_capabilities,
        "missing_capabilities": result.missing_capabilities,
    }


async def load_active_capability_catalog(
    db: AsyncSession,
    capability_ids: list[UUID],
) -> dict[UUID, dict]:
    if not capability_ids:
        return {}
    rows = (
        await db.execute(
            select(Capability, Domain)
            .join(Domain, Domain.id == Capability.domain_id)
            .where(
                Capability.id.in_(capability_ids),
                Capability.status == "active",
            )
        )
    ).all()
    catalog = {
        capability.id: {
            "capability_id": str(capability.id),
            "canonical_name": capability.canonical_name,
            "skill_type": capability.skill_type,
            "domain": {
                "id": str(domain.id),
                "code": domain.code,
                "name": domain.name,
            },
        }
        for capability, domain in rows
    }
    if set(catalog) != set(capability_ids):
        raise APIError(
            409,
            "RECRUITMENT_CAPABILITY_INACTIVE",
            "标准技能不存在或未启用",
        )
    return catalog


async def _store_candidate_file(
    upload: UploadFile,
    actor: User,
) -> tuple[StoredFile, str, str]:
    original_name = Path(upload.filename or "").name
    if not original_name or len(original_name) > 255:
        raise APIError(422, "CANDIDATE_DOCUMENT_INVALID", "候选简历文件名无效")
    extension = Path(original_name).suffix.lower().lstrip(".")
    file_id = uuid4()
    storage_key = f"resume/{file_id}.{extension}"
    try:
        size_bytes, file_sha256 = await storage.save_stream(
            upload,
            storage_key,
            MAX_RESUME_FILE_BYTES,
        )
    except FileSizeLimitExceeded:
        raise APIError(
            413,
            "CANDIDATE_FILE_TOO_LARGE",
            "单份候选简历超过 20 MB 限制",
        ) from None
    except ValueError:
        raise APIError(422, "CANDIDATE_DOCUMENT_INVALID", "候选简历不能为空") from None
    media_type = (upload.content_type or "application/octet-stream").split(";", 1)[0]
    try:
        document_type = detect_resume_document(
            original_name,
            media_type,
            storage.resolve(storage_key).read_bytes(),
        )
    except (APIError, OSError):
        _remove_file(storage_key)
        raise APIError(
            422,
            "CANDIDATE_DOCUMENT_INVALID",
            "候选简历格式或结构无效",
        ) from None
    display_name = Path(original_name).stem.strip() or original_name
    return (
        StoredFile(
            id=file_id,
            uploaded_by_user_id=actor.id,
            original_name=original_name,
            storage_key=storage_key,
            media_type=(
                "application/pdf" if document_type == "pdf" else DOCX_MEDIA_TYPE
            ),
            extension=document_type,
            size_bytes=size_bytes,
            sha256=file_sha256,
            category="resume",
            scan_status="not_required",
            status="attached",
        ),
        display_name[:200],
        storage_key,
    )


async def _find_candidate_idempotency(
    db: AsyncSession,
    user_id: UUID,
    key: str,
) -> IdempotencyRecord | None:
    return await db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.endpoint_key == "recruitment.candidates.upload",
            IdempotencyRecord.idempotency_key == key,
        )
    )


def _reuse_candidate_upload(
    existing: IdempotencyRecord,
    request_hash: str,
) -> RecruitmentCandidateUploadResponse:
    if existing.request_hash != request_hash:
        raise APIError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
    if not existing.response_body:
        raise APIError(409, "REQUEST_IN_PROGRESS", "相同请求正在处理")
    return RecruitmentCandidateUploadResponse.model_validate(existing.response_body)


def _candidate_request_hash(
    project_id: UUID,
    prepared: list[tuple[StoredFile, str, str]],
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "project_id": str(project_id),
                "files": [
                    {
                        "original_name": stored_file.original_name,
                        "size_bytes": stored_file.size_bytes,
                        "sha256": stored_file.sha256,
                    }
                    for stored_file, _display_name, _storage_key in prepared
                ],
            }
        ).encode()
    ).hexdigest()


def _candidate_summary(candidate: RecruitmentCandidate) -> dict:
    return {
        "id": str(candidate.id),
        "project_id": str(candidate.project_id),
        "display_name": candidate.display_name,
        "parse_status": candidate.parse_status,
        "file_id": str(candidate.file_id),
        "latest_run_id": (
            str(candidate.latest_run_id) if candidate.latest_run_id else None
        ),
        "created_at": candidate.created_at.isoformat(),
        "updated_at": candidate.updated_at.isoformat(),
    }


async def _find_match_run(
    db: AsyncSession,
    project_id: UUID,
    requirements_sha256: str,
    candidate_selection_sha256: str,
) -> RecruitmentMatchRun | None:
    return await db.scalar(
        select(RecruitmentMatchRun).where(
            RecruitmentMatchRun.project_id == project_id,
            RecruitmentMatchRun.requirements_sha256 == requirements_sha256,
            RecruitmentMatchRun.candidate_selection_sha256
            == candidate_selection_sha256,
            RecruitmentMatchRun.weight_version == WEIGHT_VERSION,
        )
    )


async def _visible_match_run(
    db: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    actor: User,
) -> RecruitmentMatchRun:
    project = await get_visible_project(db, project_id, actor)
    run = await db.scalar(
        select(RecruitmentMatchRun).where(
            RecruitmentMatchRun.id == run_id,
            RecruitmentMatchRun.project_id == project.id,
        )
    )
    if run is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "匹配任务不存在")
    return run


async def _match_run_response(
    db: AsyncSession,
    run: RecruitmentMatchRun,
    *,
    reused: bool,
) -> dict:
    results = (
        await db.scalars(
            select(RecruitmentMatchResult)
            .where(RecruitmentMatchResult.match_run_id == run.id)
            .order_by(RecruitmentMatchResult.rank)
            .limit(20)
        )
    ).all()
    return {
        "reused": reused,
        "run": _match_run_data(run),
        "items": [_match_result_data(result) for result in results],
    }


def _match_run_data(run: RecruitmentMatchRun) -> dict:
    return {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "requirements_revision": run.requirements_revision,
        "requirements_sha256": run.requirements_sha256,
        "candidate_selection_sha256": run.candidate_selection_sha256,
        "weight_version": run.weight_version,
        "result_count": run.result_count,
        "skipped_count": run.skipped_count,
        "high_count": run.high_count,
        "medium_count": run.medium_count,
        "low_count": run.low_count,
        "created_at": run.created_at.isoformat(),
    }


def _match_result_data(result: RecruitmentMatchResult) -> dict:
    return {
        "candidate_id": str(result.candidate_id),
        "candidate_profile_id": str(result.candidate_profile_id),
        "rank": result.rank,
        "total_score": float(result.total_score),
        "match_level": result.match_level,
        "candidate": result.candidate_snapshot["candidate"],
        "candidate_snapshot": result.candidate_snapshot,
        "dimension_scores": result.dimension_scores,
        "gap_summary": result.gap_summary,
    }


async def _confirmation_content(
    db: AsyncSession,
    project: RecruitmentProject,
    draft: dict,
) -> dict:
    stored_file = (
        await db.get(StoredFile, project.jd_file_id) if project.jd_file_id else None
    )
    source_text = project.jd_source_text or ""
    requirements = sorted(
        draft.get("requirements", []),
        key=lambda item: (item["requirement_type"], item["capability_id"]),
    )
    unmapped = sorted(
        draft.get("unmapped_skills", []),
        key=lambda item: (item["requirement_type"], item["normalized_name"]),
    )
    return {
        "schema_version": "recruitment_requirements_v1",
        "source": {
            "type": project.jd_source_type,
            "file_id": str(project.jd_file_id) if project.jd_file_id else None,
            "file_sha256": stored_file.sha256 if stored_file else None,
            "text_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        },
        "source_text": source_text,
        "job_title": draft.get("job_title"),
        "summary": draft.get("summary"),
        "responsibilities": list(draft.get("responsibilities", [])),
        "minimum_education_level": draft.get("minimum_education_level"),
        "recommended_experience_months": draft.get("recommended_experience_months"),
        "requirements": requirements,
        "unmapped_skills": unmapped,
        "validation_warnings": sorted(draft.get("validation_warnings", [])),
    }


async def _store_jd_file(
    upload: UploadFile | None,
    actor: User,
) -> tuple[StoredFile, str, str]:
    if upload is None:
        raise _invalid_jd_input()
    original_name = Path(upload.filename or "").name
    if not original_name or len(original_name) > 255:
        raise _invalid_jd_input()
    extension = Path(original_name).suffix.lower().lstrip(".")
    file_id = uuid4()
    storage_key = f"jd/{file_id}.{extension}"
    try:
        size_bytes, file_sha256 = await storage.save_stream(
            upload,
            storage_key,
            MAX_JD_FILE_BYTES,
        )
    except FileSizeLimitExceeded:
        raise APIError(
            413, "RECRUITMENT_JD_TOO_LARGE", "JD 文件超过 10 MB 限制"
        ) from None
    except ValueError:
        raise _invalid_jd_input() from None
    media_type = (upload.content_type or "application/octet-stream").split(";", 1)[0]
    try:
        content = storage.resolve(storage_key).read_bytes()
        document_type = detect_jd_document(original_name, media_type, content)
    except (APIError, OSError):
        _remove_file(storage_key)
        raise
    canonical_media_type = {
        "pdf": "application/pdf",
        "docx": DOCX_MEDIA_TYPE,
        "txt": "text/plain",
    }[document_type]
    return (
        StoredFile(
            id=file_id,
            uploaded_by_user_id=actor.id,
            original_name=original_name,
            storage_key=storage_key,
            media_type=canonical_media_type,
            extension=document_type,
            size_bytes=size_bytes,
            sha256=file_sha256,
            category="jd",
            scan_status="not_required",
            status="attached",
        ),
        document_type,
        storage_key,
    )


def _normalize_jd_text(value: str) -> str:
    if len(value) > MAX_JD_TEXT_CHARS:
        raise APIError(413, "RECRUITMENT_JD_TOO_LARGE", "JD 文本超过长度限制")
    try:
        return normalize_extracted_text(value)
    except APIError as error:
        if error.code == "RESUME_TEXT_TOO_LONG":
            raise APIError(
                413, "RECRUITMENT_JD_TOO_LARGE", "JD 文本超过长度限制"
            ) from error
        raise _invalid_jd_input() from error


def _invalid_jd_input() -> APIError:
    return APIError(422, "RECRUITMENT_JD_INPUT_INVALID", "JD 文本与文件必须二选一")


async def _find_jd_idempotency(
    db: AsyncSession,
    user_id: UUID,
    key: str,
) -> IdempotencyRecord | None:
    return await db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.endpoint_key == "recruitment.jd.submit",
            IdempotencyRecord.idempotency_key == key,
        )
    )


def _reuse_jd_submission(
    existing: IdempotencyRecord,
    request_hash: str,
) -> RecruitmentJDSubmitResponse:
    if existing.request_hash != request_hash:
        raise APIError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
    if not existing.response_body:
        raise APIError(409, "REQUEST_IN_PROGRESS", "相同请求正在处理")
    return RecruitmentJDSubmitResponse.model_validate(existing.response_body)


def _jd_request_hash(
    project_id: UUID,
    *,
    source_type: str,
    source_sha256: str,
    source_size: int,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "project_id": str(project_id),
                "source_type": source_type,
                "source_sha256": source_sha256,
                "source_size": source_size,
            }
        ).encode()
    ).hexdigest()


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _remove_file(storage_key: str) -> None:
    try:
        storage.resolve(storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        return
