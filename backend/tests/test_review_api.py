pytest_plugins = ("tests.test_discovery_api",)


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


async def _create(client, csrf: str, candidate_id) -> dict:
    response = await client.post(
        "/api/v1/review-proposals",
        json={"candidate_id": str(candidate_id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()["data"]


async def test_admin_creates_and_queries_review_proposal(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "admin")

    proposal = await _create(client, csrf, discovery_api_context.candidate.id)
    listed = await client.get("/api/v1/review-proposals?status=pending")
    detail = await client.get(f"/api/v1/review-proposals/{proposal['id']}")

    assert listed.status_code == 200
    assert [value["id"] for value in listed.json()["data"]] == [proposal["id"]]
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["review_status"] == "pending"
    assert data["proposed_payload"]["role_name"] == "Python + 自动化测试"
    assert data["decisions"] == []
    serialized = detail.text
    assert "secret raw body" not in serialized
    assert "secret normalized body" not in serialized
    assert '"secret":"payload"' not in serialized


async def test_hr_revises_and_approves_proposal(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    admin_csrf = await _login(client, "admin")
    proposal = await _create(
        client,
        admin_csrf,
        discovery_api_context.candidate.id,
    )
    required_ids = proposal["proposed_payload"]["required_capability_ids"]
    hr_csrf = await _login(client, "hr")
    revised_payload = {
        "role_name": "AI 自动化测试工程师",
        "core_responsibilities": ["建设 AI 产品自动化测试体系"],
        "required_capability_ids": required_ids,
        "bonus_capability_ids": [],
        "industry_scenarios": ["AI 产品质量保障"],
        "generation_source": "human_revision",
        "definition_status": "reviewed",
    }

    revised = await client.post(
        f"/api/v1/review-proposals/{proposal['id']}/decisions",
        json={
            "decision": "revise",
            "after_payload": revised_payload,
            "comment": "补充职责后再确认",
        },
        headers={"X-CSRF-Token": hr_csrf},
    )
    approved = await client.post(
        f"/api/v1/review-proposals/{proposal['id']}/decisions",
        json={"decision": "approve", "comment": "确认采纳"},
        headers={"X-CSRF-Token": hr_csrf},
    )

    assert revised.status_code == 200
    assert revised.json()["data"]["review_status"] == "needs_revision"
    assert approved.status_code == 200
    data = approved.json()["data"]
    assert data["review_status"] == "approved"
    assert data["proposed_payload"]["role_name"] == "AI 自动化测试工程师"
    assert [value["decision"] for value in data["decisions"]] == [
        "revise",
        "approve",
    ]


async def test_applicant_cannot_access_review_workflow(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    admin_csrf = await _login(client, "admin")
    proposal = await _create(
        client,
        admin_csrf,
        discovery_api_context.candidate.id,
    )
    applicant_csrf = await _login(client, "applicant")

    responses = [
        await client.get("/api/v1/review-proposals"),
        await client.get(f"/api/v1/review-proposals/{proposal['id']}"),
        await client.post(
            "/api/v1/review-proposals",
            json={"candidate_id": str(discovery_api_context.candidate.id)},
            headers={"X-CSRF-Token": applicant_csrf},
        ),
        await client.post(
            f"/api/v1/review-proposals/{proposal['id']}/decisions",
            json={"decision": "approve"},
            headers={"X-CSRF-Token": applicant_csrf},
        ),
    ]

    assert all(response.status_code == 403 for response in responses)
    assert all(
        response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
        for response in responses
    )


async def test_review_writes_require_csrf(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    await _login(client, "hr")

    response = await client.post(
        "/api/v1/review-proposals",
        json={"candidate_id": str(discovery_api_context.candidate.id)},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_review_validation_errors_and_status_filter_are_stable(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "hr")
    proposal = await _create(client, csrf, discovery_api_context.candidate.id)

    missing_comment = await client.post(
        f"/api/v1/review-proposals/{proposal['id']}/decisions",
        json={"decision": "reject"},
        headers={"X-CSRF-Token": csrf},
    )
    rejected = await client.post(
        f"/api/v1/review-proposals/{proposal['id']}/decisions",
        json={"decision": "reject", "comment": "证据不足"},
        headers={"X-CSRF-Token": csrf},
    )
    pending = await client.get("/api/v1/review-proposals?status=pending")
    rejected_list = await client.get(
        "/api/v1/review-proposals?status=rejected&page=1&page_size=20"
    )

    assert missing_comment.status_code == 422
    assert missing_comment.json()["error"]["code"] == (
        "REVIEW_DECISION_COMMENT_REQUIRED"
    )
    assert rejected.status_code == 200
    assert pending.json()["data"] == []
    assert [value["id"] for value in rejected_list.json()["data"]] == [
        proposal["id"]
    ]
