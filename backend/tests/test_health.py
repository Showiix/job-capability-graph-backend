from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.auth.models import User
from app.core.config import get_settings
from app.core.security import hash_password
from app.main import app
from app.system.service import DependencyStatus, llm_configuration_status


async def login_as(client, username: str, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest.fixture
def dependency_statuses() -> dict[str, DependencyStatus]:
    return {
        "postgresql": DependencyStatus("ok", 1.0),
        "redis": DependencyStatus("ok", 2.0),
        "neo4j": DependencyStatus("ok", 3.0),
        "file_volume": DependencyStatus("ok", 1.0),
        "algorithm_service": DependencyStatus("degraded", None),
        "llm_service": DependencyStatus("degraded", None),
    }


@pytest.fixture
def healthy_dependencies(monkeypatch, dependency_statuses) -> None:
    async def healthy():
        return dependency_statuses

    monkeypatch.setattr("app.system.service.probe_dependencies", healthy)


@pytest_asyncio.fixture
async def system_admin(db_session) -> User:
    user = User(
        id=uuid4(),
        username="system_admin",
        username_normalized="system_admin",
        password_hash=hash_password("system-admin-password"),
        display_name="系统诊断管理员",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def system_hr(db_session) -> User:
    user = User(
        id=uuid4(),
        username="system_hr",
        username_normalized="system_hr",
        password_hash=hash_password("system-hr-password"),
        display_name="系统诊断 HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_live_is_public_and_does_not_probe_dependencies() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_succeeds_when_required_dependencies_are_ok(
    client,
    healthy_dependencies,
) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"]["postgresql"] == "ok"
    assert response.json()["dependencies"]["algorithm_service"] == "degraded"


async def test_ready_does_not_contact_responses_provider(
    monkeypatch,
    client,
) -> None:
    contacted = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal contacted
        contacted = True
        raise AssertionError("ready must not create an LLM request")

    async def ok():
        return DependencyStatus("ok", None)

    monkeypatch.setattr("app.system.service.probe_postgres", ok)
    monkeypatch.setattr("app.system.service.probe_redis", ok)
    monkeypatch.setattr("app.system.service.probe_neo4j", ok)
    monkeypatch.setattr("app.system.service.probe_file_volume", ok)
    monkeypatch.setattr("app.system.service.probe_algorithm_service", ok)
    monkeypatch.setattr("app.resumes.llm.httpx.AsyncClient", fail_if_constructed)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert contacted is False


def test_llm_configuration_status_is_ok_only_when_all_fields_exist(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "llm_responses_url",
        "https://provider.test/v1/responses",
    )
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("test-key"))
    monkeypatch.setattr(settings, "llm_model", "test-model")

    assert llm_configuration_status() == DependencyStatus("ok", None)


@pytest.mark.parametrize("missing", ["url", "key", "model"])
def test_llm_configuration_status_is_degraded_when_one_field_is_missing(
    monkeypatch,
    missing,
):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "llm_responses_url",
        None if missing == "url" else "https://provider.test/v1/responses",
    )
    monkeypatch.setattr(
        settings,
        "llm_api_key",
        None if missing == "key" else SecretStr("test-key"),
    )
    monkeypatch.setattr(
        settings,
        "llm_model",
        None if missing == "model" else "test-model",
    )

    assert llm_configuration_status() == DependencyStatus("degraded", None)


async def test_ready_includes_degraded_llm_without_returning_503(
    client,
    monkeypatch,
    dependency_statuses,
):
    dependency_statuses["llm_service"] = DependencyStatus("degraded", None)

    async def statuses():
        return dependency_statuses

    monkeypatch.setattr("app.system.service.probe_dependencies", statuses)
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["dependencies"]["llm_service"] == "degraded"


async def test_ready_fails_when_postgres_is_down(
    client,
    monkeypatch,
    dependency_statuses,
) -> None:
    dependency_statuses["postgresql"] = DependencyStatus("down", None)

    async def failed():
        return dependency_statuses

    monkeypatch.setattr("app.system.service.probe_dependencies", failed)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "127.0.0.1" not in response.text
    assert "password" not in response.text.lower()


async def test_dependency_details_require_admin(
    client,
    monkeypatch,
    system_admin,
    system_hr,
) -> None:
    async def diagnostics(db):
        return {
            "dependencies": {
                "postgresql": {"status": "ok", "latency_ms": 1.0},
                "redis": {"status": "ok", "latency_ms": 2.0},
            },
            "processing_runs": {"pending": 0, "running": 0, "stale": 0},
            "celery_queue_length": 0,
        }

    monkeypatch.setattr(
        "app.system.service.dependency_diagnostics",
        diagnostics,
    )
    await login_as(client, "system_hr", "system-hr-password")
    denied = await client.get("/api/v1/admin/system/dependencies")
    await login_as(client, "system_admin", "system-admin-password")
    allowed = await client.get("/api/v1/admin/system/dependencies")

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert allowed.status_code == 200
    assert "postgresql" in allowed.json()["data"]["dependencies"]


async def test_versions_require_admin_and_do_not_invent_versions(
    client,
    system_admin,
) -> None:
    await login_as(client, "system_admin", "system-admin-password")

    response = await client.get("/api/v1/admin/system/versions")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["api_version"] == "0.1.0"
    assert data["alembic_revision"] == "0016"
    assert data["prompt_version"] is None
    assert data["graph_version"] is None
