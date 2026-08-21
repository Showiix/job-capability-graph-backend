from app.graph.neo4j import GraphPublishResult
from app.graph.service import publish_graph_version as service_publish_graph_version

pytest_plugins = ("tests.test_review_api",)


async def _login(client, role: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": f"discovery_api_{role}",
            "password": f"{role}-password",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def _approved_proposal(client, csrf: str, candidate_id) -> dict:
    created = await client.post(
        "/api/v1/review-proposals",
        json={"candidate_id": str(candidate_id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    proposal = created.json()["data"]
    approved = await client.post(
        f"/api/v1/review-proposals/{proposal['id']}/decisions",
        json={"decision": "approve", "comment": "确认发布"},
        headers={"X-CSRF-Token": csrf},
    )
    assert approved.status_code == 200
    return approved.json()["data"]


async def _create_version(client, csrf: str, proposal_id) -> dict:
    response = await client.post(
        "/api/v1/graph-versions",
        json={"proposal_id": str(proposal_id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()["data"]


def _publish_result(snapshot: dict) -> GraphPublishResult:
    capabilities = snapshot["capabilities"]
    required_count = sum(
        item["requirement_type"] == "required" for item in capabilities
    )
    return GraphPublishResult(
        job_role_id=snapshot["job_role"]["id"],
        capability_count=len(capabilities),
        relation_count=len(capabilities),
        required_count=required_count,
        bonus_count=len(capabilities) - required_count,
    )


async def test_admin_creates_lists_and_gets_idempotent_graph_version(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "admin")
    proposal = await _approved_proposal(
        client,
        csrf,
        discovery_api_context.candidate.id,
    )

    first = await _create_version(client, csrf, proposal["id"])
    second = await _create_version(client, csrf, proposal["id"])
    listed = await client.get("/api/v1/graph-versions")
    detail = await client.get(f"/api/v1/graph-versions/{first['id']}")

    assert second["id"] == first["id"]
    assert first["status"] == "draft"
    assert first["attempt_count"] == 0
    assert listed.status_code == 200
    assert [value["id"] for value in listed.json()["data"]] == [first["id"]]
    assert "snapshot" not in listed.json()["data"][0]
    assert detail.status_code == 200
    assert detail.json()["data"]["snapshot"]["source_proposal_id"] == proposal["id"]


async def test_graph_version_publish_is_idempotent(
    client,
    discovery_api_users,
    discovery_api_context,
    monkeypatch,
) -> None:
    csrf = await _login(client, "admin")
    proposal = await _approved_proposal(
        client,
        csrf,
        discovery_api_context.candidate.id,
    )
    version = await _create_version(client, csrf, proposal["id"])
    publish_calls = 0

    async def successful_publisher(snapshot: dict, version_no: int):
        nonlocal publish_calls
        publish_calls += 1
        return _publish_result(snapshot)

    async def publish_with_fake(db, actor, version_id, **kwargs):
        return await service_publish_graph_version(
            db,
            actor,
            version_id,
            publisher=successful_publisher,
            **kwargs,
        )

    monkeypatch.setattr(
        "app.graph.router.publish_graph_version",
        publish_with_fake,
    )
    first = await client.post(
        f"/api/v1/graph-versions/{version['id']}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    second = await client.post(
        f"/api/v1/graph-versions/{version['id']}/publish",
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["status"] == "published"
    assert second.json()["data"]["id"] == version["id"]
    assert publish_calls == 1


async def test_hr_and_applicant_cannot_access_graph_versions(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    admin_csrf = await _login(client, "admin")
    proposal = await _approved_proposal(
        client,
        admin_csrf,
        discovery_api_context.candidate.id,
    )
    version = await _create_version(client, admin_csrf, proposal["id"])

    for role in ("hr", "applicant"):
        csrf = await _login(client, role)
        responses = [
            await client.get("/api/v1/graph-versions"),
            await client.get(f"/api/v1/graph-versions/{version['id']}"),
            await client.post(
                "/api/v1/graph-versions",
                json={"proposal_id": proposal["id"]},
                headers={"X-CSRF-Token": csrf},
            ),
            await client.post(
                f"/api/v1/graph-versions/{version['id']}/publish",
                headers={"X-CSRF-Token": csrf},
            ),
        ]
        assert all(response.status_code == 403 for response in responses)
        assert all(
            response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
            for response in responses
        )


async def test_graph_version_writes_require_csrf(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "admin")
    proposal = await _approved_proposal(
        client,
        csrf,
        discovery_api_context.candidate.id,
    )

    denied_create = await client.post(
        "/api/v1/graph-versions",
        json={"proposal_id": proposal["id"]},
    )
    version = await _create_version(client, csrf, proposal["id"])
    denied_publish = await client.post(
        f"/api/v1/graph-versions/{version['id']}/publish"
    )

    assert denied_create.status_code == 403
    assert denied_publish.status_code == 403
    assert denied_create.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"
    assert denied_publish.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_graph_publish_failure_returns_stable_error_and_failed_detail(
    client,
    discovery_api_users,
    discovery_api_context,
    monkeypatch,
) -> None:
    csrf = await _login(client, "admin")
    proposal = await _approved_proposal(
        client,
        csrf,
        discovery_api_context.candidate.id,
    )
    version = await _create_version(client, csrf, proposal["id"])

    async def failed_publisher(snapshot: dict, version_no: int):
        raise RuntimeError("secret neo4j address")

    async def publish_with_failure(db, actor, version_id, **kwargs):
        return await service_publish_graph_version(
            db,
            actor,
            version_id,
            publisher=failed_publisher,
            **kwargs,
        )

    monkeypatch.setattr(
        "app.graph.router.publish_graph_version",
        publish_with_failure,
    )
    response = await client.post(
        f"/api/v1/graph-versions/{version['id']}/publish",
        headers={"X-CSRF-Token": csrf},
    )
    detail = await client.get(f"/api/v1/graph-versions/{version['id']}")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GRAPH_PUBLICATION_FAILED"
    assert "secret" not in response.text
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "failed"
    assert detail.json()["data"]["last_error"] == "RuntimeError"
