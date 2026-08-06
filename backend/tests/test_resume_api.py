from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy import func, select

import app.resumes.service as resume_service
from app.audit.models import AuditLog
from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import IdempotencyRecord, ProcessingRun
from app.resumes.models import Resume, ResumeProfile, ResumeSkill

RESUME_PDF_BYTES = (
    Path(__file__).parent / "fixtures" / "resume_text.pdf"
).read_bytes()


@pytest.fixture
def resume_api_context(tmp_path, monkeypatch):
    storage = FileStorage(tmp_path / "resume-api-files")
    sent: list[tuple[str, list[str]]] = []

    def send_task(name, args):
        sent.append((name, args))
        return SimpleNamespace(id=f"task-{len(sent)}")

    monkeypatch.setattr(resume_service, "storage", storage, raising=False)
    monkeypatch.setattr(
        resume_service,
        "celery_app",
        SimpleNamespace(send_task=send_task),
        raising=False,
    )
    return SimpleNamespace(storage=storage, sent=sent)


async def seed_resume(
    db,
    owner,
    *,
    display_name: str = "比赛简历",
    parse_status: str = "ready",
    created_at: datetime | None = None,
) -> Resume:
    file_id = uuid4()
    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=owner.id,
        original_name="resume.pdf",
        storage_key=f"resume/private-{file_id}.pdf",
        media_type="application/pdf",
        extension="pdf",
        size_bytes=len(RESUME_PDF_BYTES),
        sha256="a" * 64,
        category="resume",
        scan_status="not_required",
        status="attached",
        created_at=created_at,
    )
    archived_at = datetime.now(UTC) if parse_status == "archived" else None
    resume = Resume(
        id=uuid4(),
        owner_user_id=owner.id,
        file_id=file_id,
        display_name=display_name,
        source_language="zh-CN",
        parse_status=parse_status,
        created_by_user_id=owner.id,
        archived_at=archived_at,
        created_at=created_at,
    )
    db.add_all([stored_file, resume])
    await db.flush()
    return resume


async def seed_run(db, resume: Resume, owner) -> ProcessingRun:
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=resume.id,
        created_by_user_id=owner.id,
        owner_scope_type="user",
        owner_scope_id=owner.id,
        status="completed",
        pipeline_version="resume_parse_v1",
        total_count=1,
        processed_count=1,
        success_count=1,
        max_attempts=1,
        input_snapshot={"resume_id": str(resume.id), "file_id": str(resume.file_id)},
        result_summary={},
    )
    db.add(run)
    await db.flush()
    resume.latest_run_id = run.id
    await db.flush()
    return run


async def seed_profile(
    db,
    resume: Resume,
    owner,
    *,
    version_no: int,
    status: str = "candidate",
    extracted_text: str = "绝密原始正文 Python",
    payload: dict | None = None,
) -> ResumeProfile:
    run = await seed_run(db, resume, owner)
    profile = ResumeProfile(
        id=uuid4(),
        resume_id=resume.id,
        version_no=version_no,
        extraction_version=f"resume_parse_v{version_no}",
        profile_source="extracted",
        extracted_text=extracted_text,
        text_extraction_method="pdf_text",
        highest_education_level="bachelor",
        total_experience_months=24,
        structured_payload=payload
        or {
            "schema_version": "resume_parse_v1",
            "document_language": "zh-CN",
            "summary": "结构化摘要",
            "educations": [],
            "experiences": [],
            "projects": [],
            "validation_warnings": [],
        },
        status=status,
        created_by_run_id=run.id,
        created_by_user_id=owner.id,
        confirmed_at=datetime.now(UTC)
        if status in {"confirmed", "superseded"}
        else None,
    )
    db.add(profile)
    await db.flush()
    return profile


