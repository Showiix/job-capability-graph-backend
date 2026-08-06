from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.dependencies import CSRF, DB, Admin
from app.imports.schemas import ReprocessRequest
from app.imports.service import (
    _batch_data,
    archive_batch,
    create_import,
    get_batch,
    list_batches,
    list_rows,
    list_warnings,
    reprocess_batch,
)
from app.processing.schemas import ProcessingRunResponse

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("")
async def list_imports(
    db: DB,
    actor: Admin,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {"data": await list_batches(db, page=page, page_size=page_size)}


@router.get("/{batch_id}/rows")
async def rows(
    batch_id: UUID,
    db: DB,
    actor: Admin,
    include: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
) -> dict:
    await get_batch(db, batch_id)
    values = {item.strip() for item in (include or "").split(",") if item.strip()}
    return {
        "data": await list_rows(
            db,
            batch_id,
            include_raw_payload="raw_payload" in values,
            include_full_text="full_text" in values,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/{batch_id}/warnings")
async def warnings(batch_id: UUID, db: DB, actor: Admin) -> dict:
    await get_batch(db, batch_id)
    return {"data": await list_warnings(db, batch_id)}


@router.get("/{batch_id}")
async def detail(batch_id: UUID, db: DB, actor: Admin) -> dict:
    batch, source = await get_batch(db, batch_id)
    return {"data": _batch_data(batch, source)}


@router.post("/{batch_id}/reprocess", status_code=202)
async def reprocess(
    batch_id: UUID,
    request: Request,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
    payload: ReprocessRequest | None = None,
) -> dict:
    batch, _ = await get_batch(db, batch_id)
    run = await reprocess_batch(
        db,
        actor,
        batch,
        payload or ReprocessRequest(),
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    data = ProcessingRunResponse.model_validate(run).model_dump(mode="json")
    data["run_id"] = data["id"]
    data["resource_id"] = str(batch.id)
    return {"data": data}


@router.post("/{batch_id}/archive")
async def archive(
    batch_id: UUID,
    request: Request,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
) -> JSONResponse:
    batch, source = await get_batch(db, batch_id)
    archived = await archive_batch(
        db,
        actor,
        batch,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _batch_data(archived, source)},
    )


@router.post("", status_code=202)
async def upload_import(
    request: Request,
    db: DB,
    actor: Admin,
    _csrf: CSRF,
    file: Annotated[UploadFile, File()],
    source_code: Annotated[str, Form(min_length=1, max_length=50)],
    collected_at: Annotated[datetime, Form()],
    source_format: Annotated[str, Form(max_length=30)] = "auto",
    schema_version: Annotated[str | None, Form(max_length=40)] = None,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> dict:
    value = await create_import(
        db,
        actor,
        file,
        source_code=source_code,
        collected_at=collected_at,
        source_format=source_format,
        schema_version=schema_version,
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": value.model_dump(mode="json")}
