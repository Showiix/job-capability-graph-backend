from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.processing.models import ProcessingRun
from app.resumes.models import Resume, ResumeProfile, ResumeSkill


async def make_user(db_session, *, role: str = "applicant") -> User:
    suffix = uuid4().hex[:12]
    value = User(
        id=uuid4(),
        username=f"resume_{suffix}",
        username_normalized=f"resume_{suffix}",
        password_hash="hash",
        display_name="Resume User",
        role=role,
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def make_file(db_session, user, *, suffix: str = "pdf") -> StoredFile:
    value = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=user.id,
        original_name=f"resume.{suffix}",
        storage_key=f"resume/{uuid4()}.{suffix}",
        media_type=(
            "application/pdf"
            if suffix == "pdf"
            else "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        extension=suffix,
        size_bytes=16,
        sha256="a" * 64,
        category="resume",
        scan_status="not_required",
        status="attached",
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def make_resume(db_session, user) -> Resume:
    stored_file = await make_file(db_session, user)
    value = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=stored_file.id,
        display_name="我的简历.pdf",
        source_language="zh-CN",
        parse_status="uploaded",
        created_by_user_id=user.id,
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def make_run(db_session, user, resume) -> ProcessingRun:
    value = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=resume.id,
        created_by_user_id=user.id,
        owner_scope_type="user",
        owner_scope_id=user.id,
        status="pending",
        pipeline_version="resume_parse_v1",
        total_count=1,
        input_snapshot={"resume_id": str(resume.id)},
        result_summary={},
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def make_capability(db_session) -> Capability:
    suffix = uuid4().hex[:12]
    domain = Domain(
        id=uuid4(),
        code=f"resume-{suffix}",
        name="Resume Test",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"Python {suffix}",
        skill_type="tool",
        status="active",
        source_type="bootstrap",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()
    return capability


def extracted_profile(
    resume,
    user,
    run,
    *,
    version_no: int = 1,
    extraction_version: str = "resume_parse_v1",
    status: str = "candidate",
    confirmed_at=None,
    **overrides,
) -> ResumeProfile:
    values = {
        "id": uuid4(),
        "resume_id": resume.id,
        "base_profile_id": None,
        "version_no": version_no,
        "extraction_version": extraction_version,
        "profile_source": "extracted",
        "extracted_text": "Python 项目经验",
        "text_extraction_method": "pdf_text",
        "highest_education_level": "bachelor",
        "total_experience_months": 12,
        "structured_payload": {"summary": "Python"},
        "status": status,
        "created_by_run_id": run.id,
        "created_by_user_id": user.id,
        "confirmed_at": confirmed_at,
    }
    values.update(overrides)
    return ResumeProfile(**values)


def manual_profile(
    resume,
    user,
    base,
    *,
    version_no: int = 2,
    status: str = "draft",
    confirmed_at=None,
    **overrides,
) -> ResumeProfile:
    values = {
        "id": uuid4(),
        "resume_id": resume.id,
        "base_profile_id": base.id,
        "version_no": version_no,
        "extraction_version": base.extraction_version,
        "profile_source": "manual_revision",
        "extracted_text": base.extracted_text,
        "text_extraction_method": base.text_extraction_method,
        "highest_education_level": base.highest_education_level,
        "total_experience_months": base.total_experience_months,
        "structured_payload": dict(base.structured_payload),
        "status": status,
        "created_by_run_id": None,
        "created_by_user_id": user.id,
        "confirmed_at": confirmed_at,
    }
    values.update(overrides)
    return ResumeProfile(**values)


def resume_skill(
    profile,
    *,
    capability=None,
    source: str = "llm",
    raw_name: str = "Python",
    normalized_name: str = "python",
    **overrides,
) -> ResumeSkill:
    is_mapped = capability is not None
    values = {
        "id": uuid4(),
        "profile_id": profile.id,
        "capability_id": capability.id if is_mapped else None,
        "raw_name": raw_name,
        "normalized_name": normalized_name,
        "proficiency": "intermediate",
        "explicit_experience_months": 12,
        "evidence_strength": "project",
        "evidence_quote": "Python",
        "evidence_start": 0,
        "evidence_end": 6,
        "mapping_method": (
            "canonical_exact" if is_mapped and source == "llm" else "unmapped"
        ),
        "mapping_status": "mapped" if is_mapped else "unmapped",
        "source": source,
        "confidence": Decimal("0.9000"),
        "user_confirmed": False,
    }
    if source == "manual":
        values.update(
            mapping_method="manual" if is_mapped else "unmapped",
            evidence_strength="mention",
            evidence_quote=None,
            evidence_start=None,
            evidence_end=None,
            confidence=Decimal("1.0000"),
            user_confirmed=True,
        )
    values.update(overrides)
    return ResumeSkill(**values)


async def assert_integrity_error(db_session, value) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(value)
            await db_session.flush()


async def profile_context(db_session, user):
    resume = await make_resume(db_session, user)
    run = await make_run(db_session, user, resume)
    profile = extracted_profile(resume, user, run)
    db_session.add(profile)
    await db_session.flush()
    return resume, run, profile


async def test_resume_profile_skill_happy_path(db_session, user) -> None:
    resume, run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    skill = resume_skill(profile, capability=capability)
    db_session.add(skill)
    await db_session.flush()

    assert (await db_session.get(Resume, resume.id)).file_id == resume.file_id
    assert (await db_session.get(ResumeProfile, profile.id)).created_by_run_id == run.id
    assert (await db_session.get(ResumeSkill, skill.id)).capability_id == capability.id


async def test_resume_file_id_is_unique(db_session, user) -> None:
    resume = await make_resume(db_session, user)
    duplicate = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=resume.file_id,
        display_name="重复.pdf",
        parse_status="uploaded",
        created_by_user_id=user.id,
    )

    await assert_integrity_error(db_session, duplicate)


async def test_resume_creator_must_equal_owner(db_session, user) -> None:
    other = await make_user(db_session)
    stored_file = await make_file(db_session, user)
    invalid = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=stored_file.id,
        display_name="错误所有者.pdf",
        parse_status="uploaded",
        created_by_user_id=other.id,
    )

    await assert_integrity_error(db_session, invalid)


async def test_resume_archived_status_requires_archived_at(db_session, user) -> None:
    archived_file = await make_file(db_session, user)
    archived_without_time = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=archived_file.id,
        display_name="归档.pdf",
        parse_status="archived",
        created_by_user_id=user.id,
    )
    ready_file = await make_file(db_session, user)
    ready_with_time = Resume(
        id=uuid4(),
        owner_user_id=user.id,
        file_id=ready_file.id,
        display_name="未归档.pdf",
        parse_status="ready",
        created_by_user_id=user.id,
        archived_at=datetime.now(UTC),
    )

    await assert_integrity_error(db_session, archived_without_time)
    await assert_integrity_error(db_session, ready_with_time)


