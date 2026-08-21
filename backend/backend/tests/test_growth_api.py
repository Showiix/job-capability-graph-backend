from types import SimpleNamespace

from pydantic import SecretStr

from app.core.security import hash_password
from app.growth import router as growth_router
from app.growth import service as growth_service
from app.growth.schemas import GrowthPlanLLM
from app.llm.responses import StructuredResponseResult
from app.matching import service as matching_service
from tests.matching_fixtures import build_matching_context


async def _login(client, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "growth-password"},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def _prepare_context(db_session, monkeypatch):
    context = await build_matching_context(db_session)
    for user in (
        context.applicant,
        context.other_applicant,
        context.admin,
        context.hr,
    ):
        user.password_hash = hash_password("growth-password")
    await db_session.flush()
    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="growth-api-match",
        ip_address=None,
    )
    missing_result = next(
        result
        for result in created.results
        if result.job_role_id == context.job_roles[1].id
    )
    complete_result = next(
        result
        for result in created.results
        if result.job_role_id == context.job_roles[0].id
    )
    monkeypatch.setattr(
        growth_service,
        "get_settings",
        lambda: SimpleNamespace(
            llm_responses_url="https://provider.test/v1/responses",
            llm_api_key=SecretStr("secret"),
            llm_model="test-model",
        ),
    )

    async def provider(**kwargs):
        capability_ids = [
            item["capability_id"]
            for item in kwargs["context"]["missing_required_capabilities"]
        ]
        return StructuredResponseResult(
            payload=GrowthPlanLLM.model_validate(
                {
                    "schema_version": "growth_path_v1",
                    "summary": "掌握缺失技能并完成实践。",
                    "stages": [
                        {
                            "stage_no": 1,
                            "title": "能力补齐",
                            "objective": "补齐岗位必备技能。",
                            "capability_ids": capability_ids,
                            "estimated_weeks": 2,
                            "actions": ["完成针对性练习"],
                            "completion_criteria": ["独立完成练习"],
                        }
                    ],
                    "final_project": "完成综合项目。",
                }
            ),
            response_id="resp_api",
            returned_model="returned-model",
            status="completed",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            provider_attempts=1,
            response_sha256="hash",
        )

    original_create = growth_service.create_or_reuse_growth_path

    async def create_with_provider(*args, **kwargs):
        return await original_create(*args, **kwargs, provider=provider)

    monkeypatch.setattr(
        growth_router,
        "create_or_reuse_growth_path",
        create_with_provider,
    )
    return context, created.run, missing_result, complete_result


async def test_growth_api_creates_reuses_and_reads(
    client,
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await _prepare_context(db_session, monkeypatch)
    csrf = await _login(client, context.applicant.username)
    path = (
        f"/api/v1/job-recommendations/{run.id}"
        f"/job-roles/{result.job_role_id}/growth-path"
    )

    missing_csrf = await client.post(path)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"

    created = await client.post(path, headers={"X-CSRF-Token": csrf})
    reused = await client.post(path, headers={"X-CSRF-Token": csrf})
    loaded = await client.get(path)

    assert created.status_code == 200
    assert created.json()["data"]["reused"] is False
    assert reused.status_code == 200
    assert reused.json()["data"]["reused"] is True
    assert loaded.status_code == 200
    assert loaded.json()["data"]["id"] == created.json()["data"]["growth_path"]["id"]


async def test_growth_api_enforces_owner_and_roles(
    client,
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await _prepare_context(db_session, monkeypatch)
    applicant_username = context.applicant.username
    other_username = context.other_applicant.username
    admin_username = context.admin.username
    hr_username = context.hr.username
    applicant_csrf = await _login(client, applicant_username)
    path = (
        f"/api/v1/job-recommendations/{run.id}"
        f"/job-roles/{result.job_role_id}/growth-path"
    )
    created = await client.post(
        path,
        headers={"X-CSRF-Token": applicant_csrf},
    )
    assert created.status_code == 200

    other_csrf = await _login(client, other_username)
    hidden_get = await client.get(path)
    hidden_post = await client.post(path, headers={"X-CSRF-Token": other_csrf})
    assert hidden_get.status_code == hidden_post.status_code == 404
    assert hidden_get.json()["error"]["code"] == "MATCH_RUN_NOT_FOUND"

    admin_csrf = await _login(client, admin_username)
    admin_get = await client.get(path)
    admin_post = await client.post(path, headers={"X-CSRF-Token": admin_csrf})
    assert admin_get.status_code == admin_post.status_code == 200

    hr_csrf = await _login(client, hr_username)
    denied_get = await client.get(path)
    denied_post = await client.post(path, headers={"X-CSRF-Token": hr_csrf})
    assert denied_get.status_code == denied_post.status_code == 403
    assert denied_get.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_growth_api_handles_no_gap_and_missing_path(
    client,
    db_session,
    monkeypatch,
) -> None:
    context, run, _, complete_result = await _prepare_context(
        db_session,
        monkeypatch,
    )
    csrf = await _login(client, context.applicant.username)
    path = (
        f"/api/v1/job-recommendations/{run.id}"
        f"/job-roles/{complete_result.job_role_id}/growth-path"
    )

    missing = await client.get(path)
    not_required = await client.post(path, headers={"X-CSRF-Token": csrf})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "GROWTH_PATH_NOT_FOUND"
    assert not_required.status_code == 409
    assert not_required.json()["error"]["code"] == "GROWTH_PATH_NOT_REQUIRED"
