from decimal import Decimal
from uuid import uuid4

from app.files.models import StoredFile
from app.processing.models import ProcessingRun
from app.recruitment.models import RecruitmentCandidate, RecruitmentProject


async def _login(client, username: str, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


async def _private_recruitment_data(db_session, owner):
    jd_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=owner.id,
        original_name="jd.txt",
        storage_key=f"jd/{uuid4()}.txt",
        media_type="text/plain",
        extension="txt",
        size_bytes=10,
        sha256="a" * 64,
        category="jd",
        scan_status="not_required",
        status="attached",
    )
    candidate_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=owner.id,
        original_name="candidate.pdf",
        storage_key=f"resume/{uuid4()}.pdf",
        media_type="application/pdf",
        extension="pdf",
        size_bytes=10,
        sha256="b" * 64,
        category="resume",
        scan_status="not_required",
        status="attached",
    )
    db_session.add_all([jd_file, candidate_file])
    await db_session.flush()
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=owner.id,
        title="私有招聘项目",
        jd_source_type="file",
        jd_file_id=jd_file.id,
        jd_parse_status="processing",
        jd_draft_payload={},
        confirmed_requirement_snapshot={},
    )
    db_session.add(project)
    await db_session.flush()
    candidate = RecruitmentCandidate(
        id=uuid4(),
        project_id=project.id,
        file_id=candidate_file.id,
        display_name="候选人",
        parse_status="uploaded",
        created_by_user_id=owner.id,
    )
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_jd",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=owner.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_jd_parse_v1",
        total_count=1,
        progress_percent=Decimal("0"),
        input_snapshot={},
        result_summary={},
    )
    db_session.add_all([candidate, run])
    await db_session.flush()
    project.latest_jd_run_id = run.id
    await db_session.flush()
    return project, run, jd_file, candidate_file


async def test_project_run_visibility_is_inherited_from_project(
    client,
    db_session,
    make_user,
) -> None:
    owner, owner_password = await make_user(role="hr", username="run_owner_hr")
    _other, other_password = await make_user(role="hr", username="run_other_hr")
    _applicant, applicant_password = await make_user(
        role="applicant", username="run_applicant"
    )
    _admin, admin_password = await make_user(role="admin", username="run_admin")
    _project, run, _jd_file, _candidate_file = await _private_recruitment_data(
        db_session, owner
    )

    await _login(client, owner.username, owner_password)
    own = await client.get(f"/api/v1/processing-runs/{run.id}")
    assert own.status_code == 200
    assert str(run.id) in {
        item["id"]
        for item in (await client.get("/api/v1/processing-runs")).json()["data"]
    }

    await _login(client, "run_other_hr", other_password)
    assert (await client.get(f"/api/v1/processing-runs/{run.id}")).status_code == 404

    await _login(client, "run_applicant", applicant_password)
    assert (await client.get(f"/api/v1/processing-runs/{run.id}")).status_code == 404

    await _login(client, "run_admin", admin_password)
    assert (await client.get(f"/api/v1/processing-runs/{run.id}")).status_code == 200


async def test_recruitment_files_are_visible_only_through_project_ownership(
    client,
    db_session,
    make_user,
) -> None:
    owner, owner_password = await make_user(role="hr", username="file_project_owner")
    _other, other_password = await make_user(role="hr", username="file_other_hr")
    _applicant, applicant_password = await make_user(
        role="applicant", username="file_applicant"
    )
    _admin, admin_password = await make_user(role="admin", username="file_admin")
    _project, _run, jd_file, candidate_file = await _private_recruitment_data(
        db_session, owner
    )

    await _login(client, owner.username, owner_password)
    assert (await client.get(f"/api/v1/files/{jd_file.id}")).status_code == 200
    assert (await client.get(f"/api/v1/files/{candidate_file.id}")).status_code == 200

    for username, password in (
        ("file_other_hr", other_password),
        ("file_applicant", applicant_password),
    ):
        await _login(client, username, password)
        jd_hidden = await client.get(f"/api/v1/files/{jd_file.id}")
        candidate_hidden = await client.get(f"/api/v1/files/{candidate_file.id}")
        assert jd_hidden.status_code == 404
        assert jd_hidden.json()["error"]["code"] == "RESOURCE_NOT_OWNED"
        assert candidate_hidden.status_code == 404

    await _login(client, "file_admin", admin_password)
    assert (await client.get(f"/api/v1/files/{jd_file.id}")).status_code == 200
    assert (await client.get(f"/api/v1/files/{candidate_file.id}")).status_code == 200


async def test_cors_preflight_allows_idempotency_key(client) -> None:
    response = await client.options(
        "/api/v1/recruitment-projects/example/jd",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "content-type,x-csrf-token,idempotency-key"
            ),
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed
