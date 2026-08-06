from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.auth.models import AuthSession, LoginAttempt, User
from app.core.config import get_settings
from app.core.security import hash_password, new_token, token_digest


@pytest_asyncio.fixture
async def seeded_hr(db_session) -> User:
    user = User(
        id=uuid4(),
        username="hr_demo",
        username_normalized="hr_demo",
        password_hash=hash_password("correct-password"),
        display_name="演示 HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_login_sets_opaque_session_and_csrf(client, seeded_hr) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": " hr_demo ", "password": "correct-password"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "hr"
    assert response.cookies["session"]
    assert response.cookies["csrf"] == response.json()["data"]["csrf_token"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "password" not in response.text


async def test_wrong_password_is_audited_without_exposing_account_state(
    client,
    db_session,
    seeded_hr,
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "wrong-password"},
        headers={"X-Request-ID": "req_wrong_password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    attempt = await db_session.scalar(
        select(LoginAttempt).where(LoginAttempt.request_id == "req_wrong_password")
    )
    assert attempt is not None
    assert not attempt.success
    assert attempt.failure_code == "invalid_credentials"


async def test_inactive_account_cannot_login(client, db_session, seeded_hr) -> None:
    seeded_hr.is_active = False
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "correct-password"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_authenticated_user_can_read_me(client, seeded_hr) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "correct-password"},
    )

    response = await client.get("/api/v1/auth/me")

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(seeded_hr.id)
    assert response.json()["data"]["csrf_token"] == client.cookies["csrf"]


async def test_logout_requires_csrf(client, seeded_hr) -> None:
    await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "correct-password"},
    )

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_logout_revokes_session(client, seeded_hr) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "correct-password"},
    )
    csrf = login.json()["data"]["csrf_token"]

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    me = await client.get("/api/v1/auth/me")

    assert logout.status_code == 204
    assert me.status_code == 401


async def test_expired_session_is_rejected(client, db_session, user) -> None:
    token = new_token()
    now = datetime.now(UTC)
    db_session.add(
        AuthSession(
            id=uuid4(),
            user_id=user.id,
            token_hash=token_digest(
                token,
                get_settings().session_secret.get_secret_value(),
            ),
            csrf_token_hash="a" * 64,
            expires_at=now - timedelta(seconds=1),
            last_seen_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
        )
    )
    await db_session.flush()
    client.cookies.set("session", token)

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


async def test_tenth_recent_failure_is_rate_limited(
    client,
    db_session,
    seeded_hr,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            LoginAttempt(
                id=uuid4(),
                username_normalized="hr_demo",
                user_id=seeded_hr.id,
                success=False,
                failure_code="invalid_credentials",
                ip_address="127.0.0.1",
                request_id=f"req_previous_{index}",
                created_at=now - timedelta(minutes=1),
            )
            for index in range(9)
        ]
    )
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_demo", "password": "wrong-password"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LOGIN_RATE_LIMITED"
