from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import CSRF, DB, Admin
from app.graph.schemas import GraphVersionCreate
from app.graph.service import (
    create_graph_version,
    get_graph_version,
    graph_version_data,
    list_graph_versions,
    publish_graph_version,
)

router = APIRouter(prefix="/graph-versions", tags=["graph"])


@router.post("", status_code=201)
async def create_version(
    request: Request,
    payload: GraphVersionCreate,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
) -> dict:
    value = await create_graph_version(
        db,
        actor,
        payload.proposal_id,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": graph_version_data(value, include_snapshot=True)}


@router.get("")
async def versions(
    db: DB,
    actor: Admin,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {
        "data": await list_graph_versions(
            db,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/{version_id}")
async def version_detail(version_id: UUID, db: DB, actor: Admin) -> dict:
    value = await get_graph_version(db, version_id)
    return {"data": graph_version_data(value, include_snapshot=True)}


@router.post("/{version_id}/publish")
async def publish_version(
    version_id: UUID,
    request: Request,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
) -> dict:
    value = await publish_graph_version(
        db,
        actor,
        version_id,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": graph_version_data(value, include_snapshot=True)}
