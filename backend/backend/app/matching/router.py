from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import CSRF, DB, Identity

from .schemas import JobRecommendationCreate, RecommendationCreateData
from .service import (
    create_or_reuse_recommendations,
    get_match_result_detail,
    get_match_run_results,
    list_match_runs,
)

router = APIRouter(prefix="/job-recommendations", tags=["job-recommendations"])


@router.post("")
async def create(
    payload: JobRecommendationCreate,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    created = await create_or_reuse_recommendations(
        db,
        actor,
        payload.resume_id,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    data = await get_match_run_results(
        db,
        actor,
        created.run.id,
        page=1,
        page_size=20,
    )
    return {
        "data": RecommendationCreateData(
            reused=created.reused,
            run=data.run,
            results=data.results,
        ).model_dump(mode="json")
    }


@router.get("")
async def listing(
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    resume_id: UUID | None = None,
) -> dict:
    actor, _ = identity
    value = await list_match_runs(
        db,
        actor,
        page=page,
        page_size=page_size,
        resume_id=resume_id,
    )
    return {"data": value.model_dump(mode="json")}


@router.get("/{match_run_id}")
async def results(
    match_run_id: UUID,
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    actor, _ = identity
    value = await get_match_run_results(
        db,
        actor,
        match_run_id,
        page=page,
        page_size=page_size,
    )
    return {"data": value.model_dump(mode="json")}


@router.get("/{match_run_id}/job-roles/{job_role_id}")
async def result_detail(
    match_run_id: UUID,
    job_role_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    value = await get_match_result_detail(
        db,
        actor,
        match_run_id,
        job_role_id,
    )
    return {"data": value.model_dump(mode="json")}
