from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.auth.models import User
from app.catalog.models import CatalogVersion, Domain, JobRole
from app.files.models import StoredFile
from app.graph.models import GraphVersion
from app.matching.models import MatchResult, MatchRun
from app.processing.models import ProcessingRun
from app.resumes.models import Resume, ResumeProfile
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
