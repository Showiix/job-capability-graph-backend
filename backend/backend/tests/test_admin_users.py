from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.auth.models import AuthSession, User
from app.core.config import get_settings
from app.core.security import hash_password, token_digest, verify_password


async def login_as(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


@pytest_asyncio.fixture
async def seeded_admin(db_session) -> User:
    user = User(
        id=uuid4(),
        username="admin_demo",
        username_normalized="admin_demo",
        password_hash=hash_password("admin-password"),
        display_name="系统管理员",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def seeded_hr(db_session) -> User:
    user = User(
        id=uuid4(),
        username="hr_demo",
        username_normalized="hr_demo",
        password_hash=hash_password("hr-password"),
        display_name="演示 HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def seeded_applicant(db_session) -> User:
    user = User(
        id=uuid4(),
        username="applicant_demo",
        username_normalized="applicant_demo",
        password_hash=hash_password("applicant-password"),
        display_name="演示应聘者",
        role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_only_admin_can_create_user(
    client,
    seeded_admin,
    seeded_hr,
) -> None:
    payload = {
        "username": "new_applicant",
        "display_name": "新应聘者",
        "role": "applicant",
        "initial_password": "temporary-password",
    }
    hr_csrf = await login_as(client, "hr_demo", "hr-password")
    denied = await client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"X-CSRF-Token": hr_csrf},
    )

    admin_csrf = await login_as(client, "admin_demo", "admin-password")
    created = await client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert created.status_code == 201
    assert created.json()["data"]["username"] == "new_applicant"
    assert "initial_password" not in created.text
    assert "password_hash" not in created.text


async def test_duplicate_username_uses_normalized_value(
    client,
    seeded_admin,
    seeded_hr,
) -> None:
    csrf = await login_as(client, "admin_demo", "admin-password")
    response = await client.post(
        "/api/v1/admin/users",
        json={
            "username": " HR_DEMO ",
            "display_name": "重复 HR",
            "role": "hr",
            "initial_password": "temporary-password",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_ALREADY_EXISTS"


async def test_admin_can_list_filter_and_read_users(
    client,
    seeded_admin,
    seeded_hr,
    seeded_applicant,
) -> None:
    await login_as(client, "admin_demo", "admin-password")

    listing = await client.get("/api/v1/admin/users?role=hr&q=演示&page_size=10")
    detail = await client.get(f"/api/v1/admin/users/{seeded_hr.id}")

    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert listing.json()["data"]["items"][0]["id"] == str(seeded_hr.id)
    assert detail.status_code == 200
    assert detail.json()["data"]["role"] == "hr"


async def test_last_active_admin_cannot_be_disabled_or_demoted(
    client,
    seeded_admin,
) -> None:
    csrf = await login_as(client, "admin_demo", "admin-password")

    disabled = await client.patch(
        f"/api/v1/admin/users/{seeded_admin.id}",
        json={"is_active": False},
        headers={"X-CSRF-Token": csrf},
    )
    demoted = await client.patch(
        f"/api/v1/admin/users/{seeded_admin.id}",
        json={"role": "hr"},
        headers={"X-CSRF-Token": csrf},
    )

    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"
    assert demoted.status_code == 409
    assert demoted.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"


async def test_disabling_user_revokes_existing_sessions(
    client,
    db_session,
    seeded_admin,
    seeded_applicant,
) -> None:
    await login_as(client, "applicant_demo", "applicant-password")
    target_token = client.cookies["session"]
    csrf = await login_as(client, "admin_demo", "admin-password")

    response = await client.patch(
        f"/api/v1/admin/users/{seeded_applicant.id}",
        json={"is_active": False},
        headers={"X-CSRF-Token": csrf},
    )

    target_session = await db_session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash
            == token_digest(
                target_token,
                get_settings().session_secret.get_secret_value(),
            )
        )
    )
    assert response.status_code == 200
    assert not response.json()["data"]["is_active"]
    assert target_session is not None
    assert target_session.revoked_at is not None


async def test_password_reset_revokes_sessions_and_returns_no_secret(
    client,
    db_session,
    seeded_admin,
    seeded_applicant,
) -> None:
    await login_as(client, "applicant_demo", "applicant-password")
    target_token = client.cookies["session"]
    csrf = await login_as(client, "admin_demo", "admin-password")

    response = await client.post(
        f"/api/v1/admin/users/{seeded_applicant.id}/reset-password",
        json={"new_password": "replacement-password"},
        headers={"X-CSRF-Token": csrf},
    )

    target_session = await db_session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash
            == token_digest(
                target_token,
                get_settings().session_secret.get_secret_value(),
            )
        )
    )
    assert response.status_code == 200
    assert verify_password("replacement-password", seeded_applicant.password_hash)
    assert target_session is not None
    assert target_session.revoked_at is not None
    assert "replacement-password" not in response.text
    assert "password_hash" not in response.text
