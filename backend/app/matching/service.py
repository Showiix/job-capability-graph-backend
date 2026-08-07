from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.resumes.service import get_visible_resume
from app.reviews.schemas import MatchPolicy

from .scoring import (
    CapabilityRequirementInput,
    JobRoleMatchInput,
    ProfileMatchInput,
    ProfileSkillInput,
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
