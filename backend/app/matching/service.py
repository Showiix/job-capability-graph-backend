from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.models import (
    Capability,
    CatalogVersion,
    CatalogVersionItem,
    Domain,
    JobRole,
    JobRoleCapability,
)
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.matching.models import MatchResult, MatchRun
from app.matching.schemas import (
    DomainSnapshotRead,
    JobRoleSnapshotRead,
    JobRoleSummaryRead,
    MatchResultDetail,
    MatchResultListItem,
    MatchResultPage,
    MatchRunPage,
    MatchRunRead,
    PublishedVersionRef,
    RecommendationDetailData,
    RecommendationRunData,
    ResumeProfileVersionRef,
)
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.resumes.service import get_visible_resume
from app.reviews.schemas import MatchPolicy

from .scoring import (
    WEIGHT_VERSION,
    CapabilityRequirementInput,
    JobRoleMatchInput,
    MatchCatalogInconsistent,
    ProfileMatchInput,
    ProfileSkillInput,
    rank_scored_job_roles,
    score_job_role,
    weight_snapshot,
)


@dataclass(frozen=True)
class MatchWatermark:
    resume: Resume
    profile: ResumeProfile
    graph: GraphVersion
    catalog: CatalogVersion


@dataclass(frozen=True)
class ScoringInputs:
    profile: ProfileMatchInput
    job_roles: tuple[JobRoleMatchInput, ...]


@dataclass(frozen=True)
class RecommendationRunResult:
    reused: bool
    run: MatchRun
    results: tuple[MatchResult, ...]


def require_matching_reader(actor: User) -> None:
    if actor.role not in {"applicant", "admin"}:
        raise APIError(403, "ROLE_NOT_ALLOWED", "当前角色不能访问岗位推荐")


async def load_match_watermark(
    db: AsyncSession,
    actor: User,
    resume_id: UUID,
) -> MatchWatermark:
    require_matching_reader(actor)
    resume = await get_visible_resume(db, resume_id, actor, for_update=True)
    if resume.parse_status == "archived":
        raise APIError(409, "RESUME_ARCHIVED", "简历已归档")
    profile = await db.scalar(
        select(ResumeProfile).where(
            ResumeProfile.resume_id == resume.id,
            ResumeProfile.status == "confirmed",
        )
    )
    if profile is None:
        raise APIError(409, "RESUME_PROFILE_NOT_CONFIRMED", "请先确认简历画像")

    row = (
        await db.execute(
            select(GraphVersion, CatalogVersion)
            .outerjoin(
                CatalogVersion,
                CatalogVersion.id == GraphVersion.catalog_version_id,
            )
            .where(
                GraphVersion.status == "published",
                GraphVersion.is_current.is_(True),
            )
        )
    ).first()
    if row is None:
        raise APIError(404, "GRAPH_VERSION_NOT_PUBLISHED", "当前没有正式图谱版本")
    graph, catalog = row
    if catalog is None or catalog.status != "published" or not catalog.is_current:
        raise _catalog_inconsistent()
    return MatchWatermark(
        resume=resume,
        profile=profile,
        graph=graph,
        catalog=catalog,
    )


