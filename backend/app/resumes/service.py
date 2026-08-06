import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.models import Capability, CapabilityAlias
from app.core.config import get_settings
from app.core.errors import APIError
from app.discovery.mining import normalize_skill_label
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileSizeLimitExceeded, FileStorage
from app.processing.models import IdempotencyRecord, ProcessingRun
from app.resumes.llm import LLMParseResult
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.resumes.parsing import (
    DOCX_MEDIA_TYPE,
    MAX_RESUME_FILE_BYTES,
    ValidatedParse,
    derive_highest_education,
    derive_total_experience_months,
    detect_resume_document,
    skill_rank,
)
from app.resumes.schemas import (
    ExtractedTextResponse,
    ResumeCreatedResponse,
    ResumeFileLinks,
    ResumeProfileResponse,
    ResumeProfileSummaryResponse,
    ResumeResponse,
    ResumeSkillResponse,
)
from app.worker import celery_app

storage = FileStorage(get_settings().file_storage_root)
ALLOWED_RESUME_MEDIA_TYPES = {
    "pdf": {"application/pdf", "application/octet-stream"},
    "docx": {DOCX_MEDIA_TYPE, "application/octet-stream"},
}


@dataclass(frozen=True, slots=True)
class MappedResumeSkill:
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    proficiency: str | None
    explicit_experience_months: int | None
    evidence_strength: str
    evidence_quote: str
    evidence_start: int
    evidence_end: int
    mapping_method: str
    mapping_status: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SkillMappingResult:
    skills: list[MappedResumeSkill]
    warnings: list[str]


async def map_resume_skills(
    db: AsyncSession,
    skills: list[dict],
) -> SkillMappingResult:
    warnings: list[str] = []
    by_name: dict[str, list[dict]] = defaultdict(list)
    for source in skills:
        normalized_name = normalize_skill_label(source["name"])
        if not normalized_name:
            warnings.append("SKILL_NAME_EMPTY")
            continue
        candidate = dict(source)
        candidate["normalized_name"] = normalized_name
        by_name[normalized_name].append(candidate)

    candidates = [
        max(values, key=skill_rank)
        for _name, values in sorted(by_name.items())
    ]

    # ponytail: full active-catalog scan is acceptable at ~30k rows;
    # add persisted normalized columns and indexes only after profiling shows
    # a bottleneck.
    capabilities = (
        await db.scalars(select(Capability).where(Capability.status == "active"))
    ).all()
    canonical: dict[str, list[Capability]] = defaultdict(list)
    for capability in capabilities:
        normalized = normalize_skill_label(capability.canonical_name)
        if normalized:
            canonical[normalized].append(capability)

    alias_rows = (
        await db.execute(
            select(CapabilityAlias, Capability)
            .join(Capability, Capability.id == CapabilityAlias.capability_id)
            .where(
                CapabilityAlias.status == "active",
                Capability.status == "active",
            )
        )
    ).all()
    aliases: dict[str, dict[UUID, Capability]] = defaultdict(dict)
    for alias, capability in alias_rows:
        normalized = normalize_skill_label(alias.alias)
        if normalized:
            aliases[normalized][capability.id] = capability

    mapped_with_sources: list[tuple[MappedResumeSkill, dict]] = []
    for candidate in candidates:
        normalized_name = candidate["normalized_name"]
        capability = None
        mapping_method = "unmapped"
        canonical_matches = canonical.get(normalized_name, [])
        if len(canonical_matches) == 1:
            capability = canonical_matches[0]
            mapping_method = "canonical_exact"
        elif len(canonical_matches) > 1:
            warnings.append(f"AMBIGUOUS_CAPABILITY_NAME:{normalized_name}")
        else:
            alias_matches = list(aliases.get(normalized_name, {}).values())
            if len(alias_matches) == 1:
                capability = alias_matches[0]
                mapping_method = "alias_exact"
            elif len(alias_matches) > 1:
                warnings.append(f"AMBIGUOUS_CAPABILITY_ALIAS:{normalized_name}")

        mapped = MappedResumeSkill(
            raw_name=candidate["name"],
            normalized_name=normalized_name,
            capability_id=capability.id if capability is not None else None,
            proficiency=candidate["proficiency"],
            explicit_experience_months=candidate["explicit_experience_months"],
            evidence_strength=candidate["evidence_strength"],
            evidence_quote=candidate["evidence_quote"],
            evidence_start=candidate["evidence_start"],
            evidence_end=candidate["evidence_end"],
            mapping_method=mapping_method,
            mapping_status="mapped" if capability is not None else "unmapped",
            confidence=float(candidate["confidence"]),
        )
        mapped_with_sources.append((mapped, candidate))

    selected = [
        pair for pair in mapped_with_sources if pair[0].capability_id is None
    ]
    by_capability: dict[UUID, list[tuple[MappedResumeSkill, dict]]] = defaultdict(list)
    for pair in mapped_with_sources:
        if pair[0].capability_id is not None:
            by_capability[pair[0].capability_id].append(pair)
    selected.extend(
        max(values, key=lambda pair: skill_rank(pair[1]))
        for values in by_capability.values()
    )

    return SkillMappingResult(
        skills=sorted(
            (pair[0] for pair in selected),
            key=lambda item: item.normalized_name,
        ),
        warnings=warnings,
    )


