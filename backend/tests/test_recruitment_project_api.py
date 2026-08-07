from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingRun
from app.recruitment.models import RecruitmentProject


async def _create_project(client, csrf: str, title: str = "AI 招聘") -> dict:
    response = await client.post(
        "/api/v1/recruitment-projects",
        json={"title": title, "description": "比赛演示项目"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_project_visibility_for_hr_admin_and_applicant(
    client,
    make_user,
    login,
) -> None:
    hr_a, hr_a_password = await make_user(role="hr", username="project_hr_a")
    _hr_b, hr_b_password = await make_user(role="hr", username="project_hr_b")
    _admin, admin_password = await make_user(role="admin", username="project_admin")
    _applicant, applicant_password = await make_user(
        role="applicant", username="project_applicant"
    )

    csrf = await login(hr_a.username, hr_a_password)
    project = await _create_project(client, csrf)
    assert project["confirmed_requirement_summary"] == {}
    listing = await client.get("/api/v1/recruitment-projects?q=AI")
    assert [item["id"] for item in listing.json()["data"]] == [project["id"]]

    await login("project_hr_b", hr_b_password)
    hidden = await client.get(f"/api/v1/recruitment-projects/{project['id']}")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "RESOURCE_NOT_OWNED"
    assert (await client.get("/api/v1/recruitment-projects")).json()["data"] == []

    await login("project_admin", admin_password)
    visible = await client.get(f"/api/v1/recruitment-projects/{project['id']}")
    assert visible.status_code == 200
    assert visible.json()["data"]["owner_user_id"] == str(hr_a.id)

    applicant_csrf = await login("project_applicant", applicant_password)
    denied = await client.post(
        "/api/v1/recruitment-projects",
        json={"title": "不能创建"},
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "RECRUITMENT_ROLE_REQUIRED"
    masked = await client.get(f"/api/v1/recruitment-projects/{project['id']}")
    assert masked.status_code == 404


async def test_text_jd_submission_is_idempotent_and_blocks_parallel_run(
    client,
    make_user,
    login,
    db_session,
    monkeypatch,
) -> None:
    hr, password = await make_user(role="hr", username="jd_submit_hr")
    csrf = await login(hr.username, password)
    project = await _create_project(client, csrf)
    monkeypatch.setattr(
        "app.recruitment.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="jd-task"),
    )
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "jd-text-key"}

    first = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        data={"text": "负责 Python 开发"},
        headers=headers,
    )
    duplicate = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        data={"text": "负责 Python 开发"},
        headers=headers,
    )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json() == first.json()
    run_id = first.json()["data"]["run_id"]
    run = await db_session.get(ProcessingRun, run_id)
    stored_project = await db_session.get(RecruitmentProject, project["id"])
    assert run is not None and run.status == "pending"
    assert stored_project.jd_source_type == "text"
    assert stored_project.jd_source_text == "负责 Python 开发"
    assert stored_project.latest_jd_run_id == run.id

    conflict = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        data={"text": "负责 Java 开发"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    active = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        data={"text": "负责 Go 开发"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "another-key"},
    )
    assert active.status_code == 409
    assert active.json()["error"]["code"] == "RECRUITMENT_JD_PROCESSING"


async def test_jd_submission_validates_source_and_file_limit(
    client,
    make_user,
    login,
    monkeypatch,
    tmp_path,
) -> None:
    hr, password = await make_user(role="hr", username="jd_invalid_hr")
    csrf = await login(hr.username, password)
    project = await _create_project(client, csrf)
    storage = FileStorage(tmp_path / "files")
    monkeypatch.setattr("app.recruitment.service.storage", storage)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "invalid-jd"}

    missing = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        headers=headers,
    )
    both = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        data={"text": "Python"},
        files={"file": ("jd.txt", BytesIO(b"Python"), "text/plain")},
        headers=headers,
    )
    too_large = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        files={
            "file": (
                "jd.txt",
                BytesIO(b"x" * (10 * 1024 * 1024 + 1)),
                "text/plain",
            )
        },
        headers=headers,
    )

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "RECRUITMENT_JD_INPUT_INVALID"
    assert both.status_code == 422
    assert both.json()["error"]["code"] == "RECRUITMENT_JD_INPUT_INVALID"
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "RECRUITMENT_JD_TOO_LARGE"


