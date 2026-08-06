from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile

from app.api.dependencies import CSRF, DB, Identity
from app.resumes.service import (
    create_resume,
    extracted_text,
    get_visible_resume,
    list_profiles,
    list_resumes,
    profile_detail,
    resume_detail,
)

router = APIRouter(prefix="/resumes", tags=["resumes"])
ResumeParseStatus = Literal["uploaded", "processing", "ready", "failed", "archived"]


@router.get("")
async def listing(
    db: DB,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    parse_status: Annotated[ResumeParseStatus | None, Query()] = None,
) -> dict:
    actor, _ = identity
    return {
        "data": await list_resumes(
            db,
            actor,
            page=page,
            page_size=page_size,
            parse_status=parse_status,
        )
    }


@router.post("", status_code=202)
async def create(
    request: Request,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
    file: Annotated[UploadFile, File()],
    display_name: Annotated[str | None, Form(max_length=200)] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ] = None,
) -> dict:
    actor, _ = identity
    value = await create_resume(
        db,
        actor,
        file,
        display_name=display_name,
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": value.model_dump(mode="json")}


@router.get("/{resume_id}/profiles")
async def profiles(
    resume_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    resume = await get_visible_resume(db, resume_id, actor)
    return {"data": await list_profiles(db, resume)}


@router.get("/{resume_id}/profiles/{version_no}")
async def profile(
    resume_id: UUID,
    version_no: int,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    resume = await get_visible_resume(db, resume_id, actor)
    return {"data": await profile_detail(db, resume, version_no)}


@router.get("/{resume_id}/extracted-text")
async def get_extracted_text(
    resume_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    resume = await get_visible_resume(db, resume_id, actor)
    return {
        "data": await extracted_text(
            db,
            resume,
            actor,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.get("/{resume_id}")
async def detail(
    resume_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    actor, _ = identity
    resume = await get_visible_resume(db, resume_id, actor)
    return {"data": await resume_detail(db, resume, actor)}