async def seed_skill(
    db,
    profile: ResumeProfile,
    *,
    raw_name: str,
    normalized_name: str,
    capability: Capability | None = None,
) -> ResumeSkill:
    value = ResumeSkill(
        id=uuid4(),
        profile_id=profile.id,
        capability_id=capability.id if capability is not None else None,
        raw_name=raw_name,
        normalized_name=normalized_name,
        proficiency="intermediate",
        explicit_experience_months=12,
        evidence_strength="project",
        evidence_quote=raw_name,
        evidence_start=0,
        evidence_end=len(raw_name),
        mapping_method="canonical_exact" if capability is not None else "unmapped",
        mapping_status="mapped" if capability is not None else "unmapped",
        source="llm",
        confidence=Decimal("0.9000"),
        user_confirmed=False,
    )
    db.add(value)
    await db.flush()
    return value


async def test_applicant_uploads_pdf_and_receives_poll_url(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        data={"display_name": "比赛演示简历"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "resume-create-1"},
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "processing"
    assert data["poll_url"] == f"/api/v1/processing-runs/{data['run_id']}"
    assert resume_api_context.sent == [("app.parse_resume", [data["run_id"]])]


async def test_upload_requires_csrf(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


@pytest.mark.parametrize("role", ["hr", "admin"])
async def test_staff_cannot_create_applicant_resume(
    client,
    make_user,
    login,
    resume_api_context,
    role,
):
    actor, password = await make_user(role=role)
    csrf = await login(actor.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_empty_file_returns_resume_file_empty(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", b"", "application/pdf")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESUME_FILE_EMPTY"


async def test_file_over_limit_returns_413(
    client,
    make_user,
    login,
    resume_api_context,
    monkeypatch,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)
    monkeypatch.setattr(resume_service, "MAX_RESUME_FILE_BYTES", 8, raising=False)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", b"%PDF-1234", "application/pdf")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "RESUME_FILE_TOO_LARGE"


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("resume.txt", "application/pdf"),
        ("resume.pdf", "image/png"),
    ],
)
async def test_wrong_extension_or_media_type_returns_415(
    client,
    make_user,
    login,
    resume_api_context,
    filename,
    media_type,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": (filename, RESUME_PDF_BYTES, media_type)},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "RESUME_FILE_TYPE_UNSUPPORTED"


async def test_original_filename_over_storage_limit_returns_422(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)
    filename = f"{'a' * 252}.pdf"

    response = await client.post(
        "/api/v1/resumes",
        files={"file": (filename, RESUME_PDF_BYTES, "application/pdf")},
        data={"display_name": "短名称"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert list(resume_api_context.storage.root.rglob("*.pdf")) == []


async def test_pdf_signature_mismatch_returns_415(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", b"not-pdf", "application/pdf")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "RESUME_FILE_TYPE_UNSUPPORTED"
    assert list(resume_api_context.storage.root.rglob("*.pdf")) == []


async def test_docx_missing_required_entries_returns_415(
    client,
    make_user,
    login,
    resume_api_context,
):
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/other.xml", "<xml/>")
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={
            "file": (
                "resume.docx",
                stream.getvalue(),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
            )
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "RESUME_FILE_TYPE_UNSUPPORTED"
    assert list(resume_api_context.storage.root.rglob("*.docx")) == []


async def test_same_idempotency_key_same_body_reuses_resume_and_run(
    client,
    db_session,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)
    request = {
        "files": {"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        "data": {"display_name": "同一份简历"},
        "headers": {"X-CSRF-Token": csrf, "Idempotency-Key": "same-resume"},
    }

    first = await client.post("/api/v1/resumes", **request)
    second = await client.post("/api/v1/resumes", **request)

    assert first.status_code == second.status_code == 202
    assert first.json()["data"] == second.json()["data"]
    assert await db_session.scalar(select(func.count()).select_from(StoredFile)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Resume)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ProcessingRun)) == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == 1
    )
    assert len(list(resume_api_context.storage.root.rglob("*.pdf"))) == 1
    assert len(resume_api_context.sent) == 1


async def test_same_idempotency_key_different_body_returns_409(
    client,
    make_user,
    login,
    resume_api_context,
):
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "changed-resume"}

    first = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        data={"display_name": "版本一"},
        headers=headers,
    )
    second = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        data={"display_name": "版本二"},
        headers=headers,
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(list(resume_api_context.storage.root.rglob("*.pdf"))) == 1


async def test_enqueue_failure_keeps_created_resources(
    client,
    db_session,
    make_user,
    login,
    resume_api_context,
    monkeypatch,
):
    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("broker secret")

    monkeypatch.setattr(resume_service.celery_app, "send_task", fail_enqueue)
    applicant, password = await make_user(role="applicant")
    csrf = await login(applicant.username, password)

    response = await client.post(
        "/api/v1/resumes",
        files={"file": ("resume.pdf", RESUME_PDF_BYTES, "application/pdf")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    data = response.json()["data"]
    resume = await db_session.get(Resume, UUID(data["resource_id"]))
    run = await db_session.get(ProcessingRun, UUID(data["run_id"]))
    stored_file = await db_session.get(StoredFile, resume.file_id)
    assert resume.parse_status == "processing"
    assert run.status == "enqueue_failed"
    assert run.error_code == "TASK_ENQUEUE_FAILED"
    assert "secret" not in (run.error_message or "").lower()
    assert stored_file.status == "attached"
    assert resume_api_context.storage.exists(stored_file.storage_key)


async def test_applicant_lists_only_owned_resumes_and_archived_filter(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    other, _ = await make_user(role="applicant")
    active = await seed_resume(db_session, owner, display_name="我的有效简历")
    archived = await seed_resume(
        db_session,
        owner,
        display_name="我的归档简历",
        parse_status="archived",
    )
    await seed_resume(db_session, other, display_name="别人的简历")
    await login(owner.username, password)

    default = await client.get("/api/v1/resumes")
    archived_only = await client.get("/api/v1/resumes?parse_status=archived")

    assert default.status_code == archived_only.status_code == 200
    assert [item["id"] for item in default.json()["data"]] == [str(active.id)]
    assert [item["id"] for item in archived_only.json()["data"]] == [
        str(archived.id)
    ]


async def test_resume_list_is_created_descending_then_id(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    now = datetime.now(UTC)
    older = await seed_resume(db_session, owner, created_at=now - timedelta(days=1))
    newer_a = await seed_resume(db_session, owner, created_at=now)
    newer_b = await seed_resume(db_session, owner, created_at=now)
    await login(owner.username, password)

    response = await client.get("/api/v1/resumes")

    assert response.status_code == 200
    expected_newer = sorted([str(newer_a.id), str(newer_b.id)])
    assert [item["id"] for item in response.json()["data"]] == [
        *expected_newer,
        str(older.id),
    ]


async def test_admin_lists_all_non_archived_resumes(
    client,
    db_session,
    make_user,
    login,
):
    admin, password = await make_user(role="admin")
    owner_a, _ = await make_user(role="applicant")
    owner_b, _ = await make_user(role="applicant")
    first = await seed_resume(db_session, owner_a)
    second = await seed_resume(db_session, owner_b)
    await login(admin.username, password)

    response = await client.get("/api/v1/resumes")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["data"]} == {
        str(first.id),
        str(second.id),
    }


async def test_hr_resume_collection_returns_403(
    client,
    make_user,
    login,
):
    hr, password = await make_user(role="hr")
    await login(hr.username, password)

    response = await client.get("/api/v1/resumes")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_other_applicant_gets_resource_not_owned(
    client,
    db_session,
    make_user,
    login,
):
    owner, _ = await make_user(role="applicant")
    other, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    await login(other.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_resume_detail_has_safe_file_links_and_profile_versions(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    await seed_profile(db_session, resume, owner, version_no=1, status="confirmed")
    await seed_profile(db_session, resume, owner, version_no=2)
    await login(owner.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["latest_profile_version"] == 2
    assert data["confirmed_profile_version"] == 1
    assert data["file"] == {
        "id": str(resume.file_id),
        "metadata_url": f"/api/v1/files/{resume.file_id}",
        "content_url": f"/api/v1/files/{resume.file_id}/content",
        "download_url": f"/api/v1/files/{resume.file_id}/download",
    }
    serialized = response.text
    assert "绝密原始正文" not in serialized
    assert "private-" not in serialized
    assert "storage_key" not in serialized


async def test_profile_list_is_version_descending(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    for version in (1, 3, 2):
        await seed_profile(db_session, resume, owner, version_no=version)
    await login(owner.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}/profiles")

    assert response.status_code == 200
    assert [item["version_no"] for item in response.json()["data"]] == [3, 2, 1]
    assert all("extracted_text" not in item for item in response.json()["data"])


async def test_profile_detail_combines_payload_and_sorted_skills(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    profile = await seed_profile(
        db_session,
        resume,
        owner,
        version_no=1,
        payload={
            "schema_version": "resume_parse_v1",
            "document_language": "zh-CN",
            "summary": "可见摘要",
            "educations": [],
            "experiences": [],
            "projects": [],
            "validation_warnings": ["example"],
        },
    )
    domain = Domain(
        id=uuid4(),
        code=f"resume-api-{uuid4().hex}",
        name="测试领域",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Alpha",
        skill_type="technical",
        status="active",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()
    await seed_skill(
        db_session,
        profile,
        raw_name="Zulu",
        normalized_name="zulu",
    )
    await seed_skill(
        db_session,
        profile,
        raw_name="Alpha",
        normalized_name="alpha",
        capability=capability,
    )
    await login(owner.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}/profiles/1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["profile"]["summary"] == "可见摘要"
    assert [item["normalized_name"] for item in data["skills"]] == [
        "alpha",
        "zulu",
    ]
    assert data["skills"][0]["capability_name"] == "Alpha"
    assert data["skills"][1]["capability_name"] is None
    assert data["skills"][0]["confidence"] == 0.9
    assert "extracted_text" not in data


async def test_profile_version_from_other_resume_returns_404(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    first = await seed_resume(db_session, owner)
    second = await seed_resume(db_session, owner)
    await seed_profile(db_session, second, owner, version_no=7)
    await login(owner.username, password)

    response = await client.get(f"/api/v1/resumes/{first.id}/profiles/7")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESUME_PROFILE_NOT_FOUND"


async def test_extracted_text_owner_and_admin_can_read(
    client,
    db_session,
    make_user,
    login,
):
    owner, owner_password = await make_user(role="applicant")
    admin, admin_password = await make_user(role="admin")
    resume = await seed_resume(db_session, owner)
    profile = await seed_profile(
        db_session,
        resume,
        owner,
        version_no=1,
        extracted_text="仅专用端点可见的正文",
    )

    await login(owner.username, owner_password)
    owner_response = await client.get(
        f"/api/v1/resumes/{resume.id}/extracted-text"
    )
    await login(admin.username, admin_password)
    admin_response = await client.get(
        f"/api/v1/resumes/{resume.id}/extracted-text"
    )

    assert owner_response.status_code == admin_response.status_code == 200
    assert owner_response.json()["data"] == {
        "resume_id": str(resume.id),
        "profile_id": str(profile.id),
        "profile_version": 1,
        "text_extraction_method": "pdf_text",
        "extracted_text": "仅专用端点可见的正文",
    }
    assert admin_response.json()["data"]["extracted_text"] == "仅专用端点可见的正文"


async def test_other_applicant_cannot_read_extracted_text(
    client,
    db_session,
    make_user,
    login,
):
    owner, _ = await make_user(role="applicant")
    other, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    await seed_profile(db_session, resume, owner, version_no=1)
    await login(other.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}/extracted-text")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_extracted_text_read_records_audit_without_text_metadata(
    client,
    db_session,
    make_user,
    login,
):
    owner, password = await make_user(role="applicant")
    resume = await seed_resume(db_session, owner)
    profile = await seed_profile(
        db_session,
        resume,
        owner,
        version_no=1,
        extracted_text="绝不能进入审计 metadata 的正文",
    )
    await login(owner.username, password)

    response = await client.get(f"/api/v1/resumes/{resume.id}/extracted-text")

    assert response.status_code == 200
    audit = await db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "resume.extracted_text.read",
            AuditLog.actor_user_id == owner.id,
            AuditLog.resource_id == resume.id,
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.outcome == "success"
    assert audit.metadata_ == {
        "resume_id": str(resume.id),
        "profile_id": str(profile.id),
        "version_no": 1,
    }
    assert "绝不能" not in str(audit.metadata_)
