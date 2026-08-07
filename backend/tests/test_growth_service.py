import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.core.errors import APIError
from app.growth import service as growth_service
from app.growth.models import GrowthPath
from app.growth.schemas import GrowthPlanLLM
from app.llm.responses import ResponsesAPIError, StructuredResponseResult
from app.matching import service as matching_service
from tests.matching_fixtures import build_matching_context


def configured_settings():
    return SimpleNamespace(
        llm_responses_url="https://provider.test/v1/responses",
        llm_api_key=SecretStr("secret"),
        llm_model="test-model",
    )


def provider_result(capability_ids, *, weeks: int = 2):
    return StructuredResponseResult(
        payload=GrowthPlanLLM.model_validate(
            {
                "schema_version": "growth_path_v1",
                "summary": "先掌握缺失技能，再完成综合实践。",
                "stages": [
                    {
                        "stage_no": 1,
                        "title": "核心能力",
                        "objective": "掌握岗位要求的缺失技能。",
                        "capability_ids": [str(value) for value in capability_ids],
                        "estimated_weeks": weeks,
                        "actions": ["完成针对性练习"],
                        "completion_criteria": ["能够独立完成练习"],
                    }
                ],
                "final_project": "完成一个覆盖缺失能力的综合项目。",
            }
        ),
        response_id="resp_growth",
        returned_model="returned-model",
        status="completed",
        usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        provider_attempts=1,
        response_sha256="response-hash",
    )


async def prepared_match(db_session):
    context = await build_matching_context(db_session)
    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="growth-match",
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
    return context, created.run, missing_result, complete_result


async def test_create_growth_path_uses_required_gaps_and_reuses(
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await prepared_match(db_session)
    monkeypatch.setattr(growth_service, "get_settings", configured_settings)
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        capability_ids = [
            item["capability_id"]
            for item in kwargs["context"]["missing_required_capabilities"]
        ]
        return provider_result(capability_ids)

    created = await growth_service.create_or_reuse_growth_path(
        db_session,
        context.applicant,
        run.id,
        result.job_role_id,
        request_id="growth-create",
        ip_address="127.0.0.1",
        provider=provider,
    )
    reused = await growth_service.create_or_reuse_growth_path(
        db_session,
        context.applicant,
        run.id,
        result.job_role_id,
        request_id="growth-reuse",
        ip_address=None,
        provider=provider,
    )

    assert created.reused is False
    assert reused.reused is True
    assert reused.growth_path.id == created.growth_path.id
    assert len(calls) == 1
    assert created.growth_path.plan.total_estimated_weeks == 2
    capability = created.growth_path.plan.stages[0].capabilities[0]
    assert capability.canonical_name == "Kubernetes"
    assert capability.domain.name == "人工智能"
    serialized_source = json.dumps(
        created.growth_path.source.model_dump(mode="json"),
        ensure_ascii=False,
    )
    assert "evidence_quote" not in serialized_source
    assert "raw_name" not in serialized_source
    assert "extracted_text" not in serialized_source
    assert calls[0]["context"] == created.growth_path.source.match_result
    assert calls[0]["api_key"] == "secret"
    assert (
        await db_session.scalar(select(func.count()).select_from(GrowthPath)) == 1
    )
    actions = (
        await db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.resource_id == created.growth_path.id)
            .order_by(AuditLog.created_at)
        )
    ).all()
    assert actions == ["growth_path.create", "growth_path.reuse"]


async def test_growth_path_rejects_result_without_required_gaps(
    db_session,
) -> None:
    context, run, _, complete_result = await prepared_match(db_session)
    called = False

    async def provider(**kwargs):
        nonlocal called
        called = True

    with pytest.raises(APIError) as error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.applicant,
            run.id,
            complete_result.job_role_id,
            provider=provider,
        )

    assert error.value.status_code == 409
    assert error.value.code == "GROWTH_PATH_NOT_REQUIRED"
    assert called is False


async def test_growth_path_enforces_role_and_owner(db_session) -> None:
    context, run, result, _ = await prepared_match(db_session)

    with pytest.raises(APIError) as hr_error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.hr,
            run.id,
            result.job_role_id,
        )
    with pytest.raises(APIError) as owner_error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.other_applicant,
            run.id,
            result.job_role_id,
        )

    assert hr_error.value.status_code == 403
    assert hr_error.value.code == "ROLE_NOT_ALLOWED"
    assert owner_error.value.status_code == 404
    assert owner_error.value.code == "MATCH_RUN_NOT_FOUND"


async def test_admin_growth_path_records_actual_actor(
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await prepared_match(db_session)
    monkeypatch.setattr(growth_service, "get_settings", configured_settings)
    capability_id = context.capabilities["Kubernetes"].id

    async def provider(**kwargs):
        return provider_result([capability_id])

    created = await growth_service.create_or_reuse_growth_path(
        db_session,
        context.admin,
        run.id,
        result.job_role_id,
        provider=provider,
    )
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.resource_id == created.growth_path.id)
    )

    assert created.reused is False
    assert audit.actor_user_id == context.admin.id


async def test_growth_path_scope_failure_leaves_no_row(
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await prepared_match(db_session)
    monkeypatch.setattr(growth_service, "get_settings", configured_settings)

    async def provider(**kwargs):
        return provider_result([context.capabilities["Python"].id])

    with pytest.raises(APIError) as error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.applicant,
            run.id,
            result.job_role_id,
            provider=provider,
        )

    assert error.value.status_code == 502
    assert error.value.code == "GROWTH_PATH_RESPONSE_INVALID"
    assert (
        await db_session.scalar(select(func.count()).select_from(GrowthPath)) == 0
    )


async def test_growth_path_provider_failure_leaves_no_row(
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await prepared_match(db_session)
    monkeypatch.setattr(growth_service, "get_settings", configured_settings)

    async def provider(**kwargs):
        raise ResponsesAPIError("LLM_TIMEOUT", "request", True)

    with pytest.raises(APIError) as error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.applicant,
            run.id,
            result.job_role_id,
            provider=provider,
        )

    assert error.value.status_code == 503
    assert error.value.code == "LLM_TIMEOUT"
    assert (
        await db_session.scalar(select(func.count()).select_from(GrowthPath)) == 0
    )


async def test_growth_path_requires_llm_configuration(db_session) -> None:
    context, run, result, _ = await prepared_match(db_session)

    with pytest.raises(APIError) as error:
        await growth_service.create_or_reuse_growth_path(
            db_session,
            context.applicant,
            run.id,
            result.job_role_id,
        )

    assert error.value.status_code == 503
    assert error.value.code == "LLM_NOT_CONFIGURED"


async def test_get_growth_path_returns_saved_path_or_not_found(
    db_session,
    monkeypatch,
) -> None:
    context, run, result, _ = await prepared_match(db_session)
    monkeypatch.setattr(growth_service, "get_settings", configured_settings)

    with pytest.raises(APIError) as missing:
        await growth_service.get_growth_path(
            db_session,
            context.applicant,
            run.id,
            result.job_role_id,
        )
    assert missing.value.code == "GROWTH_PATH_NOT_FOUND"

    async def provider(**kwargs):
        return provider_result([context.capabilities["Kubernetes"].id])

    created = await growth_service.create_or_reuse_growth_path(
        db_session,
        context.applicant,
        run.id,
        result.job_role_id,
        provider=provider,
    )
    loaded = await growth_service.get_growth_path(
        db_session,
        context.applicant,
        run.id,
        result.job_role_id,
    )

    assert loaded == created.growth_path
