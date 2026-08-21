from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio

from app.auth.models import User
from app.core.security import hash_password
from app.processing.models import ProcessingError, ProcessingRun


async def login_as(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


@pytest_asyncio.fixture
async def processing_user(db_session) -> User:
    user = User(
        id=uuid4(),
        username="processing_user",
        username_normalized="processing_user",
        password_hash=hash_password("processing-password"),
        display_name="任务用户",
        role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_processing_user(db_session) -> User:
    user = User(
        id=uuid4(),
        username="other_processing_user",
        username_normalized="other_processing_user",
        password_hash=hash_password("other-processing-password"),
        display_name="其他任务用户",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def make_run(
    db_session,
    owner: User,
    *,
    status: str = "pending",
    result_summary: dict | None = None,
) -> ProcessingRun:
    now = datetime.now(UTC)
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_resume",
        subject_type="resume",
        subject_id=uuid4(),
        created_by_user_id=owner.id,
        owner_scope_type="user",
        owner_scope_id=owner.id,
        status=status,
        pipeline_version="test-v1",
        total_count=1,
        processed_count=1 if status in {"completed", "failed"} else 0,
        success_count=1 if status == "completed" else 0,
        failed_count=1 if status == "failed" else 0,
        progress_percent=100 if status in {"completed", "failed"} else 0,
        max_attempts=3,
        input_snapshot={"file_id": str(uuid4())},
        result_summary=result_summary or {},
        started_at=now if status != "pending" else None,
        heartbeat_at=now if status == "running" else None,
        completed_at=now if status in {"completed", "failed"} else None,
    )
    db_session.add(run)
    await db_session.flush()
    return run


async def test_user_only_lists_own_runs(
    client,
    db_session,
    processing_user,
    other_processing_user,
) -> None:
    own_run = await make_run(db_session, processing_user)
    other_run = await make_run(db_session, other_processing_user)
    await login_as(client, "processing_user", "processing-password")

    response = await client.get("/api/v1/processing-runs")
    ids = {item["id"] for item in response.json()["data"]}

    assert response.status_code == 200
    assert str(own_run.id) in ids
    assert str(other_run.id) not in ids


async def test_other_users_run_is_hidden(
    client,
    db_session,
    processing_user,
    other_processing_user,
) -> None:
    other_run = await make_run(db_session, other_processing_user)
    await login_as(client, "processing_user", "processing-password")

    response = await client.get(f"/api/v1/processing-runs/{other_run.id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_cancel_pending_run_is_immediate(
    client,
    db_session,
    processing_user,
) -> None:
    run = await make_run(db_session, processing_user, status="pending")
    csrf = await login_as(client, "processing_user", "processing-password")

    response = await client.post(
        f"/api/v1/processing-runs/{run.id}/cancel",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"
    assert run.completed_at is not None


async def test_cancel_running_run_is_cooperative(
    client,
    db_session,
    processing_user,
) -> None:
    run = await make_run(db_session, processing_user, status="running")
    csrf = await login_as(client, "processing_user", "processing-password")

    response = await client.post(
        f"/api/v1/processing-runs/{run.id}/cancel",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "cancel_requested"
    assert response.json()["data"]["cancel_requested"] is True


async def test_retry_creates_new_run_without_mutating_old(
    client,
    db_session,
    processing_user,
    monkeypatch,
) -> None:
    failed_run = await make_run(db_session, processing_user, status="failed")
    monkeypatch.setattr(
        "app.processing.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="celery-test-id"),
    )
    csrf = await login_as(client, "processing_user", "processing-password")

    response = await client.post(
        f"/api/v1/processing-runs/{failed_run.id}/retry",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    assert response.json()["data"]["retry_of_run_id"] == str(failed_run.id)
    assert response.json()["data"]["celery_task_id"] == "celery-test-id"
    await db_session.refresh(failed_run)
    assert failed_run.status == "failed"


async def test_enqueue_failure_keeps_retry_run(
    client,
    db_session,
    processing_user,
    monkeypatch,
) -> None:
    failed_run = await make_run(db_session, processing_user, status="failed")

    def fail_enqueue(*args, **kwargs):
        raise ConnectionError("redis secret must not leak")

    monkeypatch.setattr(
        "app.processing.service.celery_app.send_task",
        fail_enqueue,
    )
    csrf = await login_as(client, "processing_user", "processing-password")

    response = await client.post(
        f"/api/v1/processing-runs/{failed_run.id}/retry",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "enqueue_failed"
    assert response.json()["data"]["error_code"] == "TASK_ENQUEUE_FAILED"
    assert "redis secret" not in response.text


async def test_non_failed_run_cannot_be_retried(
    client,
    db_session,
    processing_user,
) -> None:
    run = await make_run(db_session, processing_user, status="completed")
    csrf = await login_as(client, "processing_user", "processing-password")

    response = await client.post(
        f"/api/v1/processing-runs/{run.id}/retry",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_NOT_RETRYABLE"


async def test_errors_are_returned_in_occurrence_order(
    client,
    db_session,
    processing_user,
) -> None:
    run = await make_run(db_session, processing_user, status="failed")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ProcessingError(
                id=uuid4(),
                run_id=run.id,
                stage="extract",
                error_code="SECOND",
                message="second",
                retryable=True,
                occurred_at=now,
            ),
            ProcessingError(
                id=uuid4(),
                run_id=run.id,
                stage="parse",
                error_code="FIRST",
                message="first",
                retryable=False,
                occurred_at=now - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.flush()
    await login_as(client, "processing_user", "processing-password")

    response = await client.get(f"/api/v1/processing-runs/{run.id}/errors")

    assert response.status_code == 200
    assert [item["error_code"] for item in response.json()["data"]] == [
        "FIRST",
        "SECOND",
    ]


async def test_result_requires_ready_run_and_result_url(
    client,
    db_session,
    processing_user,
) -> None:
    pending = await make_run(db_session, processing_user, status="pending")
    completed = await make_run(
        db_session,
        processing_user,
        status="completed",
        result_summary={
            "resource_type": "resume_profile",
            "result_url": "/api/v1/resumes/example",
        },
    )
    await login_as(client, "processing_user", "processing-password")

    not_ready = await client.get(f"/api/v1/processing-runs/{pending.id}/result")
    ready = await client.get(f"/api/v1/processing-runs/{completed.id}/result")

    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "RUN_RESULT_NOT_READY"
    assert ready.status_code == 200
    assert ready.json()["data"]["result_url"] == "/api/v1/resumes/example"
