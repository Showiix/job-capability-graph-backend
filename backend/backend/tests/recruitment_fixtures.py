from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.auth.models import User
from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.processing.models import ProcessingRun
from app.recruitment.models import (
    CandidateProfile,
    CandidateSkill,
    RecruitmentCandidate,
    RecruitmentMatchResult,
    RecruitmentMatchRun,
    RecruitmentProject,
)


@dataclass
class RecruitmentDependencies:
    hr: User
    project: RecruitmentProject
    candidate: RecruitmentCandidate
    profile: CandidateProfile
    capability: Capability


async def make_recruitment_dependencies(db_session) -> RecruitmentDependencies:
    suffix = uuid4().hex[:12]
    now = datetime.now(UTC)
    hr = User(
        id=uuid4(),
        username=f"hr_{suffix}",
        username_normalized=f"hr_{suffix}",
        password_hash="hash",
        display_name="Recruitment HR",
        role="hr",
        password_changed_at=now,
    )
    resume_file = _stored_file(hr, "candidate.pdf", "resume")
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=hr.id,
        title="AI 应用工程师招聘",
        description="内部招聘项目",
        jd_source_type="text",
        jd_source_text="负责 Python 和 PyTorch 开发",
        jd_parse_status="ready",
        jd_draft_payload={},
        confirmed_requirement_snapshot={"schema_version": "recruitment_jd_v1"},
        confirmed_requirement_sha256="a" * 64,
        requirements_revision=1,
    )
    candidate = RecruitmentCandidate(
        id=uuid4(),
        project_id=project.id,
        file_id=resume_file.id,
        display_name="张三",
        parse_status="ready",
        created_by_user_id=hr.id,
    )
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_candidates",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=hr.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="completed",
        pipeline_version="recruitment_candidate_parse_v1",
        total_count=1,
        processed_count=1,
        success_count=1,
        failed_count=0,
        progress_percent=Decimal("100"),
        input_snapshot={"candidate_ids": [str(candidate.id)]},
        result_summary={},
        started_at=now,
        completed_at=now,
    )
    profile = CandidateProfile(
        id=uuid4(),
        candidate_id=candidate.id,
        extraction_version="resume_parse_v1",
        extracted_text="使用 Python 完成项目",
        text_extraction_method="pdf_text",
        highest_education_level="bachelor",
        total_experience_months=24,
        structured_payload={},
        created_by_run_id=run.id,
    )
    domain = Domain(
        id=uuid4(),
        code=f"recruitment-{suffix}",
        name="Recruitment Domain",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"Python {suffix}",
        skill_type="technical",
        status="active",
        source_type="manual",
    )
    db_session.add_all([hr, resume_file, domain])
    await db_session.flush()
    db_session.add_all([project, capability])
    await db_session.flush()
    db_session.add(candidate)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    candidate.latest_run_id = run.id
    db_session.add(profile)
    await db_session.flush()
    return RecruitmentDependencies(hr, project, candidate, profile, capability)


def make_candidate_skill(
    context: RecruitmentDependencies,
    **overrides,
) -> CandidateSkill:
    values = {
        "id": uuid4(),
        "profile_id": context.profile.id,
        "capability_id": context.capability.id,
        "raw_name": "Python",
        "normalized_name": "python",
        "proficiency": "intermediate",
        "explicit_experience_months": 24,
        "evidence_strength": "project",
        "evidence_quote": "使用 Python 完成项目",
        "evidence_start": 0,
        "evidence_end": 13,
        "mapping_method": "canonical_exact",
        "mapping_status": "mapped",
        "confidence": Decimal("0.9500"),
    }
    values.update(overrides)
    return CandidateSkill(**values)


def make_recruitment_match_run(
    context: RecruitmentDependencies,
    **overrides,
) -> RecruitmentMatchRun:
    values = {
        "id": uuid4(),
        "project_id": context.project.id,
        "requirements_revision": 1,
        "requirements_sha256": "a" * 64,
        "candidate_selection_sha256": "b" * 64,
        "weight_version": "match_weights_v1",
        "weight_snapshot": {"algorithm": "exact_capability_match_v1"},
        "requirements_snapshot": {"schema_version": "recruitment_jd_v1"},
        "skipped_candidates": [],
        "result_count": 1,
        "skipped_count": 0,
        "high_count": 1,
        "medium_count": 0,
        "low_count": 0,
        "created_by_user_id": context.hr.id,
    }
    values.update(overrides)
    return RecruitmentMatchRun(**values)


def make_recruitment_match_result(
    context: RecruitmentDependencies,
    run: RecruitmentMatchRun,
    **overrides,
) -> RecruitmentMatchResult:
    values = {
        "match_run_id": run.id,
        "candidate_id": context.candidate.id,
        "candidate_profile_id": context.profile.id,
        "rank": 1,
        "total_score": Decimal("88.25"),
        "match_level": "high",
        "dimension_scores": {},
        "matched_capabilities": [],
        "missing_capabilities": [],
        "gap_summary": {},
        "candidate_snapshot": {"id": str(context.candidate.id)},
    }
    values.update(overrides)
    return RecruitmentMatchResult(**values)


def _stored_file(user: User, name: str, category: str) -> StoredFile:
    extension = name.rsplit(".", 1)[-1]
    return StoredFile(
        id=uuid4(),
        uploaded_by_user_id=user.id,
        original_name=name,
        storage_key=f"{category}/{uuid4()}.{extension}",
        media_type="application/pdf",
        extension=extension,
        size_bytes=32,
        sha256=uuid4().hex * 2,
        category=category,
        scan_status="not_required",
        status="attached",
    )
