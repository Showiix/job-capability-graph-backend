from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from docx import Document
from sqlalchemy import func, select

from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingRun
from app.recruitment.models import RecruitmentCandidate, RecruitmentProject
from app.resumes.parsing import DOCX_MEDIA_TYPE


def _docx_bytes(text: str) -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def _project(db_session, owner) -> RecruitmentProject:
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=owner.id,
        title="候选人批量解析",
        jd_parse_status="empty",
        jd_draft_payload={},
        confirmed_requirement_snapshot={},
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def test_candidate_upload_is_atomic_appendable_and_idempotent(
    client,
    db_session,
    make_user,
    monkeypatch,
    tmp_path,
) -> None:
    owner, password = await make_user(role="hr", username="candidate_upload_hr")
    project = await _project(db_session, owner)
    csrf = await _login(client, owner.username, password)
    storage = FileStorage(tmp_path / "candidate-files")
    monkeypatch.setattr("app.recruitment.service.storage", storage)
    monkeypatch.setattr(
        "app.recruitment.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="candidate-task"),
    )
    files = [
        ("files", ("张三.docx", _docx_bytes("使用 Python 开发"), DOCX_MEDIA_TYPE)),
        ("files", ("李四.docx", _docx_bytes("使用 Java 开发"), DOCX_MEDIA_TYPE)),
    ]
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "candidate-batch-1"}

    first = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/candidates",
        files=files,
        headers=headers,
    )
    duplicate = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/candidates",
        files=files,
        headers=headers,
    )

    assert first.status_code == 202
    assert duplicate.json() == first.json()
    assert [item["display_name"] for item in first.json()["data"]["candidates"]] == [
        "张三",
        "李四",
    ]
    assert (
        await db_session.scalar(select(func.count()).select_from(RecruitmentCandidate))
        == 2
    )
    run = await db_session.get(ProcessingRun, first.json()["data"]["run_id"])
    assert run.input_snapshot["candidate_ids"] == sorted(
        item["id"] for item in first.json()["data"]["candidates"]
    )

    appended = await client.post(
        f"/api/v1/recruitment-projects/{project.id}/candidates",
        files=[
            (
                "files",
                ("王五.docx", _docx_bytes("使用 Go 开发"), DOCX_MEDIA_TYPE),
            )
        ],
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "candidate-batch-2",
        },
    )
    assert appended.status_code == 202
    assert (
        await db_session.scalar(select(func.count()).select_from(RecruitmentCandidate))
        == 3
    )


async def test_candidate_upload_rejects_invalid_batches_without_partial_rows(
    client,
    db_session,
    make_user,
    monkeypatch,
    tmp_path,
) -> None:
    owner, password = await make_user(role="hr", username="candidate_invalid_hr")
    project = await _project(db_session, owner)
    csrf = await _login(client, owner.username, password)
    storage = FileStorage(tmp_path / "candidate-invalid-files")
    monkeypatch.setattr("app.recruitment.service.storage", storage)
    url = f"/api/v1/recruitment-projects/{project.id}/candidates"

    empty = await client.post(
        url,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "empty"},
    )
    too_many = await client.post(
        url,
        files=[
            ("files", (f"{index}.docx", _docx_bytes("Python"), DOCX_MEDIA_TYPE))
            for index in range(21)
        ],
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "too-many"},
    )
    invalid = await client.post(
        url,
        files=[
            ("files", ("ok.docx", _docx_bytes("Python"), DOCX_MEDIA_TYPE)),
            ("files", ("bad.png", b"png", "image/png")),
        ],
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "invalid"},
    )

    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "CANDIDATE_FILE_COUNT_INVALID"
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "CANDIDATE_FILE_COUNT_INVALID"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "CANDIDATE_DOCUMENT_INVALID"
    assert (
        await db_session.scalar(select(func.count()).select_from(RecruitmentCandidate))
        == 0
    )
    assert list(storage.root.rglob("*.*")) == []


async def test_candidate_list_and_detail_inherit_project_visibility(
    client,
    db_session,
    make_user,
) -> None:
    owner, owner_password = await make_user(role="hr", username="candidate_owner")
    _other, other_password = await make_user(role="hr", username="candidate_other")
    _admin, admin_password = await make_user(role="admin", username="candidate_admin")
    project = await _project(db_session, owner)
    stored_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=owner.id,
        original_name="张三.docx",
        storage_key=f"resume/{uuid4()}.docx",
        media_type=DOCX_MEDIA_TYPE,
        extension="docx",
        size_bytes=10,
        sha256="a" * 64,
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
        display_name="张三",
        parse_status="uploaded",
        created_by_user_id=owner.id,
    )
    db_session.add(candidate)
    await db_session.flush()

    await _login(client, owner.username, owner_password)
    listing = await client.get(
        f"/api/v1/recruitment-projects/{project.id}/candidates?q=张"
    )
    detail = await client.get(
        f"/api/v1/recruitment-projects/{project.id}/candidates/{candidate.id}"
    )
    assert listing.status_code == 200
    assert listing.json()["data"][0]["id"] == str(candidate.id)
    assert detail.json()["data"]["file"]["content_url"].endswith("/content")
    assert detail.json()["data"]["profile"] is None

    await _login(client, "candidate_other", other_password)
    hidden = await client.get(
        f"/api/v1/recruitment-projects/{project.id}/candidates/{candidate.id}"
    )
    assert hidden.status_code == 404

    await _login(client, "candidate_admin", admin_password)
    visible = await client.get(
        f"/api/v1/recruitment-projects/{project.id}/candidates/{candidate.id}"
    )
    assert visible.status_code == 200
