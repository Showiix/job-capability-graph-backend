from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.core.config import get_settings
from app.core.errors import APIError
from app.growth.llm import PROMPT_VERSION, generate_growth_path
from app.growth.models import GrowthPath
from app.growth.schemas import (
    GrowthCapabilityRead,
    GrowthPathCreateResponse,
    GrowthPathRead,
    GrowthPathScopeError,
    GrowthPlanLLM,
    GrowthPlanRead,
    GrowthSourceRead,
    GrowthStageRead,
    validate_capability_scope,
)
from app.llm.responses import (
    ResponsesAPIError,
    StructuredResponseResult,
    create_responses_http_client,
)
from app.matching.models import MatchResult, MatchRun
from app.matching.service import get_visible_match_result_record

GrowthProvider = Callable[
    ..., Awaitable[StructuredResponseResult[GrowthPlanLLM]]
]

LLM_ERROR_MESSAGES = {
    "LLM_TIMEOUT": "成长路径生成请求超时",
    "LLM_RATE_LIMITED": "成长路径生成服务暂时繁忙",
    "LLM_UPSTREAM_ERROR": "成长路径生成服务暂时不可用",
    "LLM_REQUEST_REJECTED": "成长路径生成请求被上游拒绝",
    "LLM_RESPONSE_REFUSED": "成长路径生成服务拒绝处理该请求",
    "LLM_RESPONSE_INCOMPLETE": "成长路径生成结果不完整",
    "LLM_RESPONSE_INVALID": "成长路径生成结果格式无效",
}


async def create_or_reuse_growth_path(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
    provider: GrowthProvider | None = None,
) -> GrowthPathCreateResponse:
    try:
        run, result = await get_visible_match_result_record(
            db,
            actor,
            match_run_id,
            job_role_id,
        )
        source_snapshot = _source_snapshot(run, result)
        missing = source_snapshot["match_result"][
            "missing_required_capabilities"
        ]
        if not missing:
            raise APIError(
                409,
                "GROWTH_PATH_NOT_REQUIRED",
                "该岗位没有缺失的必备技能",
            )

        existing = await _find_growth_path(db, match_run_id, job_role_id)
        if existing is not None:
            _record_growth_audit(
                db,
                action="growth_path.reuse",
                actor=actor,
                growth_path=existing,
                missing_count=len(missing),
                request_id=request_id,
                ip_address=ip_address,
            )
            await db.commit()
            return GrowthPathCreateResponse(
                reused=True,
                growth_path=_growth_path_read(existing),
            )

        settings = get_settings()
        if not all(
            (
                settings.llm_responses_url,
                settings.llm_api_key,
                settings.llm_model,
            )
        ):
            raise APIError(
                503,
                "LLM_NOT_CONFIGURED",
                "成长路径生成服务尚未配置",
            )

        growth_path_id = uuid4()
        request = {
            "url": str(settings.llm_responses_url),
            "api_key": settings.llm_api_key.get_secret_value(),
            "model": settings.llm_model,
            "growth_path_id": growth_path_id,
            "match_run_id": match_run_id,
            "job_role_id": job_role_id,
            "context": deepcopy(source_snapshot["match_result"]),
            "request_id": request_id,
        }
        if db.in_transaction():
            await db.commit()

        llm_result = await _call_provider(provider, request)
        expected_ids = {
            UUID(item["capability_id"])
            for item in missing
        }
        validate_capability_scope(llm_result.payload, expected_ids)
        plan = _hydrate_plan(llm_result.payload, result, missing)
        growth_path = GrowthPath(
            id=growth_path_id,
            match_run_id=match_run_id,
            job_role_id=job_role_id,
            prompt_version=PROMPT_VERSION,
            source_snapshot=source_snapshot,
            path_payload=plan.model_dump(mode="json"),
            generation_metadata={
                "requested_model": settings.llm_model,
                "returned_model": llm_result.returned_model,
                "response_id": llm_result.response_id,
                "provider_attempts": llm_result.provider_attempts,
                "usage": llm_result.usage,
                "response_sha256": llm_result.response_sha256,
            },
        )
        db.add(growth_path)
        _record_growth_audit(
            db,
            action="growth_path.create",
            actor=actor,
            growth_path=growth_path,
            missing_count=len(missing),
            request_id=request_id,
            ip_address=ip_address,
        )
        try:
            await db.commit()
        except IntegrityError as error:
            if not _is_natural_key_conflict(error):
                raise
            await db.rollback()
            return await _reuse_after_conflict(
                db,
                actor,
                match_run_id,
                job_role_id,
                missing_count=len(missing),
                request_id=request_id,
                ip_address=ip_address,
            )
        return GrowthPathCreateResponse(
            reused=False,
            growth_path=_growth_path_read(growth_path),
        )
    except ResponsesAPIError as error:
        await db.rollback()
        raise _provider_api_error(error) from error
    except GrowthPathScopeError as error:
        await db.rollback()
        raise APIError(
            502,
            "GROWTH_PATH_RESPONSE_INVALID",
            "成长路径技能范围无效",
        ) from error
    except APIError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


async def get_growth_path(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
) -> GrowthPathRead:
    await get_visible_match_result_record(
        db,
        actor,
        match_run_id,
        job_role_id,
    )
    growth_path = await _find_growth_path(db, match_run_id, job_role_id)
    if growth_path is None:
        raise APIError(404, "GROWTH_PATH_NOT_FOUND", "成长路径不存在")
    return _growth_path_read(growth_path)


