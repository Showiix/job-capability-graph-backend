from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio

from app.auth.models import User
from app.core.security import hash_password
from app.processing.models import ProcessingRun


@pytest_asyncio.fixture
async def flow_admin(db_session) -> User:
    admin = User(
        id=uuid4(),
        username="admin_flow",
        username_normalized="admin_flow",
        password_hash=hash_password("admin-test-password"),
        display_name="闭环管理员",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(admin)
    await db_session.flush()
    return admin


async def test_batch_a_role_and_session_flow(
    client,
    db_session,
    flow_admin,
) -> None:
    admin_run = ProcessingRun(
        id=uuid4(),
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=uuid4(),
        created_by_user_id=flow_admin.id,
        owner_scope_type="admin_global",
        owner_scope_id=None,
        status="pending",
        pipeline_version="flow-v1",
    )
    db_session.add(admin_run)
    await db_session.flush()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin_flow", "password": "admin-test-password"},
    )
    csrf = login.json()["data"]["csrf_token"]
    hr_created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "hr_flow",
            "display_name": "闭环 HR",
            "role": "hr",
            "initial_password": "hr-test-password",
        },
        headers={"X-CSRF-Token": csrf},
    )
    applicant_created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "applicant_flow",
            "display_name": "闭环应聘者",
            "role": "applicant",
            "initial_password": "applicant-test-password",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert login.status_code == 200
    assert hr_created.status_code == 201
    assert applicant_created.status_code == 201

    admin_logout = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    hr_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_flow", "password": "hr-test-password"},
    )
    hr_runs = await client.get("/api/v1/processing-runs")
    hr_admin_details = await client.get("/api/v1/admin/system/dependencies")

    assert admin_logout.status_code == 204
    assert hr_login.status_code == 200
    assert hr_login.json()["data"]["role"] == "hr"
    assert hr_runs.status_code == 200
    assert hr_runs.json()["data"] == []
    assert hr_admin_details.status_code == 403
    assert hr_admin_details.json()["error"]["code"] == "ROLE_NOT_ALLOWED"

    hr_csrf = hr_login.json()["data"]["csrf_token"]
    await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": hr_csrf},
    )
    applicant_login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "applicant_flow",
            "password": "applicant-test-password",
        },
    )
    hidden_run = await client.get(f"/api/v1/processing-runs/{admin_run.id}")

    assert applicant_login.status_code == 200
    assert hidden_run.status_code == 404
    assert hidden_run.json()["error"]["code"] == "RESOURCE_NOT_OWNED"

    applicant_csrf = applicant_login.json()["data"]["csrf_token"]
    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": applicant_csrf},
    )
    me_after_logout = await client.get("/api/v1/auth/me")

    assert logout.status_code == 204
    assert me_after_logout.status_code == 401
    assert me_after_logout.json()["error"]["code"] == "AUTH_REQUIRED"
