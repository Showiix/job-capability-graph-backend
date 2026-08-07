from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.auth.models import User
from app.catalog.models import (
    Capability,
    CatalogVersion,
    CatalogVersionItem,
    Domain,
    JobRole,
    JobRoleCapability,
)
from app.files.models import StoredFile
from app.graph.models import GraphVersion
from app.matching.models import MatchResult, MatchRun
from app.processing.models import ProcessingRun
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.reviews.models import GraphChangeCandidate


@dataclass
class MatchDependencies:
    user: User
    resume: Resume
    profile: ResumeProfile
    catalog: CatalogVersion
    graph: GraphVersion
    domain: Domain
    job_role: JobRole


@dataclass
class ServiceMatchContext:
    applicant: User
    other_applicant: User
    admin: User
    hr: User
    resume: Resume
    profile: ResumeProfile
    catalog: CatalogVersion
    graph: GraphVersion
    proposal: GraphChangeCandidate
    domain: Domain
    capabilities: dict[str, Capability]
    job_roles: tuple[JobRole, JobRole]
    resume_skills: dict[str, ResumeSkill]


async def make_match_dependencies(db_session) -> MatchDependencies:
    suffix = uuid4().hex[:12]
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        username=f"match_{suffix}",
        username_normalized=f"match_{suffix}",
        password_hash="hash",
        display_name="Matching User",
        role="applicant",
        password_changed_at=now,
    )
    stored_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=user.id,
        original_name="resume.pdf",
        storage_key=f"resume/{uuid4()}.pdf",
        media_type="application/pdf",
        extension="pdf",
        size_bytes=16,
        sha256="b" * 64,
        category="resume",
        scan_status="not_required",
        status="attached",
    )
    resume = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=stored_file.id,
        display_name="比赛简历.pdf",
        source_language="zh-CN",
        parse_status="ready",
        created_by_user_id=user.id,
    )
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=resume.id,
        created_by_user_id=user.id,
        owner_scope_type="user",
        owner_scope_id=user.id,
        status="completed",
        pipeline_version="resume_parse_v1",
        total_count=1,
        processed_count=1,
        success_count=1,
        failed_count=0,
        progress_percent=Decimal("100"),
        input_snapshot={"resume_id": str(resume.id)},
        result_summary={},
        started_at=now,
        completed_at=now,
    )
    profile = ResumeProfile(
        id=uuid4(),
        resume_id=resume.id,
        version_no=1,
        extraction_version="resume_parse_v1",
        profile_source="extracted",
        extracted_text="Python 项目经验",
        text_extraction_method="pdf_text",
        highest_education_level="bachelor",
        total_experience_months=24,
        structured_payload={},
        status="confirmed",
        created_by_run_id=processing_run.id,
        created_by_user_id=user.id,
        confirmed_at=now,
    )
    domain = Domain(
        id=uuid4(),
        code=f"matching-{suffix}",
        name="Matching Domain",
        status="active",
        sort_order=0,
    )
    job_role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"AI Engineer {suffix}",
        description="Matching role",
        definition_payload={"role_name": f"AI Engineer {suffix}"},
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={"role_name": job_role.canonical_name},
        source_snapshot={},
        evidence_summary={},
        confidence=Decimal("0.8"),
        review_status="published",
        created_by_user_id=user.id,
        reviewed_by_user_id=user.id,
        reviewed_at=now,
    )
    catalog = CatalogVersion(
        id=uuid4(),
        version_no=1,
        status="published",
        is_current=True,
        created_by_user_id=user.id,
        summary={},
        published_at=now.replace(tzinfo=None),
    )
    graph = GraphVersion(
        id=uuid4(),
        version_no=1,
        source_proposal_id=proposal.id,
        catalog_version_id=catalog.id,
        job_role_id=job_role.id,
        status="published",
        is_current=True,
        snapshot={"job_role": {"id": str(job_role.id)}},
        attempt_count=1,
        created_by_user_id=user.id,
        published_at=now,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add_all([stored_file, processing_run, domain, proposal, catalog])
    await db_session.flush()
    db_session.add_all([resume, job_role])
    await db_session.flush()
    db_session.add_all([profile, graph])
    await db_session.flush()
    return MatchDependencies(
        user=user,
        resume=resume,
        profile=profile,
        catalog=catalog,
        graph=graph,
        domain=domain,
        job_role=job_role,
    )


def make_match_run(context: MatchDependencies, **overrides) -> MatchRun:
    values = {
        "id": uuid4(),
        "owner_user_id": context.user.id,
        "resume_id": context.resume.id,
        "resume_profile_id": context.profile.id,
        "graph_version_id": context.graph.id,
        "catalog_version_id": context.catalog.id,
        "weight_version": "match_weights_v1",
        "weight_snapshot": {"algorithm": "exact_capability_match_v1"},
        "result_count": 1,
        "high_count": 1,
        "medium_count": 0,
        "low_count": 0,
    }
    values.update(overrides)
    return MatchRun(**values)


def make_match_result(run: MatchRun, job_role: JobRole, **overrides) -> MatchResult:
    values = {
        "match_run_id": run.id,
        "job_role_id": job_role.id,
        "rank": 1,
        "total_score": Decimal("88.25"),
        "match_level": "high",
        "dimension_scores": {},
        "matched_capabilities": [],
        "missing_capabilities": [],
        "gap_summary": {},
        "job_role_snapshot": {"id": str(job_role.id)},
    }
    values.update(overrides)
    return MatchResult(**values)


async def make_second_job_role(db_session, context: MatchDependencies) -> JobRole:
    role = JobRole(
        id=uuid4(),
        domain_id=context.domain.id,
        canonical_name=f"Second Role {uuid4().hex[:8]}",
        description="Second matching role",
        definition_payload={"role_name": "Second Role"},
        status="active",
        source_type="manual",
    )
    db_session.add(role)
    await db_session.flush()
    return role


async def build_matching_context(db_session) -> ServiceMatchContext:
    suffix = uuid4().hex[:12]
    now = datetime.now(UTC)
    applicant = _user("applicant", f"applicant_{suffix}", now)
    other_applicant = _user("applicant", f"other_{suffix}", now)
    admin = _user("admin", f"admin_{suffix}", now)
    hr = _user("hr", f"hr_{suffix}", now)
    db_session.add_all([applicant, other_applicant, admin, hr])
    await db_session.flush()

    stored_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=applicant.id,
        original_name="confirmed-resume.pdf",
        storage_key=f"resume/{uuid4()}.pdf",
        media_type="application/pdf",
        extension="pdf",
        size_bytes=32,
        sha256="c" * 64,
        category="resume",
        scan_status="not_required",
        status="attached",
    )
    resume = Resume(
        id=uuid4(),
        owner_user_id=applicant.id,
        file_id=stored_file.id,
        display_name="已确认简历.pdf",
        source_language="zh-CN",
        parse_status="ready",
        created_by_user_id=applicant.id,
    )
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=resume.id,
        created_by_user_id=applicant.id,
        owner_scope_type="user",
        owner_scope_id=applicant.id,
        status="completed",
        pipeline_version="resume_parse_v1",
        total_count=1,
        processed_count=1,
        success_count=1,
        failed_count=0,
        progress_percent=Decimal("100"),
        input_snapshot={"resume_id": str(resume.id)},
        result_summary={},
        started_at=now,
        completed_at=now,
    )
    db_session.add_all([stored_file, processing_run])
    await db_session.flush()
    db_session.add(resume)
    await db_session.flush()
    profile = ResumeProfile(
        id=uuid4(),
        resume_id=resume.id,
        version_no=1,
        extraction_version="resume_parse_v1",
        profile_source="extracted",
        extracted_text="Python PyTorch Docker 项目经验",
        text_extraction_method="pdf_text",
        highest_education_level="associate",
        total_experience_months=18,
        structured_payload={},
        status="confirmed",
        created_by_run_id=processing_run.id,
        created_by_user_id=applicant.id,
        confirmed_at=now,
    )
    db_session.add(profile)
    await db_session.flush()

    domain = Domain(
        id=uuid4(),
        code=f"ai-{suffix}",
        name="人工智能",
        status="active",
        sort_order=0,
    )
    db_session.add(domain)
    await db_session.flush()
    capabilities = {
        name: Capability(
            id=uuid4(),
            domain_id=domain.id,
            canonical_name=name,
            description=f"{name} capability",
            skill_type="tool",
            status="active",
            source_type="manual",
        )
        for name in ["Python", "PyTorch", "Kubernetes", "Docker", "MLOps"]
    }
    db_session.add_all(capabilities.values())
    await db_session.flush()

    first_role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"AI 应用工程师 {suffix}",
        description="负责 AI 应用开发",
        definition_payload={
            "role_name": f"AI 应用工程师 {suffix}",
            "required_capability_ids": [
                str(capabilities["Python"].id),
                str(capabilities["PyTorch"].id),
            ],
            "bonus_capability_ids": [str(capabilities["Docker"].id)],
            "match_policy": {
                "minimum_education_level": "bachelor",
                "recommended_experience_months": 24,
            },
        },
        status="active",
        source_type="manual",
    )
    second_role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"云原生 AI 工程师 {suffix}",
        description="负责云原生 AI 平台",
        definition_payload={
            "role_name": f"云原生 AI 工程师 {suffix}",
            "required_capability_ids": [
                str(capabilities["Python"].id),
                str(capabilities["Kubernetes"].id),
            ],
            "bonus_capability_ids": [],
        },
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload=first_role.definition_payload,
        source_snapshot={},
        evidence_summary={},
        confidence=Decimal("0.9"),
        review_status="published",
        created_by_user_id=admin.id,
        reviewed_by_user_id=admin.id,
        reviewed_at=now,
    )
    db_session.add_all([first_role, second_role, proposal])
    await db_session.flush()

    catalog_version_no = (
        await db_session.scalar(select(func.max(CatalogVersion.version_no))) or 0
    ) + 1
    graph_version_no = (
        await db_session.scalar(select(func.max(GraphVersion.version_no))) or 0
    ) + 1
    catalog = CatalogVersion(
        id=uuid4(),
        version_no=catalog_version_no,
        status="published",
        is_current=True,
        created_by_user_id=admin.id,
        summary={"source": "matching-test"},
        published_at=now.replace(tzinfo=None),
    )
    graph = GraphVersion(
        id=uuid4(),
        version_no=graph_version_no,
        source_proposal_id=proposal.id,
        catalog_version_id=catalog.id,
        job_role_id=first_role.id,
        status="published",
        is_current=True,
        snapshot={"job_role": {"id": str(first_role.id)}},
        attempt_count=1,
        created_by_user_id=admin.id,
        published_at=now,
    )
    db_session.add_all([catalog, graph])
    await db_session.flush()
    db_session.add_all(
        [
            *[
                CatalogVersionItem(
                    id=uuid4(),
                    catalog_version_id=catalog.id,
                    item_type="capability",
                    capability_id=capability.id,
                    change_type="added",
                )
                for capability in capabilities.values()
            ],
            *[
                CatalogVersionItem(
                    id=uuid4(),
                    catalog_version_id=catalog.id,
                    item_type="job_role",
                    job_role_id=role.id,
                    change_type="added",
                )
                for role in (first_role, second_role)
            ],
        ]
    )
    db_session.add_all(
        [
            JobRoleCapability(
                job_role_id=first_role.id,
                capability_id=capabilities["Python"].id,
                requirement_type="required",
                importance=Decimal("1"),
                source_candidate_id=proposal.id,
            ),
            JobRoleCapability(
                job_role_id=first_role.id,
                capability_id=capabilities["PyTorch"].id,
                requirement_type="required",
                importance=Decimal("1"),
                source_candidate_id=proposal.id,
            ),
            JobRoleCapability(
                job_role_id=first_role.id,
                capability_id=capabilities["Docker"].id,
                requirement_type="bonus",
                importance=Decimal("0.5"),
                source_candidate_id=proposal.id,
            ),
            JobRoleCapability(
                job_role_id=second_role.id,
                capability_id=capabilities["Python"].id,
                requirement_type="required",
                importance=Decimal("1"),
                source_candidate_id=proposal.id,
            ),
            JobRoleCapability(
                job_role_id=second_role.id,
                capability_id=capabilities["Kubernetes"].id,
                requirement_type="required",
                importance=Decimal("1"),
                source_candidate_id=proposal.id,
            ),
        ]
    )
    resume_skills = {
        name: _resume_skill(profile, capability, strength)
        for name, capability, strength in [
            ("Python", capabilities["Python"], "work"),
            ("PyTorch", capabilities["PyTorch"], "project"),
            ("Docker", capabilities["Docker"], "mention"),
        ]
    }
    unmapped = ResumeSkill(
        id=uuid4(),
        profile_id=profile.id,
        capability_id=None,
        raw_name="FutureSkill",
        normalized_name="futureskill",
        evidence_strength="mention",
        mapping_method="unmapped",
        mapping_status="unmapped",
        source="manual",
        confidence=Decimal("1"),
        user_confirmed=True,
    )
    db_session.add_all([*resume_skills.values(), unmapped])
    await db_session.flush()
    return ServiceMatchContext(
        applicant=applicant,
        other_applicant=other_applicant,
        admin=admin,
        hr=hr,
        resume=resume,
        profile=profile,
        catalog=catalog,
        graph=graph,
        proposal=proposal,
        domain=domain,
        capabilities=capabilities,
        job_roles=(first_role, second_role),
        resume_skills=resume_skills,
    )


def _user(role: str, username: str, now: datetime) -> User:
    return User(
        id=uuid4(),
        username=username,
        username_normalized=username,
        password_hash="hash",
        display_name=f"{role} matching user",
        role=role,
        password_changed_at=now,
    )


def _resume_skill(
    profile: ResumeProfile,
    capability: Capability,
    evidence_strength: str,
) -> ResumeSkill:
    return ResumeSkill(
        id=uuid4(),
        profile_id=profile.id,
        capability_id=capability.id,
        raw_name=capability.canonical_name,
        normalized_name=capability.canonical_name.casefold(),
        evidence_strength=evidence_strength,
        evidence_quote=f"使用 {capability.canonical_name} 完成项目",
        mapping_method="manual",
        mapping_status="mapped",
        source="manual",
        confidence=Decimal("1"),
        user_confirmed=True,
    )
