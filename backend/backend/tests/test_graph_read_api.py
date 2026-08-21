from datetime import UTC, datetime
from uuid import uuid4

from app.core.errors import APIError
from app.graph.schemas import GraphReadData, GraphVersionRead

pytest_plugins = ("tests.test_discovery_api",)


async def _login(client, role: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": f"discovery_api_{role}",
            "password": f"{role}-password",
        },
    )
    assert response.status_code == 200


def _graph_data() -> GraphReadData:
    return GraphReadData(
        graph_version=GraphVersionRead(
            id=uuid4(),
            version_no=3,
            published_at=datetime(2026, 8, 6, tzinfo=UTC),
        ),
        nodes=[],
        edges=[],
        truncated=False,
    )


async def test_all_authenticated_roles_read_graph_without_csrf(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    global_calls = []
    local_calls = []
    job_role_id = uuid4()

    async def fake_global(db, **kwargs):
        global_calls.append(kwargs)
        return _graph_data()

    async def fake_local(db, value, **kwargs):
        local_calls.append((value, kwargs))
        return _graph_data()

    monkeypatch.setattr(
        "app.graph.router.get_global_graph",
        fake_global,
        raising=False,
    )
    monkeypatch.setattr(
        "app.graph.router.get_job_role_graph",
        fake_local,
        raising=False,
    )

    for role in ("applicant", "hr", "admin"):
        await _login(client, role)
        global_response = await client.get(
            "/api/v1/graph",
            params={
                "domain_id": str(uuid4()),
                "max_job_roles": 12,
                "max_capabilities": 80,
            },
        )
        local_response = await client.get(
            f"/api/v1/graph/job-roles/{job_role_id}"
        )
        assert global_response.status_code == 200
        assert local_response.status_code == 200
        assert global_response.json()["data"]["graph_version"]["version_no"] == 3
        assert local_response.json()["data"]["truncated"] is False

    assert len(global_calls) == 3
    assert all(call["max_job_roles"] == 12 for call in global_calls)
    assert all(call["max_capabilities"] == 80 for call in global_calls)
    assert local_calls == [(job_role_id, {})] * 3


async def test_graph_read_requires_authentication(client, monkeypatch) -> None:
    async def must_not_run(*args, **kwargs):
        raise AssertionError("query service must not run")

    monkeypatch.setattr(
        "app.graph.router.get_global_graph",
        must_not_run,
        raising=False,
    )
    monkeypatch.setattr(
        "app.graph.router.get_job_role_graph",
        must_not_run,
        raising=False,
    )

    global_response = await client.get("/api/v1/graph")
    local_response = await client.get(f"/api/v1/graph/job-roles/{uuid4()}")

    assert global_response.status_code == 401
    assert local_response.status_code == 401
    assert global_response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert local_response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_global_graph_query_parameter_bounds(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    await _login(client, "applicant")

    async def must_not_run(*args, **kwargs):
        raise AssertionError("invalid parameters must not reach query service")

    monkeypatch.setattr(
        "app.graph.router.get_global_graph",
        must_not_run,
        raising=False,
    )
    responses = [
        await client.get("/api/v1/graph?max_job_roles=0"),
        await client.get("/api/v1/graph?max_job_roles=51"),
        await client.get("/api/v1/graph?max_capabilities=0"),
        await client.get("/api/v1/graph?max_capabilities=201"),
        await client.get("/api/v1/graph?domain_id=not-a-uuid"),
    ]

    assert all(response.status_code == 422 for response in responses)
    assert all(
        response.json()["error"]["code"] == "VALIDATION_FAILED"
        for response in responses
    )


async def test_graph_read_returns_stable_service_errors(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    await _login(client, "hr")

    async def missing_domain(db, **kwargs):
        raise APIError(404, "GRAPH_DOMAIN_NOT_FOUND", "技术域不存在或未启用")

    async def failed_role(db, job_role_id, **kwargs):
        raise APIError(503, "GRAPH_READ_FAILED", "图谱读取失败")

    monkeypatch.setattr(
        "app.graph.router.get_global_graph",
        missing_domain,
        raising=False,
    )
    monkeypatch.setattr(
        "app.graph.router.get_job_role_graph",
        failed_role,
        raising=False,
    )
    global_response = await client.get(
        "/api/v1/graph",
        params={"domain_id": str(uuid4())},
    )
    local_response = await client.get(f"/api/v1/graph/job-roles/{uuid4()}")

    assert global_response.status_code == 404
    assert global_response.json()["error"]["code"] == "GRAPH_DOMAIN_NOT_FOUND"
    assert local_response.status_code == 503
    assert local_response.json()["error"]["code"] == "GRAPH_READ_FAILED"
    assert "bolt://" not in local_response.text
    assert "password" not in local_response.text
    assert "query" not in local_response.text.lower()