async def get_existing_extracted_profile(
    db: AsyncSession,
    resume_id: UUID,
    extraction_version: str,
) -> ResumeProfile | None:
    return await db.scalar(
        select(ResumeProfile).where(
            ResumeProfile.resume_id == resume_id,
            ResumeProfile.extraction_version == extraction_version,
            ResumeProfile.profile_source == "extracted",
        )
    )


async def complete_run_for_profile(
    db: AsyncSession,
    *,
    resume: Resume,
    run: ProcessingRun,
    profile: ResumeProfile,
) -> dict:
    counts = dict(
        (
            await db.execute(
                select(ResumeSkill.mapping_status, func.count())
                .where(ResumeSkill.profile_id == profile.id)
                .group_by(ResumeSkill.mapping_status)
            )
        ).all()
    )
    warnings = profile.structured_payload.get("validation_warnings", [])
    result = {
        "result_url": (
            f"/api/v1/resumes/{resume.id}/profiles/{profile.version_no}"
        ),
        "resume_id": str(resume.id),
        "profile_id": str(profile.id),
        "profile_version": profile.version_no,
        "mapped_skill_count": int(counts.get("mapped", 0)),
        "unmapped_skill_count": int(counts.get("unmapped", 0)),
        "validation_warning_count": len(warnings),
    }
    now = datetime.now(UTC)
    resume.parse_status = "ready"
    resume.latest_run_id = run.id
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
    run.result_summary = result
    await db.commit()
    return result