async def test_profile_version_is_positive_and_unique_per_resume(
    db_session,
    user,
) -> None:
    resume, run, profile = await profile_context(db_session, user)
    zero = extracted_profile(
        resume,
        user,
        run,
        version_no=0,
        extraction_version="resume_parse_zero",
    )
    duplicate = manual_profile(resume, user, profile, version_no=1)

    await assert_integrity_error(db_session, zero)
    await assert_integrity_error(db_session, duplicate)


async def test_extracted_profile_requires_run_and_candidate_like_status(
    db_session,
    user,
) -> None:
    resume, run, base = await profile_context(db_session, user)
    invalid_values = [
        extracted_profile(
            resume,
            user,
            run,
            version_no=2,
            extraction_version="missing-run",
            created_by_run_id=None,
        ),
        extracted_profile(
            resume,
            user,
            run,
            version_no=3,
            extraction_version="has-base",
            base_profile_id=base.id,
        ),
        extracted_profile(
            resume,
            user,
            run,
            version_no=4,
            extraction_version="draft-extracted",
            status="draft",
        ),
    ]

    for invalid in invalid_values:
        await assert_integrity_error(db_session, invalid)


async def test_manual_profile_requires_base_and_draft_like_status(
    db_session,
    user,
) -> None:
    resume, run, base = await profile_context(db_session, user)
    invalid_values = [
        manual_profile(resume, user, base, version_no=2, created_by_run_id=run.id),
        manual_profile(resume, user, base, version_no=3, base_profile_id=None),
        manual_profile(resume, user, base, version_no=4, status="candidate"),
    ]

    for invalid in invalid_values:
        await assert_integrity_error(db_session, invalid)


