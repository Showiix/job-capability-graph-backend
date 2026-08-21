from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile

from app.api.dependencies import CSRF, DB, Identity
from app.recruitment.schemas import (
    RecruitmentProjectCreateRequest,
    RequirementsReplaceRequest,
)
from app.recruitment.service import (
    candidate_detail,
    confirm_requirements,
    create_match_run,
    create_project,
    get_visible_project,
    list_candidates,
    list_match_results,
    list_match_runs,
    list_projects,
    match_result_detail,
    project_detail,
    replace_requirements,
    submit_jd,
    upload_candidates,
)

router = APIRouter(prefix="/recruitment-projects", tags=["recruitment"])


@router.post("", status_code=201)
async def create(
    payload: RecruitmentProjectCreateRequest,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    return {
        "data": await create_project(
            db,
            actor,
            payload,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.get("")
async def listing(
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    actor, _ = identity
    return {
        "data": await list_projects(
            db,
            actor,
            page=page,
            page_size=page_size,
            query=q,
        )
    }


@router.post("/{project_id}/jd", status_code=202)
async def upload_jd(
    project_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
    text: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    actor, _ = identity
    response = await submit_jd(
        db,
        project_id,
        actor,
        text=text,
        upload=file,
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": response.model_dump(mode="json")}


@router.put("/{project_id}/requirements")
async def replace(
    project_id: UUID,
    payload: RequirementsReplaceRequest,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    return {
        "data": await replace_requirements(
            db,
            project_id,
            actor,
            payload,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.post("/{project_id}/requirements/confirm")
async def confirm(
    project_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    response = await confirm_requirements(
        db,
        project_id,
        actor,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": response.model_dump(mode="json")}


@router.post("/{project_id}/candidates", status_code=202)
async def upload_candidate_batch(
    project_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    actor, _ = identity
    response = await upload_candidates(
        db,
        project_id,
        actor,
        files or [],
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": response.model_dump(mode="json")}


@router.get("/{project_id}/candidates")
async def candidate_listing(
    project_id: UUID,
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Annotated[
        Literal["uploaded", "processing", "ready", "failed"] | None,
        Query(),
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    actor, _ = identity
    return {
        "data": await list_candidates(
            db,
            project_id,
            actor,
            page=page,
            page_size=page_size,
            parse_status=status,
            query=q,
        )
    }


@router.get("/{project_id}/candidates/{candidate_id}")
async def candidate(
    project_id: UUID,
    candidate_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    return {
        "data": await candidate_detail(
            db,
            project_id,
            candidate_id,
            actor,
        )
    }


@router.post("/{project_id}/match-runs")
async def match(
    project_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> dict:
    actor, _ = identity
    return {
        "data": await create_match_run(
            db,
            project_id,
            actor,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.get("/{project_id}/match-runs")
async def match_history(
    project_id: UUID,
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    actor, _ = identity
    return {
        "data": await list_match_runs(
            db,
            project_id,
            actor,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/{project_id}/match-runs/{run_id}/results")
async def match_results(
    project_id: UUID,
    run_id: UUID,
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    actor, _ = identity
    return {
        "data": await list_match_results(
            db,
            project_id,
            run_id,
            actor,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/{project_id}/match-runs/{run_id}/results/{candidate_id}")
async def match_result(
    project_id: UUID,
    run_id: UUID,
    candidate_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    return {
        "data": await match_result_detail(
            db,
            project_id,
            run_id,
            candidate_id,
            actor,
        )
    }


@router.get("/{project_id}")
async def detail(
    project_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    project = await get_visible_project(db, project_id, actor)
    return {"data": await project_detail(db, project)}