async def persist_extracted_profile(
    db: AsyncSession,
    *,
    resume: Resume,
    run: ProcessingRun,
    extracted_text: str,
    extraction_method: str,
    validated: ValidatedParse,
    mapping: SkillMappingResult,
    llm_result: LLMParseResult,
    requested_model: str,
    current_month: date,
) -> ResumeProfile:
    resume_id = resume.id
    run_id = run.id
    extraction_version = run.pipeline_version
    try:
        locked_resume = await db.scalar(
            select(Resume).where(Resume.id == resume_id).with_for_update()
        )
        existing = await get_existing_extracted_profile(
            db,
            resume_id,
            extraction_version,
        )
        if existing is not None:
            await complete_run_for_profile(
                db,
                resume=locked_resume,
                run=run,
                profile=existing,
            )
            return existing

        version_no = (
            await db.scalar(
                select(func.max(ResumeProfile.version_no)).where(
                    ResumeProfile.resume_id == resume_id
                )
            )
            or 0
        ) + 1
        highest_education = derive_highest_education(validated.educations)
        total_experience, date_warnings = derive_total_experience_months(
            validated.experiences,
            current_month=current_month,
        )
        validation_warnings = [
            *validated.warnings,
            *mapping.warnings,
            *date_warnings,
        ]
        structured_payload = {
            "schema_version": "resume_parse_v1",
            "document_language": validated.document_language,
            "summary": validated.summary,
            "educations": validated.educations,
            "experiences": validated.experiences,
            "projects": validated.projects,
            "validation_warnings": validation_warnings,
            "llm_metadata": {
                "response_id": llm_result.response_id,
                "requested_model": requested_model,
                "returned_model": llm_result.returned_model,
                "status": llm_result.status,
                "input_tokens": llm_result.usage.get("input_tokens"),
                "output_tokens": llm_result.usage.get("output_tokens"),
                "total_tokens": llm_result.usage.get("total_tokens"),
                "provider_attempts": llm_result.provider_attempts,
                "prompt_version": "resume_parse_v1",
                "response_sha256": llm_result.response_sha256,
            },
        }
        profile = ResumeProfile(
            resume_id=resume_id,
            version_no=version_no,
            extraction_version=run.pipeline_version,
            profile_source="extracted",
            extracted_text=extracted_text,
            text_extraction_method=extraction_method,
            highest_education_level=highest_education,
            total_experience_months=total_experience,
            structured_payload=structured_payload,
            status="candidate",
            created_by_run_id=run_id,
            created_by_user_id=run.created_by_user_id,
        )
        db.add(profile)
        await db.flush()
        db.add_all(
            [
                ResumeSkill(
                    profile_id=profile.id,
                    capability_id=value.capability_id,
                    raw_name=value.raw_name,
                    normalized_name=value.normalized_name,
                    proficiency=value.proficiency,
                    explicit_experience_months=value.explicit_experience_months,
                    evidence_strength=value.evidence_strength,
                    evidence_quote=value.evidence_quote,
                    evidence_start=value.evidence_start,
                    evidence_end=value.evidence_end,
                    mapping_method=value.mapping_method,
                    mapping_status=value.mapping_status,
                    source="llm",
                    confidence=Decimal(str(value.confidence)),
                    user_confirmed=False,
                )
                for value in mapping.skills
            ]
        )
        await db.flush()
        await complete_run_for_profile(
            db,
            resume=locked_resume,
            run=run,
            profile=profile,
        )
        return profile
    except IntegrityError:
        await db.rollback()
        existing = await get_existing_extracted_profile(
            db,
            resume_id,
            extraction_version,
        )
        if existing is None:
            raise
        current_resume = await db.get(Resume, resume_id)
        current_run = await db.get(ProcessingRun, run_id)
        await complete_run_for_profile(
            db,
            resume=current_resume,
            run=current_run,
            profile=existing,
        )
        return existing


def require_resume_reader(actor: User) -> None:
    if actor.role == "hr":
        raise APIError(403, "ROLE_NOT_ALLOWED", "当前角色不能访问应聘者简历")


def require_resume_creator(actor: User) -> None:
    if actor.role != "applicant":
        raise APIError(403, "ROLE_NOT_ALLOWED", "当前角色不能创建应聘者简历")


async def get_visible_resume(
    db: AsyncSession,
    resume_id: UUID,
    actor: User,
    *,
    for_update: bool = False,
) -> Resume:
    require_resume_reader(actor)
    statement = select(Resume).where(Resume.id == resume_id)
    if actor.role != "admin":
        statement = statement.where(Resume.owner_user_id == actor.id)
    if for_update:
        statement = statement.with_for_update()
    value = await db.scalar(statement)
    if value is None:
        raise APIError(404, "RESOURCE_NOT_OWNED", "简历不存在")
    return value