async def load_scoring_inputs(
    db: AsyncSession,
    watermark: MatchWatermark,
) -> ScoringInputs:
    items = (
        await db.scalars(
            select(CatalogVersionItem).where(
                CatalogVersionItem.catalog_version_id == watermark.catalog.id
            )
        )
    ).all()
    job_role_ids = {
        item.job_role_id
        for item in items
        if item.item_type == "job_role" and item.job_role_id is not None
    }
    capability_ids = {
        item.capability_id
        for item in items
        if item.item_type == "capability" and item.capability_id is not None
    }
    role_rows = []
    if job_role_ids:
        role_rows = (
            await db.execute(
                select(JobRole, Domain)
                .join(Domain, Domain.id == JobRole.domain_id)
                .where(
                    JobRole.id.in_(job_role_ids),
                    JobRole.status == "active",
                    Domain.status == "active",
                )
                .order_by(JobRole.canonical_name, JobRole.id)
            )
        ).all()
    if not role_rows:
        raise APIError(
            409,
            "MATCH_JOB_ROLE_NOT_AVAILABLE",
            "当前岗位目录没有可匹配岗位",
        )

    active_role_ids = {role.id for role, _ in role_rows}
    relation_rows = []
    if capability_ids:
        relation_rows = (
            await db.execute(
                select(JobRoleCapability, Capability, Domain)
                .join(
                    Capability,
                    Capability.id == JobRoleCapability.capability_id,
                )
                .join(Domain, Domain.id == Capability.domain_id)
                .where(
                    JobRoleCapability.job_role_id.in_(active_role_ids),
                    Capability.id.in_(capability_ids),
                    Capability.status == "active",
                    Domain.status == "active",
                )
            )
        ).all()
    requirements_by_role: dict[UUID, list[CapabilityRequirementInput]] = {
        role_id: [] for role_id in active_role_ids
    }
    for relation, capability, domain in relation_rows:
        requirements_by_role[relation.job_role_id].append(
            CapabilityRequirementInput(
                capability_id=capability.id,
                canonical_name=capability.canonical_name,
                skill_type=capability.skill_type,
                requirement_type=relation.requirement_type,
                importance=relation.importance,
                domain_id=domain.id,
                domain_code=domain.code,
                domain_name=domain.name,
            )
        )

    job_roles = []
    for role, domain in role_rows:
        capabilities = tuple(requirements_by_role[role.id])
        _validate_capability_requirements(capabilities)
        policy = _match_policy(role.definition_payload)
        job_roles.append(
            JobRoleMatchInput(
                job_role_id=role.id,
                canonical_name=role.canonical_name,
                description=role.description,
                domain_id=domain.id,
                domain_code=domain.code,
                domain_name=domain.name,
                definition_payload=role.definition_payload,
                minimum_education_level=policy.minimum_education_level,
                recommended_experience_months=policy.recommended_experience_months,
                capabilities=capabilities,
            )
        )

    skill_rows = (
        await db.scalars(
            select(ResumeSkill).where(
                ResumeSkill.profile_id == watermark.profile.id,
                ResumeSkill.mapping_status == "mapped",
                ResumeSkill.capability_id.is_not(None),
            )
        )
    ).all()
    skills = {
        skill.capability_id: ProfileSkillInput(
            id=skill.id,
            capability_id=skill.capability_id,
            raw_name=skill.raw_name,
            mapping_method=skill.mapping_method,
            evidence_strength=skill.evidence_strength,
            evidence_quote=skill.evidence_quote,
        )
        for skill in skill_rows
        if skill.capability_id is not None
    }
    return ScoringInputs(
        profile=ProfileMatchInput(
            highest_education_level=watermark.profile.highest_education_level,
            total_experience_months=watermark.profile.total_experience_months,
            skills=skills,
        ),
        job_roles=tuple(job_roles),
    )


async def create_or_reuse_recommendations(
    db: AsyncSession,
    actor: User,
    resume_id: UUID,
    *,
    request_id: str | None,
    ip_address: str | None,
) -> RecommendationRunResult:
    try:
        watermark = await load_match_watermark(db, actor, resume_id)
        existing = await _find_match_run(db, watermark)
        if existing is not None:
            results = await _load_match_results(db, existing.id)
            _record_recommendation_audit(
                db,
                action="job_recommendation.run.reuse",
                actor=actor,
                run=existing,
                watermark=watermark,
                request_id=request_id,
                ip_address=ip_address,
            )
            await db.commit()
            return RecommendationRunResult(
                reused=True,
                run=existing,
                results=tuple(results[:20]),
            )

        inputs = await load_scoring_inputs(db, watermark)
        scored = rank_scored_job_roles(
            [score_job_role(inputs.profile, role) for role in inputs.job_roles]
        )
        run = MatchRun(
            owner_user_id=watermark.resume.owner_user_id,
            resume_id=watermark.resume.id,
            resume_profile_id=watermark.profile.id,
            graph_version_id=watermark.graph.id,
            catalog_version_id=watermark.catalog.id,
            weight_version=WEIGHT_VERSION,
            weight_snapshot=weight_snapshot(),
            result_count=len(scored),
            high_count=sum(value.match_level == "high" for value in scored),
            medium_count=sum(value.match_level == "medium" for value in scored),
            low_count=sum(value.match_level == "low" for value in scored),
        )
        db.add(run)
        try:
            await db.flush()
        except IntegrityError as error:
            if not _is_match_run_natural_key_conflict(error):
                raise
            await db.rollback()
            return await _reuse_after_conflict(
                db,
                actor,
                resume_id,
                request_id=request_id,
                ip_address=ip_address,
            )

        result_rows = [
            MatchResult(
                match_run_id=run.id,
                job_role_id=value.job_role_id,
                rank=value.rank,
                total_score=value.total_score,
                match_level=value.match_level,
                dimension_scores=value.dimension_scores,
                matched_capabilities=value.matched_capabilities,
                missing_capabilities=value.missing_capabilities,
                gap_summary=value.gap_summary,
                job_role_snapshot=value.job_role_snapshot,
            )
            for value in scored
        ]
        db.add_all(result_rows)
        _record_recommendation_audit(
            db,
            action="job_recommendation.run.create",
            actor=actor,
            run=run,
            watermark=watermark,
            request_id=request_id,
            ip_address=ip_address,
        )
        await db.commit()
        return RecommendationRunResult(
            reused=False,
            run=run,
            results=tuple(result_rows[:20]),
        )
    except APIError as error:
        await db.rollback()
        raise error
    except MatchCatalogInconsistent as error:
        await db.rollback()
        raise _catalog_inconsistent() from error
    except Exception:
        await db.rollback()
        raise


