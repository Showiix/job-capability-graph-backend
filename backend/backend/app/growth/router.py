from uuid import UUID

from fastapi import APIRouter, Request

from app.api.dependencies import CSRF, DB, Identity
from app.growth.service import create_or_reuse_growth_path, get_growth_path

router = APIRouter(prefix="/job-recommendations", tags=["growth-paths"])


@router.post("/{match_run_id}/job-roles/{job_role_id}/growth-path")
async def create(
    match_run_id: UUID,
    job_role_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    value = await create_or_reuse_growth_path(
        db,
        actor,
        match_run_id,
        job_role_id,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": value.model_dump(mode="json")}


@router.get("/{match_run_id}/job-roles/{job_role_id}/growth-path")
async def read(
    match_run_id: UUID,
    job_role_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    value = await get_growth_path(
        db,
        actor,
        match_run_id,
        job_role_id,
    )
    return {"data": value.model_dump(mode="json")}