async def test_profile_confirmed_timestamp_matches_status(db_session, user) -> None:
    resume, run, _profile = await profile_context(db_session, user)
    confirmed_without_time = extracted_profile(
        resume,
        user,
        run,
        version_no=2,
        extraction_version="confirmed-no-time",
        status="confirmed",
    )
    candidate_with_time = extracted_profile(
        resume,
        user,
        run,
        version_no=3,
        extraction_version="candidate-with-time",
        confirmed_at=datetime.now(UTC),
    )

    await assert_integrity_error(db_session, confirmed_without_time)
    await assert_integrity_error(db_session, candidate_with_time)


async def test_only_one_confirmed_profile_per_resume(db_session, user) -> None:
    resume = await make_resume(db_session, user)
    run = await make_run(db_session, user, resume)
    confirmed_at = datetime.now(UTC)
    confirmed = extracted_profile(
        resume,
        user,
        run,
        status="confirmed",
        confirmed_at=confirmed_at,
    )
    db_session.add(confirmed)
    await db_session.flush()
    duplicate = manual_profile(
        resume,
        user,
        confirmed,
        status="confirmed",
        confirmed_at=confirmed_at,
    )

    await assert_integrity_error(db_session, duplicate)


async def test_only_one_extracted_profile_per_version(db_session, user) -> None:
    resume, run, _profile = await profile_context(db_session, user)
    duplicate = extracted_profile(resume, user, run, version_no=2)

    await assert_integrity_error(db_session, duplicate)


async def test_mapped_skill_requires_capability(db_session, user) -> None:
    _resume, _run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    mapped_without_target = resume_skill(
        profile,
        capability=None,
        mapping_status="mapped",
        mapping_method="canonical_exact",
    )
    unmapped_with_target = resume_skill(
        profile,
        capability=capability,
        normalized_name="python-alt",
        mapping_status="unmapped",
        mapping_method="unmapped",
    )

    await assert_integrity_error(db_session, mapped_without_target)
    await assert_integrity_error(db_session, unmapped_with_target)


async def test_llm_skill_requires_quote_offsets_and_unconfirmed(
    db_session,
    user,
) -> None:
    _resume, _run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    invalid_values = [
        resume_skill(profile, capability=capability, evidence_quote=None),
        resume_skill(profile, capability=capability, evidence_start=None),
        resume_skill(profile, capability=capability, evidence_end=None),
        resume_skill(profile, capability=capability, user_confirmed=True),
    ]

    for invalid in invalid_values:
        await assert_integrity_error(db_session, invalid)


async def test_manual_skill_requires_user_confirmation(db_session, user) -> None:
    _resume, _run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    invalid = resume_skill(
        profile,
        capability=capability,
        source="manual",
        user_confirmed=False,
    )

    await assert_integrity_error(db_session, invalid)


async def test_skill_enums_confidence_and_offsets_are_constrained(
    db_session,
    user,
) -> None:
    _resume, _run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    invalid_overrides = [
        {"proficiency": "expert"},
        {"explicit_experience_months": -1},
        {"evidence_strength": "guess"},
        {"mapping_method": "semantic"},
        {"mapping_status": "pending"},
        {"source": "import"},
        {"confidence": Decimal("-0.1000")},
        {"confidence": Decimal("1.1000")},
        {"evidence_start": -1},
        {"evidence_end": 0},
    ]

    for overrides in invalid_overrides:
        invalid = resume_skill(profile, capability=capability, **overrides)
        await assert_integrity_error(db_session, invalid)


async def test_mapped_capability_is_unique_per_profile(db_session, user) -> None:
    _resume, _run, profile = await profile_context(db_session, user)
    capability = await make_capability(db_session)
    first = resume_skill(profile, capability=capability)
    db_session.add(first)
    await db_session.flush()
    duplicate = resume_skill(
        profile,
        capability=capability,
        raw_name="Py",
        normalized_name="py",
    )

    await assert_integrity_error(db_session, duplicate)