async def list_match_runs(
    db: AsyncSession,
    actor: User,
    *,
    page: int,
    page_size: int,
    resume_id: UUID | None = None,
) -> MatchRunPage:
    require_matching_reader(actor)
    _validate_pagination(page, page_size)
    filters = []
    if actor.role != "admin":
        filters.append(MatchRun.owner_user_id == actor.id)
    if resume_id is not None:
        filters.append(MatchRun.resume_id == resume_id)
    total = await db.scalar(select(func.count()).select_from(MatchRun).where(*filters))
    rows = (
        await db.execute(
            _match_run_read_statement()
            .where(*filters)
            .order_by(MatchRun.created_at.desc(), MatchRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MatchRunPage(
        items=[_match_run_read(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


async def get_visible_match_run(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
) -> MatchRunRead:
    row = await _get_visible_match_run_row(db, actor, match_run_id)
    return _match_run_read(row)


async def get_match_run_results(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    *,
    page: int,
    page_size: int,
) -> RecommendationRunData:
    _validate_pagination(page, page_size)
    run_row = await _get_visible_match_run_row(db, actor, match_run_id)
    run = run_row[0]
    results = (
        await db.scalars(
            select(MatchResult)
            .where(MatchResult.match_run_id == run.id)
            .order_by(MatchResult.rank)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return RecommendationRunData(
        run=_match_run_read(run_row),
        results=MatchResultPage(
            items=[_match_result_list_item(value) for value in results],
            page=page,
            page_size=page_size,
            total=run.result_count,
        ),
    )


async def get_match_result_detail(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
) -> RecommendationDetailData:
    run_row = await _get_visible_match_run_row(db, actor, match_run_id)
    result = await db.scalar(
        select(MatchResult).where(
            MatchResult.match_run_id == match_run_id,
            MatchResult.job_role_id == job_role_id,
        )
    )
    if result is None:
        raise APIError(404, "MATCH_RESULT_NOT_FOUND", "岗位匹配结果不存在")
    list_item = _match_result_list_item(result)
    detail_data = list_item.model_dump()
    detail_data["job_role"] = JobRoleSnapshotRead.model_validate(
        result.job_role_snapshot
    )
    return RecommendationDetailData(
        run=_match_run_read(run_row),
        result=MatchResultDetail(
            **detail_data,
            matched_capabilities=result.matched_capabilities,
            missing_capabilities=result.missing_capabilities,
        ),
    )


def _match_run_read_statement():
    return (
        select(
            MatchRun,
            ResumeProfile.version_no,
            GraphVersion.version_no,
            CatalogVersion.version_no,
        )
        .join(ResumeProfile, ResumeProfile.id == MatchRun.resume_profile_id)
        .join(GraphVersion, GraphVersion.id == MatchRun.graph_version_id)
        .join(CatalogVersion, CatalogVersion.id == MatchRun.catalog_version_id)
    )


async def _get_visible_match_run_row(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
):
    require_matching_reader(actor)
    statement = _match_run_read_statement().where(MatchRun.id == match_run_id)
    if actor.role != "admin":
        statement = statement.where(MatchRun.owner_user_id == actor.id)
    row = (await db.execute(statement)).one_or_none()
    if row is None:
        raise APIError(404, "MATCH_RUN_NOT_FOUND", "岗位推荐记录不存在")
    return row


def _match_run_read(row) -> MatchRunRead:
    run, profile_version, graph_version, catalog_version = row
    return MatchRunRead(
        id=run.id,
        owner_user_id=run.owner_user_id,
        resume_id=run.resume_id,
        resume_profile=ResumeProfileVersionRef(
            id=run.resume_profile_id,
            version_no=profile_version,
        ),
        graph_version=PublishedVersionRef(
            id=run.graph_version_id,
            version_no=graph_version,
        ),
        catalog_version=PublishedVersionRef(
            id=run.catalog_version_id,
            version_no=catalog_version,
        ),
        weight_version=run.weight_version,
        result_count=run.result_count,
        high_count=run.high_count,
        medium_count=run.medium_count,
        low_count=run.low_count,
        created_at=run.created_at,
    )


def _match_result_list_item(result: MatchResult) -> MatchResultListItem:
    snapshot = result.job_role_snapshot
    domain = DomainSnapshotRead.model_validate(snapshot["domain"])
    return MatchResultListItem(
        job_role_id=result.job_role_id,
        rank=result.rank,
        total_score=result.total_score,
        match_level=result.match_level,
        job_role=JobRoleSummaryRead(
            id=snapshot["id"],
            canonical_name=snapshot["canonical_name"],
            description=snapshot.get("description"),
            domain=domain,
        ),
        dimension_scores=result.dimension_scores,
        gap_summary=result.gap_summary,
        created_at=result.created_at,
    )


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1 or page_size < 1 or page_size > 100:
        raise APIError(422, "VALIDATION_FAILED", "分页参数无效")


async def _find_match_run(
    db: AsyncSession,
    watermark: MatchWatermark,
) -> MatchRun | None:
    return await db.scalar(
        select(MatchRun).where(
            MatchRun.resume_profile_id == watermark.profile.id,
            MatchRun.graph_version_id == watermark.graph.id,
            MatchRun.weight_version == WEIGHT_VERSION,
        )
    )


async def _load_match_results(
    db: AsyncSession,
    match_run_id: UUID,
) -> list[MatchResult]:
    return (
        await db.scalars(
            select(MatchResult)
            .where(MatchResult.match_run_id == match_run_id)
            .order_by(MatchResult.rank)
        )
    ).all()


def _record_recommendation_audit(
    db: AsyncSession,
    *,
    action: str,
    actor: User,
    run: MatchRun,
    watermark: MatchWatermark,
    request_id: str | None,
    ip_address: str | None,
) -> None:
    record_audit(
        db,
        action=action,
        resource_type="match_run",
        resource_id=run.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "resume_id": str(watermark.resume.id),
            "resume_profile_id": str(watermark.profile.id),
            "graph_version_id": str(watermark.graph.id),
            "catalog_version_id": str(watermark.catalog.id),
            "weight_version": run.weight_version,
            "result_count": run.result_count,
        },
    )


def _is_match_run_natural_key_conflict(error: IntegrityError) -> bool:
    original = error.orig
    constraint_name = getattr(original, "constraint_name", None)
    if constraint_name is None:
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name == "uq_match_runs_profile_graph_weight"


async def _reuse_after_conflict(
    db: AsyncSession,
    actor: User,
    resume_id: UUID,
    *,
    request_id: str | None,
    ip_address: str | None,
) -> RecommendationRunResult:
    watermark = await load_match_watermark(db, actor, resume_id)
    run = await _find_match_run(db, watermark)
    if run is None:
        raise RuntimeError("match run conflict winner is unavailable")
    results = await _load_match_results(db, run.id)
    _record_recommendation_audit(
        db,
        action="job_recommendation.run.reuse",
        actor=actor,
        run=run,
        watermark=watermark,
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()
    return RecommendationRunResult(
        reused=True,
        run=run,
        results=tuple(results[:20]),
    )


def _validate_capability_requirements(
    capabilities: tuple[CapabilityRequirementInput, ...],
) -> None:
    required = [value for value in capabilities if value.requirement_type == "required"]
    bonus = [value for value in capabilities if value.requirement_type == "bonus"]
    required_importance = sum(
        (value.importance for value in required),
        start=Decimal("0"),
    )
    bonus_importance = sum(
        (value.importance for value in bonus),
        start=Decimal("0"),
    )
    if not required or required_importance <= 0:
        raise _catalog_inconsistent()
    if bonus and bonus_importance <= 0:
        raise _catalog_inconsistent()


def _match_policy(definition_payload: dict) -> MatchPolicy:
    value = definition_payload.get("match_policy")
    if value is None:
        return MatchPolicy()
    try:
        return MatchPolicy.model_validate(value)
    except ValidationError as error:
        raise _catalog_inconsistent() from error


def _catalog_inconsistent() -> APIError:
    return APIError(503, "MATCH_CATALOG_INCONSISTENT", "岗位能力目录不一致")
