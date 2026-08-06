from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import CSRF, DB, Admin, Staff
from app.discovery.schemas import DiscoveryRunCreate
from app.discovery.service import (
    candidate_detail,
    candidate_evidence,
    create_discovery_run,
    get_discovery_run,
    list_candidates,
    list_discovery_runs,
)

router = APIRouter(tags=["discovery"])


@router.post("/discovery-runs", status_code=202)
async def create_run(
    request: Request,
    payload: DiscoveryRunCreate,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
) -> dict:
    return {
        "data": await create_discovery_run(
            db,
            actor,
            payload,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.get("/discovery-runs")
async def runs(
    db: DB,
    actor: Staff,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {"data": await list_discovery_runs(db, page=page, page_size=page_size)}


@router.get("/discovery-runs/{run_id}")
async def run_detail(run_id: UUID, db: DB, actor: Staff) -> dict:
    return {"data": await get_discovery_run(db, run_id)}


@router.get("/discovery-candidates")
async def candidates(
    db: DB,
    actor: Staff,
    discovery_run_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {
        "data": await list_candidates(
            db,
            discovery_run_id=discovery_run_id,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/discovery-candidates/{candidate_id}")
async def candidate(candidate_id: UUID, db: DB, actor: Staff) -> dict:
    return {"data": await candidate_detail(db, candidate_id)}


@router.get("/discovery-candidates/{candidate_id}/evidence")
async def evidence(
    candidate_id: UUID,
    db: DB,
    actor: Staff,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> dict:
    return {
        "data": await candidate_evidence(
            db,
            candidate_id,
            page=page,
            page_size=page_size,
        )
    }
