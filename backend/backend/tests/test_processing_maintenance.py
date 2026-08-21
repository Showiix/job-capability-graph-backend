from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.auth.models import AuthSession, User
from app.core.security import hash_password
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun
from app.processing.service import (
    clean_expired_sessions,
    clean_unattached_files,
    mark_stale_runs,
    redispatch_pending_runs,
)


@pytest_asyncio.fixture
async def maintenance_user(db_session) -> User:
    user = User(
        id=uuid4(),
        username="maintenance_user",
        username_normalized="maintenance_user",
        password_hash=hash_password("maintenance-password"),
        display_name="维护任务用户",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_mark_stale_run_records_retryable_error(
    db_session,
    maintenance_user,
) -> None:
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=uuid4(),
        created_by_user_id=maintenance_user.id,
        owner_scope_type="admin_global",
        owner_scope_id=None,
        status="running",
        current_stage="extract",
        pipeline_version="test-v1",
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=6),
    )
    db_session.add(run)
    await db_session.flush()

    count = await mark_stale_runs(db_session)
    error = await db_session.scalar(
        select(ProcessingError).where(ProcessingError.run_id == run.id)
    )

    assert count == 1
    assert run.status == "failed"
    assert run.error_code == "WORKER_HEARTBEAT_STALE"
    assert error is not None
    assert error.retryable


async def test_redispatch_pending_run_records_task_id(
    db_session,
    maintenance_user,
    monkeypatch,
) -> None:
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=uuid4(),
        created_by_user_id=maintenance_user.id,
        owner_scope_type="admin_global",
        owner_scope_id=None,
        status="pending",
        pipeline_version="test-v1",
    )
    db_session.add(run)
    await db_session.flush()
    monkeypatch.setattr(
        "app.processing.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="redispatched-id"),
    )

    count = await redispatch_pending_runs(db_session)

    assert count == 1
    assert run.celery_task_id == "redispatched-id"
    assert run.enqueued_at is not None


async def test_clean_expired_sessions(db_session, maintenance_user) -> None:
    now = datetime.now(UTC)
    session = AuthSession(
        id=uuid4(),
        user_id=maintenance_user.id,
        token_hash="a" * 64,
        csrf_token_hash="b" * 64,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        last_seen_at=now - timedelta(hours=2),
    )
    db_session.add(session)
    await db_session.flush()

    count = await clean_expired_sessions(db_session)

    assert count == 1
    assert await db_session.get(AuthSession, session.id) is None


async def test_clean_expired_unattached_file(
    db_session,
    maintenance_user,
    tmp_path,
    monkeypatch,
) -> None:
    storage = FileStorage(tmp_path / "files")
    path = storage.resolve("expired.txt")
    path.write_bytes(b"expired")
    stored_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=maintenance_user.id,
        original_name="expired.txt",
        storage_key="expired.txt",
        media_type="text/plain",
        extension="txt",
        size_bytes=7,
        sha256="c" * 64,
        category="other",
        scan_status="clean",
        status="uploaded",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(stored_file)
    await db_session.flush()
    monkeypatch.setattr(
        "app.processing.service.get_settings",
        lambda: SimpleNamespace(file_storage_root=storage.root),
    )

    count = await clean_unattached_files(db_session)

    assert count == 1
    assert not path.exists()
    assert await db_session.get(StoredFile, stored_file.id) is None
