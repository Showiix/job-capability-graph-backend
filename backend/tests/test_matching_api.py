from app.core.security import hash_password
from tests.matching_fixtures import build_matching_context


async def _prepare_context(db_session):
    context = await build_matching_context(db_session)
    for user in (
        context.applicant,
        context.other_applicant,
        context.admin,
        context.hr,
    ):
        user.password_hash = hash_password("matching-password")
    await db_session.flush()
    return context


async def _login(client, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "matching-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def test_applicant_recommendation_api_creates_reuses_and_reads_history(
    client,
    db_session,
) -> None:
    context = await _prepare_context(db_session)
    csrf = await _login(client, context.applicant.username)

    missing_csrf = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(context.resume.id)},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"

    created = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(context.resume.id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200
    assert created.json()["data"]["reused"] is False
    run_id = created.json()["data"]["run"]["id"]
    assert len(created.json()["data"]["results"]["items"]) == 2

    reused = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(context.resume.id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert reused.status_code == 200
    assert reused.json()["data"]["reused"] is True
    assert reused.json()["data"]["run"]["id"] == run_id

    history = await client.get("/api/v1/job-recommendations?page=1&page_size=1")
    assert history.status_code == 200
    assert history.json()["data"]["total"] == 1
    assert history.json()["data"]["items"][0]["id"] == run_id

    result_page = await client.get(
        f"/api/v1/job-recommendations/{run_id}?page=1&page_size=1"
    )
    assert result_page.status_code == 200
    assert len(result_page.json()["data"]["results"]["items"]) == 1

    job_role_id = result_page.json()["data"]["results"]["items"][0]["job_role_id"]
    detail = await client.get(
        f"/api/v1/job-recommendations/{run_id}/job-roles/{job_role_id}"
    )
    assert detail.status_code == 200
    assert "matched_capabilities" in detail.json()["data"]["result"]
    assert "missing_capabilities" in detail.json()["data"]["result"]


async def test_recommendation_api_enforces_roles_ownership_and_validation(
    client,
    db_session,
) -> None:
    context = await _prepare_context(db_session)
    admin_username = context.admin.username
    hr_username = context.hr.username
    resume_id = context.resume.id
    other_username = context.other_applicant.username
    csrf = await _login(client, context.applicant.username)

    invalid_body = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(resume_id), "page": 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid_body.status_code == 422

    other_csrf = await _login(client, other_username)
    hidden = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(resume_id)},
        headers={"X-CSRF-Token": other_csrf},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "RESOURCE_NOT_OWNED"

    admin_csrf = await _login(client, admin_username)
    admin_created = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(resume_id)},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert admin_created.status_code == 200
    assert admin_created.json()["data"]["reused"] is False

    hr_csrf = await _login(client, hr_username)
    denied = await client.get("/api/v1/job-recommendations")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    denied_post = await client.post(
        "/api/v1/job-recommendations",
        json={"resume_id": str(resume_id)},
        headers={"X-CSRF-Token": hr_csrf},
    )
    assert denied_post.status_code == 403
    assert denied_post.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_recommendation_api_rejects_pagination_bounds(client, db_session) -> None:
    context = await _prepare_context(db_session)
    await _login(client, context.applicant.username)

    invalid_page = await client.get("/api/v1/job-recommendations?page=0")
    assert invalid_page.status_code == 422
    invalid_size = await client.get("/api/v1/job-recommendations?page_size=101")
    assert invalid_size.status_code == 422
