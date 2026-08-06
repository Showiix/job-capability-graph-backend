from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Request, UploadFile

from app.api.dependencies import CSRF, DB, Admin
from app.imports.service import create_import

router = APIRouter(prefix="/imports", tags=["imports"])


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
