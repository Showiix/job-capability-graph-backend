from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from app.api.dependencies import CSRF, DB, Admin, Identity
from app.catalog.service import (
    _import_data,
    create_catalog_import,
    current_version,
    get_catalog_import,
    list_capabilities,
    list_catalog_imports,
    list_domains,
    list_job_roles,
    list_versions,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.post("/imports", status_code=202)
async def upload_catalog(
    request: Request,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
    file: Annotated[UploadFile, File()],
    import_type: Annotated[str, Form(min_length=1, max_length=30)],
    schema_version: Annotated[str, Form(min_length=1, max_length=40)],
    mode: Annotated[str, Form(min_length=1, max_length=20)] = "validate_only",
) -> dict:
    value = await create_catalog_import(
        db,
        actor,
        file,
        import_type=import_type,
        schema_version=schema_version,
        mode=mode,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": value.model_dump(mode="json")}


@router.get("/imports")
async def imports(db: DB, actor: Admin) -> dict:
    return {"data": await list_catalog_imports(db)}


@router.get("/imports/{import_id}")
async def import_detail(import_id: UUID, db: DB, actor: Admin) -> dict:
    value = await get_catalog_import(db, import_id)
    return {"data": _import_data(value)}


@router.get("/versions")
async def versions(
    db: DB,
    identity: Identity,
    include_drafts: bool = Query(default=False),
) -> dict:
    actor, _ = identity
    return {
        "data": await list_versions(
            db,
            include_drafts=include_drafts,
            is_admin=actor.role == "admin",
        )
    }


@router.get("/versions/current")
async def current(db: DB, identity: Identity) -> dict:
    return {"data": await current_version(db)}


@router.get("/domains")
async def domains(db: DB, identity: Identity) -> dict:
    return {"data": await list_domains(db)}


@router.get("/capabilities")
async def capabilities(
    db: DB,
    identity: Identity,
    include_candidates: bool = Query(default=False),
) -> dict:
    actor, _ = identity
    return {
        "data": await list_capabilities(
            db,
            include_candidates=include_candidates,
            is_admin=actor.role == "admin",
        )
    }


@router.get("/job-roles")
async def job_roles(
    db: DB,
    identity: Identity,
    include_candidates: bool = Query(default=False),
) -> dict:
    actor, _ = identity
    return {
        "data": await list_job_roles(
            db,
            include_candidates=include_candidates,
            is_admin=actor.role == "admin",
        )
    }
