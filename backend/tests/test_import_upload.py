from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.files.models import StoredFile
from app.imports.models import ImportBatch
from app.infrastructure.file_storage import FileStorage
from app.processing.models import IdempotencyRecord, ProcessingRun


@pytest_asyncio.fixture
async def import_admin(db_session) -> User:
    value = User(
        id=uuid4(),
        username="import_admin",
        username_normalized="import_admin",
        password_hash=hash_password("import-admin-password"),
        display_name="Import Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def import_hr(db_session) -> User:
    value = User(
        id=uuid4(),
        username="import_hr",
        username_normalized="import_hr",
        password_hash=hash_password("import-hr-password"),
        display_name="Import HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def import_context(tmp_path, monkeypatch):
    storage = FileStorage(tmp_path / "files")
    monkeypatch.setattr("app.imports.service.storage", storage)
    monkeypatch.setattr(
        "app.imports.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="task-1"),
    )
    return storage


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def _upload(
    client,
    csrf: str,
    *,
    content: bytes = b"job_name\tcompany_name\nAI Engineer\tExample\n",
    idempotency_key: str = "import-key-1",
    filename: str = "jobs.tsv",
):
    return await client.post(
        "/api/v1/imports",
        data={
            "source_code": "standard",
            "collected_at": "2026-08-06T00:00:00Z",
            "source_format": "auto",
            "schema_version": "standard_v1",
        },
        files={"file": (filename, content, "text/tab-separated-values")},
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": idempotency_key,
        },
    )


async def test_admin_upload_creates_file_batch_and_run(
    client,
    db_session,
    import_admin,
    import_context,
) -> None:
    csrf = await _login(client, "import_admin", "import-admin-password")

    response = await _upload(client, csrf)

    assert response.status_code == 202
    data = response.json()["data"]
    batch = await db_session.get(ImportBatch, data["resource_id"])
    run = await db_session.get(ProcessingRun, data["run_id"])
    stored_file = await db_session.get(StoredFile, batch.file_id)
    assert batch.status == "uploaded"
    assert run.subject_type == "import_batch"
    assert run.subject_id == batch.id
    assert run.run_type == "import_market_jd"
    assert stored_file.category == "market_jd"
    assert stored_file.status == "attached"
    assert "jobs.tsv" not in stored_file.storage_key
    assert import_context.resolve(stored_file.storage_key).read_bytes().endswith(
        b"AI Engineer\tExample\n"
    )
    assert data["poll_url"] == f"/api/v1/processing-runs/{run.id}"


async def test_same_idempotency_key_returns_same_import(
    client,
    db_session,
    import_admin,
    import_context,
) -> None:
    csrf = await _login(client, "import_admin", "import-admin-password")

    first = await _upload(client, csrf)
    second = await _upload(client, csrf)

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert await db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(IdempotencyRecord))
        == 1
    )
    assert len(list(import_context.root.rglob("*.tsv"))) == 1


async def test_reused_idempotency_key_with_different_file_is_rejected(
    client,
    db_session,
    import_admin,
    import_context,
) -> None:
    csrf = await _login(client, "import_admin", "import-admin-password")
    await _upload(client, csrf)

    response = await _upload(client, csrf, content=b"job_name\nData Engineer\n")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert len(list(import_context.root.rglob("*.tsv"))) == 1


async def test_market_import_requires_admin(
    client,
    import_hr,
    import_context,
) -> None:
    csrf = await _login(client, "import_hr", "import-hr-password")

    response = await _upload(client, csrf)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_oversized_import_is_removed(
    client,
    import_admin,
    import_context,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.imports.service.MAX_IMPORT_FILE_BYTES", 4)
    csrf = await _login(client, "import_admin", "import-admin-password")

    response = await _upload(client, csrf, content=b"12345")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMPORT_FILE_TOO_LARGE"
    assert list(import_context.root.rglob("*.*")) == []


async def test_import_rejects_unsupported_extension(
    client,
    import_admin,
    import_context,
) -> None:
    csrf = await _login(client, "import_admin", "import-admin-password")

    response = await _upload(client, csrf, filename="jobs.exe")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_FILE_TYPE_UNSUPPORTED"
