from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.models import User
from app.core.security import hash_password
from app.files.models import FileAccessLog, StoredFile
from app.infrastructure.file_storage import FileStorage
from app.resumes.models import Resume


async def login_as(client, username: str, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest_asyncio.fixture
async def file_owner(db_session) -> User:
    user = User(
        id=uuid4(),
        username="file_owner",
        username_normalized="file_owner",
        password_hash=hash_password("owner-password"),
        display_name="文件所有者",
        role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session) -> User:
    user = User(
        id=uuid4(),
        username="other_user",
        username_normalized="other_user",
        password_hash=hash_password("other-password"),
        display_name="其他用户",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def file_storage(tmp_path) -> FileStorage:
    return FileStorage(tmp_path / "files")


@pytest_asyncio.fixture
async def stored_unattached_file(
    db_session,
    file_owner,
    file_storage,
    monkeypatch,
) -> StoredFile:
    monkeypatch.setattr("app.files.router.storage", file_storage)
    path = file_storage.resolve("resume/safe.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"safe file")
    value = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=file_owner.id,
        original_name="safe.txt",
        storage_key="resume/safe.txt",
        media_type="text/plain",
        extension="txt",
        size_bytes=9,
        sha256="a" * 64,
        category="resume",
        scan_status="clean",
        status="uploaded",
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def attached_file(
    db_session,
    file_owner,
    file_storage,
    monkeypatch,
) -> StoredFile:
    monkeypatch.setattr("app.files.router.storage", file_storage)
    path = file_storage.resolve("resume/attached.docx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"resume doc")
    value = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=file_owner.id,
        original_name="attached.docx",
        storage_key="resume/attached.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        extension="docx",
        size_bytes=10,
        sha256="b" * 64,
        category="resume",
        scan_status="clean",
        status="attached",
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def attached_resume(db_session, file_owner, attached_file) -> Resume:
    value = Resume(
        id=uuid4(),
        owner_user_id=file_owner.id,
        file_id=attached_file.id,
        display_name="attached.docx",
        source_language="zh-CN",
        parse_status="uploaded",
        created_by_user_id=file_owner.id,
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def test_uploader_can_preview_unattached_file(
    client,
    file_owner,
    stored_unattached_file,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(f"/api/v1/files/{stored_unattached_file.id}/content")

    assert response.status_code == 200
    assert response.content == b"safe file"
    assert response.headers["accept-ranges"] == "bytes"


async def test_file_content_supports_byte_ranges(
    client,
    file_owner,
    stored_unattached_file,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(
        f"/api/v1/files/{stored_unattached_file.id}/content",
        headers={"Range": "bytes=0-3"},
    )

    assert response.status_code == 206
    assert response.content == b"safe"
    assert response.headers["content-range"] == "bytes 0-3/9"


async def test_other_user_sees_not_found(
    client,
    stored_unattached_file,
    other_user,
) -> None:
    await login_as(client, "other_user", "other-password")

    response = await client.get(f"/api/v1/files/{stored_unattached_file.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_attached_file_is_not_owned_by_original_uploader(
    client,
    file_owner,
    attached_file,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(f"/api/v1/files/{attached_file.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_resume_owner_can_read_attached_resume_file(
    client,
    file_owner,
    attached_file,
    attached_resume,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(f"/api/v1/files/{attached_file.id}")

    assert response.status_code == 200


async def test_hr_cannot_read_attached_applicant_resume_file(
    client,
    other_user,
    attached_file,
    attached_resume,
) -> None:
    await login_as(client, "other_user", "other-password")

    response = await client.get(f"/api/v1/files/{attached_file.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_admin_can_read_attached_resume_file_and_access_is_audited(
    client,
    db_session,
    make_user,
    attached_file,
    attached_resume,
) -> None:
    admin, password = await make_user(role="admin")
    await login_as(client, admin.username, password)

    metadata = await client.get(f"/api/v1/files/{attached_file.id}")
    content = await client.get(f"/api/v1/files/{attached_file.id}/content")
    download = await client.get(f"/api/v1/files/{attached_file.id}/download")
    logs = (
        await db_session.scalars(
            select(FileAccessLog).where(FileAccessLog.file_id == attached_file.id)
        )
    ).all()

    assert metadata.status_code == 200
    assert content.status_code == 200
    assert content.content == b"resume doc"
    assert download.status_code == 200
    assert download.content == b"resume doc"
    assert {log.action for log in logs} == {"preview", "download"}
    assert {log.user_id for log in logs} == {admin.id}


def test_storage_key_cannot_escape_root(file_storage, tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid storage key"):
        file_storage.resolve("../outside.txt")
    with pytest.raises(ValueError, match="invalid storage key"):
        file_storage.resolve(str(tmp_path / "absolute.txt"))


async def test_metadata_marks_text_preview_supported(
    client,
    file_owner,
    stored_unattached_file,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(f"/api/v1/files/{stored_unattached_file.id}")

    assert response.status_code == 200
    assert response.json()["data"]["preview_supported"] is True
    assert "storage_key" not in response.text


async def test_download_creates_access_log(
    client,
    db_session,
    file_owner,
    stored_unattached_file,
) -> None:
    await login_as(client, "file_owner", "owner-password")

    response = await client.get(f"/api/v1/files/{stored_unattached_file.id}/download")
    log = await db_session.scalar(
        select(FileAccessLog).where(
            FileAccessLog.file_id == stored_unattached_file.id,
            FileAccessLog.action == "download",
        )
    )

    assert response.status_code == 200
    assert response.content == b"safe file"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert log is not None
    assert log.user_id == file_owner.id