async def _call_provider(
    provider: GrowthProvider | None,
    request: dict[str, Any],
) -> StructuredResponseResult[GrowthPlanLLM]:
    if provider is not None:
        return await provider(**request)
    async with create_responses_http_client() as http:
        return await generate_growth_path(http=http, **request)


def _source_snapshot(run: MatchRun, result: MatchResult) -> dict[str, Any]:
    matched = [
        {
            "capability_id": item["capability_id"],
            "canonical_name": item["canonical_name"],
            "requirement_type": item["requirement_type"],
            "importance": item["importance"],
            "evidence_strength": item.get("resume_skill", {}).get(
                "evidence_strength"
            ),
        }
        for item in result.matched_capabilities
    ]
    missing = [
        deepcopy(item)
        for item in result.missing_capabilities
        if item.get("requirement_type") == "required"
    ]
    return {
        "match_run": {
            "id": str(run.id),
            "resume_profile_id": str(run.resume_profile_id),
            "graph_version_id": str(run.graph_version_id),
            "catalog_version_id": str(run.catalog_version_id),
            "weight_version": run.weight_version,
        },
        "match_result": {
            "job_role_id": str(result.job_role_id),
            "rank": result.rank,
            "total_score": float(result.total_score),
            "match_level": result.match_level,
            "job_role": deepcopy(result.job_role_snapshot),
            "dimension_scores": deepcopy(result.dimension_scores),
            "gap_summary": deepcopy(result.gap_summary),
            "matched_capabilities": matched,
            "missing_required_capabilities": missing,
        },
    }


def _hydrate_plan(
    llm_plan: GrowthPlanLLM,
    result: MatchResult,
    missing: list[dict[str, Any]],
) -> GrowthPlanRead:
    capability_map = {
        UUID(item["capability_id"]): GrowthCapabilityRead(
            id=item["capability_id"],
            canonical_name=item["canonical_name"],
            skill_type=item["skill_type"],
            domain=item["domain"],
        )
        for item in missing
    }
    stages = [
        GrowthStageRead(
            stage_no=stage.stage_no,
            title=stage.title,
            objective=stage.objective,
            capabilities=[
                capability_map[capability_id]
                for capability_id in stage.capability_ids
            ],
            estimated_weeks=stage.estimated_weeks,
            actions=stage.actions,
            completion_criteria=stage.completion_criteria,
        )
        for stage in llm_plan.stages
    ]
    return GrowthPlanRead(
        schema_version=llm_plan.schema_version,
        target_role=result.job_role_snapshot,
        summary=llm_plan.summary,
        total_estimated_weeks=sum(stage.estimated_weeks for stage in stages),
        stages=stages,
        final_project=llm_plan.final_project,
    )


async def _find_growth_path(
    db: AsyncSession,
    match_run_id: UUID,
    job_role_id: UUID,
) -> GrowthPath | None:
    return await db.scalar(
        select(GrowthPath).where(
            GrowthPath.match_run_id == match_run_id,
            GrowthPath.job_role_id == job_role_id,
            GrowthPath.prompt_version == PROMPT_VERSION,
        )
    )


def _growth_path_read(growth_path: GrowthPath) -> GrowthPathRead:
    return GrowthPathRead(
        id=growth_path.id,
        match_run_id=growth_path.match_run_id,
        job_role_id=growth_path.job_role_id,
        prompt_version=growth_path.prompt_version,
        source=GrowthSourceRead.model_validate(growth_path.source_snapshot),
        plan=GrowthPlanRead.model_validate(growth_path.path_payload),
        created_at=growth_path.created_at,
    )


def _record_growth_audit(
    db: AsyncSession,
    *,
    action: str,
    actor: User,
    growth_path: GrowthPath,
    missing_count: int,
    request_id: str | None,
    ip_address: str | None,
) -> None:
    metadata = growth_path.generation_metadata
    record_audit(
        db,
        action=action,
        resource_type="growth_path",
        resource_id=growth_path.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "match_run_id": str(growth_path.match_run_id),
            "job_role_id": str(growth_path.job_role_id),
            "prompt_version": growth_path.prompt_version,
            "missing_required_capability_count": missing_count,
            "requested_model": metadata.get("requested_model"),
            "provider_attempts": metadata.get("provider_attempts"),
        },
    )


def _is_natural_key_conflict(error: IntegrityError) -> bool:
    original = error.orig
    constraint_name = getattr(original, "constraint_name", None)
    if constraint_name is None:
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name == "uq_growth_paths_match_role_prompt"


async def _reuse_after_conflict(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
    *,
    missing_count: int,
    request_id: str | None,
    ip_address: str | None,
) -> GrowthPathCreateResponse:
    winner = await _find_growth_path(db, match_run_id, job_role_id)
    if winner is None:
        raise RuntimeError("growth path conflict winner is unavailable")
    _record_growth_audit(
        db,
        action="growth_path.reuse",
        actor=actor,
        growth_path=winner,
        missing_count=missing_count,
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()
    return GrowthPathCreateResponse(
        reused=True,
        growth_path=_growth_path_read(winner),
    )


def _provider_api_error(error: ResponsesAPIError) -> APIError:
    status_code = (
        503
        if error.code in {"LLM_TIMEOUT", "LLM_RATE_LIMITED", "LLM_UPSTREAM_ERROR"}
        else 502
    )
    return APIError(
        status_code,
        error.code,
        LLM_ERROR_MESSAGES.get(error.code, "成长路径生成失败"),
    )