async def create_resume(
    db: AsyncSession,
    actor: User,
    upload: UploadFile,
    *,
    display_name: str | None,
    idempotency_key: str | None,
    request_id: str,
    ip_address: str | None,
) -> ResumeCreatedResponse:
    require_resume_creator(actor)
    original_name = Path(upload.filename or "").name
    if len(original_name) > 255:
        raise APIError(422, "VALIDATION_FAILED", "简历文件名过长")
    extension = Path(original_name).suffix.lower().lstrip(".")
    media_type = (upload.content_type or "application/octet-stream").split(";", 1)[
        0
    ].lower()
    if (
        extension not in ALLOWED_RESUME_MEDIA_TYPES
        or media_type not in ALLOWED_RESUME_MEDIA_TYPES[extension]
    ):
        raise APIError(
            415,
            "RESUME_FILE_TYPE_UNSUPPORTED",
            "仅支持 PDF 或 DOCX 简历",
        )

    normalized_display_name = (display_name or "").strip() or original_name
    if not normalized_display_name or len(normalized_display_name) > 200:
        raise APIError(422, "VALIDATION_FAILED", "简历名称长度无效")

    file_id = uuid4()
    resume_id = uuid4()
    run_id = uuid4()
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
            "RESUME_FILE_TOO_LARGE",
            "简历文件超过 20 MB 限制",
        ) from None
    except ValueError as error:
        if str(error) == "empty file":
            raise APIError(400, "RESUME_FILE_EMPTY", "简历文件不能为空") from None
        raise

    try:
        content = storage.resolve(storage_key).read_bytes()
        document_type = detect_resume_document(original_name, media_type, content)
    except (APIError, OSError):
        _remove_resume_file(storage_key)
        raise APIError(
            415,
            "RESUME_FILE_TYPE_UNSUPPORTED",
            "简历文件格式或结构无效",
        ) from None

    request_hash = _resume_request_hash(file_sha256, normalized_display_name)
    if idempotency_key:
        existing = await _find_resume_idempotency(db, actor.id, idempotency_key)
        if existing is not None:
            _remove_resume_file(storage_key)
            return _reuse_resume_idempotency(existing, request_hash)

    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=actor.id,
        original_name=original_name,
        storage_key=storage_key,
        media_type="application/pdf" if document_type == "pdf" else DOCX_MEDIA_TYPE,
        extension=extension,
        size_bytes=size_bytes,
        sha256=file_sha256,
        category="resume",
        scan_status="not_required",
        status="attached",
    )
    run = ProcessingRun(
        id=run_id,
        run_type="parse_resume",
        subject_type="resume",
        subject_id=resume_id,
        created_by_user_id=actor.id,
        owner_scope_type="user",
        owner_scope_id=actor.id,
        status="pending",
        pipeline_version="resume_parse_v1",
        total_count=1,
        max_attempts=1,
        input_snapshot={"resume_id": str(resume_id), "file_id": str(file_id)},
        result_summary={},
    )
    resume = Resume(
        id=resume_id,
        owner_user_id=actor.id,
        file_id=file_id,
        display_name=normalized_display_name,
        source_language="zh-CN",
        parse_status="processing",
        latest_run_id=run_id,
        created_by_user_id=actor.id,
    )
    response = ResumeCreatedResponse(
        resource_id=resume_id,
        run_id=run_id,
        status="processing",
        poll_url=f"/api/v1/processing-runs/{run_id}",
    )
    idempotency = None
    if idempotency_key:
        idempotency = IdempotencyRecord(
            user_id=actor.id,
            endpoint_key="resumes.create",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=202,
            response_body=response.model_dump(mode="json"),
            resource_type="resume",
            resource_id=resume_id,
            state="completed",
        )
        db.add(idempotency)
    db.add_all([stored_file, run, resume])
    record_audit(
        db,
        action="resume.create",
        resource_type="resume",
        resource_id=resume_id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"file_id": str(file_id), "run_id": str(run_id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _remove_resume_file(storage_key)
        if idempotency_key:
            existing = await _find_resume_idempotency(
                db,
                actor.id,
                idempotency_key,
            )
            if existing is not None:
                return _reuse_resume_idempotency(existing, request_hash)
        raise
    except Exception:
        await db.rollback()
        _remove_resume_file(storage_key)
        raise

    try:
        task = celery_app.send_task("app.parse_resume", args=[str(run_id)])
        run.celery_task_id = task.id
        run.enqueued_at = datetime.now(UTC)
    except Exception:
        run.status = "enqueue_failed"
        run.error_code = "TASK_ENQUEUE_FAILED"
        run.error_message = "任务暂时无法投递，可稍后重试"
    if idempotency is not None:
        idempotency.response_body = response.model_dump(mode="json")
    await db.commit()
    return response


async def list_resumes(
    db: AsyncSession,
    actor: User,
    *,
    page: int,
    page_size: int,
    parse_status: str | None,
) -> list[dict]:
    require_resume_reader(actor)
    statement = select(Resume)
    if actor.role != "admin":
        statement = statement.where(Resume.owner_user_id == actor.id)
    if parse_status is None:
        statement = statement.where(Resume.parse_status != "archived")
    else:
        statement = statement.where(Resume.parse_status == parse_status)
    resumes = (
        await db.scalars(
            statement.order_by(Resume.created_at.desc(), Resume.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [await resume_detail(db, value, actor) for value in resumes]


async def resume_detail(
    db: AsyncSession,
    resume: Resume,
    actor: User,
) -> dict:
    require_resume_reader(actor)
    latest_profile_version = await db.scalar(
        select(func.max(ResumeProfile.version_no)).where(
            ResumeProfile.resume_id == resume.id
        )
    )
    confirmed_profile_version = await db.scalar(
        select(ResumeProfile.version_no).where(
            ResumeProfile.resume_id == resume.id,
            ResumeProfile.status == "confirmed",
        )
    )
    file_url = f"/api/v1/files/{resume.file_id}"
    return ResumeResponse(
        id=resume.id,
        display_name=resume.display_name,
        file=ResumeFileLinks(
            id=resume.file_id,
            metadata_url=file_url,
            content_url=f"{file_url}/content",
            download_url=f"{file_url}/download",
        ),
        parse_status=resume.parse_status,
        latest_run_id=resume.latest_run_id,
        latest_profile_version=latest_profile_version,
        confirmed_profile_version=confirmed_profile_version,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
        archived_at=resume.archived_at,
    ).model_dump(mode="json")


async def list_profiles(db: AsyncSession, resume: Resume) -> list[dict]:
    profiles = (
        await db.scalars(
            select(ResumeProfile)
            .where(ResumeProfile.resume_id == resume.id)
            .order_by(ResumeProfile.version_no.desc(), ResumeProfile.id)
        )
    ).all()
    base_ids = [
        profile.base_profile_id for profile in profiles if profile.base_profile_id
    ]
    base_versions = dict(
        (
            await db.execute(
                select(ResumeProfile.id, ResumeProfile.version_no).where(
                    ResumeProfile.id.in_(base_ids)
                )
            )
        ).all()
    ) if base_ids else {}
    return [
        _profile_summary(profile, base_versions.get(profile.base_profile_id))
        for profile in profiles
    ]


async def profile_detail(
    db: AsyncSession,
    resume: Resume,
    version_no: int,
) -> dict:
    profile = await _get_profile_for_resume(db, resume.id, version_no)
    base_profile_version = None
    if profile.base_profile_id is not None:
        base_profile_version = await db.scalar(
            select(ResumeProfile.version_no).where(
                ResumeProfile.id == profile.base_profile_id,
                ResumeProfile.resume_id == resume.id,
            )
        )
    skill_rows = (
        await db.execute(
            select(ResumeSkill, Capability.canonical_name)
            .outerjoin(Capability, Capability.id == ResumeSkill.capability_id)
            .where(ResumeSkill.profile_id == profile.id)
            .order_by(ResumeSkill.normalized_name, ResumeSkill.id)
        )
    ).all()
    skills = [
        ResumeSkillResponse(
            id=skill.id,
            raw_name=skill.raw_name,
            normalized_name=skill.normalized_name,
            capability_id=skill.capability_id,
            capability_name=capability_name,
            proficiency=skill.proficiency,
            explicit_experience_months=skill.explicit_experience_months,
            evidence_strength=skill.evidence_strength,
            evidence_quote=skill.evidence_quote,
            evidence_start=skill.evidence_start,
            evidence_end=skill.evidence_end,
            mapping_method=skill.mapping_method,
            mapping_status=skill.mapping_status,
            source=skill.source,
            confidence=float(skill.confidence),
            user_confirmed=skill.user_confirmed,
        )
        for skill, capability_name in skill_rows
    ]
    summary = _profile_summary_data(profile, base_profile_version)
    return ResumeProfileResponse(
        **summary,
        text_extraction_method=profile.text_extraction_method,
        profile=profile.structured_payload,
        skills=skills,
    ).model_dump(mode="json")


async def extracted_text(
    db: AsyncSession,
    resume: Resume,
    actor: User,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    profile = await db.scalar(
        select(ResumeProfile)
        .where(ResumeProfile.resume_id == resume.id)
        .order_by(ResumeProfile.version_no.desc(), ResumeProfile.id)
        .limit(1)
    )
    if profile is None:
        raise APIError(409, "RUN_RESULT_NOT_READY", "简历解析结果尚未就绪")
    record_audit(
        db,
        action="resume.extracted_text.read",
        resource_type="resume",
        resource_id=resume.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "resume_id": str(resume.id),
            "profile_id": str(profile.id),
            "version_no": profile.version_no,
        },
    )
    await db.commit()
    return ExtractedTextResponse(
        resume_id=resume.id,
        profile_id=profile.id,
        profile_version=profile.version_no,
        text_extraction_method=profile.text_extraction_method,
        extracted_text=profile.extracted_text,
    ).model_dump(mode="json")


async def _get_profile_for_resume(
    db: AsyncSession,
    resume_id: UUID,
    version_no: int,
) -> ResumeProfile:
    profile = await db.scalar(
        select(ResumeProfile).where(
            ResumeProfile.resume_id == resume_id,
            ResumeProfile.version_no == version_no,
        )
    )
    if profile is None:
        raise APIError(404, "RESUME_PROFILE_NOT_FOUND", "简历画像不存在")
    return profile


def _profile_summary(
    profile: ResumeProfile,
    base_profile_version: int | None,
) -> dict:
    return ResumeProfileSummaryResponse(
        **_profile_summary_data(profile, base_profile_version)
    ).model_dump(mode="json")


def _profile_summary_data(
    profile: ResumeProfile,
    base_profile_version: int | None,
) -> dict:
    return {
        "id": profile.id,
        "resume_id": profile.resume_id,
        "version_no": profile.version_no,
        "base_profile_version": base_profile_version,
        "profile_source": profile.profile_source,
        "status": profile.status,
        "extraction_version": profile.extraction_version,
        "highest_education_level": profile.highest_education_level,
        "total_experience_months": profile.total_experience_months,
        "confirmed_at": profile.confirmed_at,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


async def _find_resume_idempotency(
    db: AsyncSession,
    user_id: UUID,
    idempotency_key: str,
) -> IdempotencyRecord | None:
    return await db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.endpoint_key == "resumes.create",
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )


def _reuse_resume_idempotency(
    existing: IdempotencyRecord,
    request_hash: str,
) -> ResumeCreatedResponse:
    if existing.request_hash != request_hash:
        raise APIError(409, "IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
    if not existing.response_body:
        raise APIError(409, "REQUEST_IN_PROGRESS", "相同请求正在处理")
    return ResumeCreatedResponse.model_validate(existing.response_body)


def _resume_request_hash(file_sha256: str, display_name: str) -> str:
    body = {"file_sha256": file_sha256, "display_name": display_name}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _remove_resume_file(storage_key: str) -> None:
    try:
        storage.resolve(storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        return
