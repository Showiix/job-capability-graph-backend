from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import AuthSession, User


async def test_username_normalized_is_unique(db_session) -> None:
    db_session.add_all(
        [
            User(
                id=uuid4(),
                username="Demo",
                username_normalized="demo",
                password_hash="hash",
                display_name="A",
                role="applicant",
                password_changed_at=datetime.now(UTC),
            ),
            User(
                id=uuid4(),
                username="demo",
                username_normalized="demo",
                password_hash="hash",
                display_name="B",
                role="hr",
                password_changed_at=datetime.now(UTC),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_session_expiry_must_follow_creation(db_session, user) -> None:
    now = datetime.now(UTC)
    db_session.add(
        AuthSession(
            id=uuid4(),
            user_id=user.id,
            token_hash="a" * 64,
            csrf_token_hash="b" * 64,
            created_at=now,
            last_seen_at=now,
            expires_at=now - timedelta(seconds=1),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_stored_file_size_must_be_positive(db_session, user) -> None:
    from app.files.models import StoredFile

    db_session.add(
        StoredFile(
            id=uuid4(),
            uploaded_by_user_id=user.id,
            original_name="empty.pdf",
            storage_key="files/empty",
            media_type="application/pdf",
            extension="pdf",
            size_bytes=0,
            sha256="c" * 64,
            category="resume",
            scan_status="not_required",
            status="uploaded",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_stored_file_status_must_be_known(db_session, user) -> None:
    from app.files.models import StoredFile

    db_session.add(
        StoredFile(
            id=uuid4(),
            uploaded_by_user_id=user.id,
            original_name="resume.pdf",
            storage_key="files/resume",
            media_type="application/pdf",
            extension="pdf",
            size_bytes=10,
            sha256="d" * 64,
            category="resume",
            scan_status="not_required",
            status="unknown",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_processing_user_scope_requires_owner_id(db_session, user) -> None:
    from app.processing.models import ProcessingRun

    db_session.add(
        ProcessingRun(
            id=uuid4(),
            run_type="test",
            subject_type="test",
            subject_id=uuid4(),
            created_by_user_id=user.id,
            owner_scope_type="user",
            owner_scope_id=None,
            status="pending",
            pipeline_version="test-v1",
            input_snapshot={},
            result_summary={},
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_processing_progress_stays_in_percentage_range(db_session, user) -> None:
    from app.processing.models import ProcessingRun

    db_session.add(
        ProcessingRun(
            id=uuid4(),
            run_type="test",
            subject_type="test",
            subject_id=uuid4(),
            created_by_user_id=user.id,
            owner_scope_type="user",
            owner_scope_id=user.id,
            status="running",
            pipeline_version="test-v1",
            progress_percent=101,
            input_snapshot={},
            result_summary={},
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
