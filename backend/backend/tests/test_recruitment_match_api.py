from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.processing.models import ProcessingRun
from app.recruitment.models import (
    CandidateProfile,
    CandidateSkill,
    RecruitmentCandidate,
    RecruitmentMatchRun,
    RecruitmentProject,
)


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def _matching_project(db_session, owner):
    domain = Domain(
        id=uuid4(),
        code=f"match-{uuid4().hex[:8]}",
        name="软件工程",
        status="active",
        sort_order=0,
    )
    db_session.add(domain)
    await db_session.flush()
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        skill_type="language",
        status="active",
        source_type="manual",
    )
    db_session.add(capability)
    await db_session.flush()
    requirement = {
        "capability_id": str(capability.id),
        "canonical_name": capability.canonical_name,
        "skill_type": capability.skill_type,
        "domain": {
            "id": str(domain.id),
            "code": domain.code,
            "name": domain.name,
        },
        "raw_name": "Python",
        "requirement_type": "required",
        "importance": 1.0,
        "mapping_method": "manual",
        "evidence_quote": None,
        "confidence": None,
    }
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=owner.id,
        title="AI 招聘匹配",
        jd_source_type="text",
        jd_source_text="熟练掌握 Python",
        jd_parse_status="ready",
        jd_draft_payload={},
        confirmed_requirement_snapshot={
            "schema_version": "recruitment_requirements_v1",
            "revision_no": 1,
            "confirmed_at": datetime.now(UTC).isoformat(),
            "confirmed_by_user_id": str(owner.id),
            "source": {"type": "text", "text_sha256": "c" * 64},
            "source_text": "熟练掌握 Python",
            "job_title": "AI 应用工程师",
            "summary": None,
            "responsibilities": [],
            "minimum_education_level": "bachelor",
            "recommended_experience_months": 24,
            "requirements": [requirement],
            "unmapped_skills": [],
            "validation_warnings": [],
        },
        confirmed_requirement_sha256="d" * 64,
        requirements_revision=1,
    )
    db_session.add(project)
    await db_session.flush()
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_candidates",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=owner.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="completed",
        pipeline_version="recruitment_candidate_parse_v1",
        total_count=3,
        processed_count=3,
        success_count=2,
        failed_count=1,
        progress_percent=Decimal("100"),
        input_snapshot={},
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()
    candidates = []
    profiles = []
    for index, (name, status) in enumerate(
        (("A 候选人", "ready"), ("B 候选人", "ready"), ("C 候选人", "failed"))
    ):
        stored_file = StoredFile(
            id=uuid4(),
            uploaded_by_user_id=owner.id,
            original_name=f"{name}.pdf",
            storage_key=f"resume/{uuid4()}.pdf",
            media_type="application/pdf",
            extension="pdf",
            size_bytes=10,
            sha256=f"{index + 1}" * 64,
            category="resume",
            scan_status="not_required",
            status="attached",
        )
        db_session.add(stored_file)
        await db_session.flush()
        candidate = RecruitmentCandidate(
            id=uuid4(),
            project_id=project.id,
            file_id=stored_file.id,
            display_name=name,
            parse_status=status,
            latest_run_id=run.id,
            created_by_user_id=owner.id,
        )
        db_session.add(candidate)
        await db_session.flush()
        candidates.append(candidate)
        if status == "ready":
            profile = CandidateProfile(
                id=uuid4(),
                candidate_id=candidate.id,
                extraction_version="resume_parse_v1",
                extracted_text="使用 Python 开发项目",
                text_extraction_method="pdf_text",
                highest_education_level="bachelor",
                total_experience_months=24,
                structured_payload={"validation_warnings": []},
                created_by_run_id=run.id,
            )
            db_session.add(profile)
            await db_session.flush()
            profiles.append(profile)
            if name.startswith("A"):
                db_session.add(
                    CandidateSkill(
                        id=uuid4(),
                        profile_id=profile.id,
                        capability_id=capability.id,
                        raw_name="Python",
                        normalized_name="python",
                        proficiency="intermediate",
                        explicit_experience_months=24,
                        evidence_strength="work",
                        evidence_quote="使用 Python 开发项目",
                        evidence_start=0,
                        evidence_end=13,
                        mapping_method="canonical_exact",
                        mapping_status="mapped",
                        confidence=Decimal("0.95"),
                    )
                )
                await db_session.flush()
    return project, candidates, profiles


