from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.dependencies import CSRF, DB, Identity
from app.core.errors import APIError
from app.processing.models import ProcessingError, ProcessingRun
from app.processing.schemas import ProcessingErrorResponse, ProcessingRunResponse
from app.processing.service import (
    cancel_run,
    get_visible_run,
    retry_run,
    visible_run_predicate,
)

router = APIRouter(prefix="/processing-runs", tags=["processing-runs"])
RUN_STATUSES = Literal[
    "pending",
    "enqueue_failed",
    "running",
    "waiting_review",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
]


@router.get("")
async def list_runs(
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    run_type: str | None = Query(default=None, max_length=60),
    status: RUN_STATUSES | None = None,
    subject_type: str | None = Query(default=None, max_length=50),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> dict:
    actor, _ = identity
    filters = [visible_run_predicate(actor)]
    if run_type is not None:
        filters.append(ProcessingRun.run_type == run_type)
    if status is not None:
        filters.append(ProcessingRun.status == status)
    if subject_type is not None:
        filters.append(ProcessingRun.subject_type == subject_type)
    if created_from is not None:
        filters.append(ProcessingRun.created_at >= created_from)
    if created_to is not None:
        filters.append(ProcessingRun.created_at <= created_to)
    runs = (
        await db.scalars(
            select(ProcessingRun)
            .where(*filters)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {"data": [_run_data(run) for run in runs]}


@router.get("/{run_id}")
async def detail(run_id: UUID, db: DB, identity: Identity) -> dict:
    actor, _ = identity
    return {"data": _run_data(await get_visible_run(db, run_id, actor))}


@router.get("/{run_id}/errors")
async def errors(
    run_id: UUID,
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> dict:
    actor, _ = identity
    run = await get_visible_run(db, run_id, actor)
    values = (
        await db.scalars(
            select(ProcessingError)
            .where(ProcessingError.run_id == run.id)
            .order_by(ProcessingError.occurred_at.asc(), ProcessingError.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "data": [
            ProcessingErrorResponse.model_validate(value).model_dump(mode="json")
            for value in values
        ]
    }


@router.get("/{run_id}/result")
async def result(run_id: UUID, db: DB, identity: Identity) -> dict:
    actor, _ = identity
    run = await get_visible_run(db, run_id, actor)
    if run.status not in {"completed", "waiting_review"} or not run.result_summary.get(
        "result_url"
    ):
        raise APIError(409, "RUN_RESULT_NOT_READY", "任务结果尚未就绪")
    return {"data": run.result_summary}


@router.post("/{run_id}/retry", status_code=202)
async def retry(
    run_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    old = await get_visible_run(db, run_id, actor)
    new = await retry_run(
        db,
        old,
        actor,
        request_id=request.state.request_id,
        ip_address=_client_ip(request),
    )
    return {"data": _run_data(new)}


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> JSONResponse:
    actor, _ = identity
    run = await get_visible_run(db, run_id, actor)
    run, status_code = await cancel_run(
        db,
        run,
        actor,
        request_id=request.state.request_id,
        ip_address=_client_ip(request),
    )
    return JSONResponse(status_code=status_code, content={"data": _run_data(run)})


def _run_data(run: ProcessingRun) -> dict:
    return ProcessingRunResponse.model_validate(run).model_dump(mode="json")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