async def test_txt_jd_submission_attaches_private_file(
    client,
    make_user,
    login,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    hr, password = await make_user(role="hr", username="jd_file_hr")
    csrf = await login(hr.username, password)
    project = await _create_project(client, csrf)
    storage = FileStorage(tmp_path / "files")
    monkeypatch.setattr("app.recruitment.service.storage", storage)
    monkeypatch.setattr(
        "app.recruitment.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="jd-file-task"),
    )

    response = await client.post(
        f"/api/v1/recruitment-projects/{project['id']}/jd",
        files={
            "file": (
                "jd.txt",
                BytesIO("负责 Python 开发".encode()),
                "text/plain",
            )
        },
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "jd-file-key",
        },
    )

    assert response.status_code == 202
    stored_project = await db_session.get(RecruitmentProject, project["id"])
    stored_file = await db_session.get(StoredFile, stored_project.jd_file_id)
    assert stored_project.jd_source_type == "file"
    assert stored_project.jd_source_text is None
    assert stored_file.category == "jd"
    assert stored_file.extension == "txt"
    assert storage.resolve(stored_file.storage_key).read_text() == "负责 Python 开发"


async def test_requirements_replace_rebuilds_catalog_metadata_and_confirm_reuses_hash(
    client,
    make_user,
    login,
    db_session,
) -> None:
    hr, password = await make_user(role="hr", username="requirements_hr")
    domain = Domain(
        id=uuid4(),
        code=f"requirements-{uuid4().hex[:8]}",
        name="软件工程",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        skill_type="language",
        status="active",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()
    csrf = await login(hr.username, password)
    created = await _create_project(client, csrf)
    project = await db_session.get(RecruitmentProject, created["id"])
    project.jd_source_type = "text"
    project.jd_source_text = "负责 Python 开发"
    project.jd_parse_status = "ready"
    project.jd_draft_payload = {"schema_version": "recruitment_requirements_v1"}
    await db_session.flush()
    payload = {
        "job_title": "AI 应用开发工程师",
        "summary": "负责工程化落地",
        "responsibilities": ["负责 Python 开发"],
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
        "requirements": [
            {
                "capability_id": str(capability.id),
                "requirement_type": "required",
                "importance": 1.0,
            }
        ],
        "unmapped_skills": [{"raw_name": "新框架", "requirement_type": "bonus"}],
    }

    replaced = await client.put(
        f"/api/v1/recruitment-projects/{project.id}/requirements",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    first = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/requirements/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    second = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/requirements/confirm",
        headers={"X-CSRF-Token": csrf},
    )

    assert replaced.status_code == 200
    requirement = replaced.json()["data"]["requirements"][0]
    assert requirement["canonical_name"] == "Python"
    assert requirement["domain"]["name"] == "软件工程"
    assert requirement["mapping_method"] == "manual"
    assert first.status_code == 200
    assert first.json()["data"]["requirements_revision"] == 1
    assert first.json()["data"]["reused"] is False
    assert second.json()["data"]["requirements_revision"] == 1
    assert second.json()["data"]["reused"] is True
    assert (
        second.json()["data"]["requirements_sha256"]
        == first.json()["data"]["requirements_sha256"]
    )
    detail = await client.get(f"/api/v1/recruitment-projects/{project.id}")
    summary = detail.json()["data"]["confirmed_requirement_summary"]
    assert (
        summary.pop("confirmed_at").replace("+00:00", "Z")
        == first.json()["data"]["confirmed_at"]
    )
    assert summary == {
        "job_title": "AI 应用开发工程师",
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
        "required_capability_count": 1,
        "bonus_capability_count": 0,
        "unmapped_skill_count": 1,
    }

    stored = await db_session.scalar(
        select(RecruitmentProject).where(RecruitmentProject.id == project.id)
    )
    assert stored.requirements_revision == 1
    assert stored.confirmed_requirement_snapshot["requirements"][0][
        "capability_id"
    ] == str(capability.id)