async def test_match_run_is_deterministic_idempotent_and_queryable(
    client,
    db_session,
    make_user,
) -> None:
    owner, password = await make_user(role="hr", username="match_owner")
    _other, other_password = await make_user(role="hr", username="match_other")
    project, candidates, _profiles = await _matching_project(db_session, owner)
    csrf = await _login(client, owner.username, password)
    url = f"/api/v1/recruitment-projects/{project.id}/match-runs"

    first = await client.post(url, headers={"X-CSRF-Token": csrf})
    duplicate = await client.post(url, headers={"X-CSRF-Token": csrf})

    assert first.status_code == 200
    assert first.json()["data"]["reused"] is False
    assert duplicate.json()["data"]["reused"] is True
    assert duplicate.json()["data"]["run"]["id"] == first.json()["data"]["run"]["id"]
    assert [
        item["candidate"]["display_name"] for item in first.json()["data"]["items"]
    ] == [
        "A 候选人",
        "B 候选人",
    ]
    assert first.json()["data"]["run"]["skipped_count"] == 1
    assert first.json()["data"]["items"][0]["match_level"] == "high"
    run_id = first.json()["data"]["run"]["id"]
    history = await client.get(url)
    results = await client.get(f"{url}/{run_id}/results")
    detail = await client.get(f"{url}/{run_id}/results/{candidates[0].id}")
    assert history.json()["data"][0]["id"] == run_id
    assert [item["rank"] for item in results.json()["data"]] == [1, 2]
    assert detail.json()["data"]["requirements_snapshot"]["job_title"] == (
        "AI 应用工程师"
    )
    assert (
        detail.json()["data"]["matched_capabilities"][0]["canonical_name"] == "Python"
    )
    assert (
        await db_session.scalar(
            select(RecruitmentMatchRun).where(
                RecruitmentMatchRun.project_id == project.id
            )
        )
    ).result_count == 2

    await _login(client, "match_other", other_password)
    hidden = await client.get(f"{url}/{run_id}/results")
    assert hidden.status_code == 404


async def test_match_run_rejects_unready_candidates(
    client,
    db_session,
    make_user,
) -> None:
    owner, password = await make_user(role="hr", username="match_unready")
    project, candidates, _profiles = await _matching_project(db_session, owner)
    candidates[1].parse_status = "uploaded"
    await db_session.flush()
    csrf = await _login(client, owner.username, password)

    response = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/match-runs",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATES_NOT_READY"


async def test_match_run_requires_confirmation(
    client,
    db_session,
    make_user,
) -> None:
    owner, password = await make_user(role="hr", username="match_inputs")
    project, _candidates, _profiles = await _matching_project(db_session, owner)
    csrf = await _login(client, owner.username, password)
    url = f"/api/v1/recruitment-projects/{project.id}/match-runs"
    project.requirements_revision = 0
    project.confirmed_requirement_sha256 = None
    project.confirmed_requirement_snapshot = {}
    await db_session.flush()

    unconfirmed = await client.post(url, headers={"X-CSRF-Token": csrf})
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["error"]["code"] == "REQUIREMENTS_NOT_CONFIRMED"


async def test_match_run_rejects_ready_candidate_without_profile(
    client,
    db_session,
    make_user,
) -> None:
    owner, password = await make_user(role="hr", username="match_missing_profile")
    project, _candidates, profiles = await _matching_project(db_session, owner)
    await db_session.delete(profiles[1])
    await db_session.flush()
    csrf = await _login(client, owner.username, password)

    response = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/match-runs",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_PROFILE_MISSING"
