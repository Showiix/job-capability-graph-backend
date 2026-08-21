from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.api.dependencies import DB, Identity
from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.files.schemas import FileResponseSchema, preview_supported
from app.files.service import get_visible_file, log_access
from app.infrastructure.file_storage import FileStorage

router = APIRouter(prefix="/files", tags=["files"])
storage = FileStorage(get_settings().file_storage_root)


@router.get("/{file_id}")
async def metadata(file_id: UUID, db: DB, identity: Identity) -> dict:
    actor, _ = identity
    stored_file = await get_visible_file(db, file_id, actor)
    return {"data": _file_data(stored_file)}


@router.get("/{file_id}/content")
async def content(
    file_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
) -> FileResponse:
    actor, _ = identity
    stored_file = await get_visible_file(db, file_id, actor)
    path = _content_path(stored_file)
    await log_access(db, stored_file, actor, "preview", request.state.request_id)
    return FileResponse(path, media_type=stored_file.media_type)


@router.get("/{file_id}/download")
async def download(
    file_id: UUID,
    request: Request,
    db: DB,
    identity: Identity,
) -> FileResponse:
    actor, _ = identity
    stored_file = await get_visible_file(db, file_id, actor)
    path = _content_path(stored_file)
    await log_access(db, stored_file, actor, "download", request.state.request_id)
    return FileResponse(
        path,
        media_type=stored_file.media_type,
        filename=stored_file.original_name,
    )


def _file_data(stored_file: StoredFile) -> dict:
    return FileResponseSchema.model_validate(
        {
            "id": stored_file.id,
            "original_name": stored_file.original_name,
            "media_type": stored_file.media_type,
            "size_bytes": stored_file.size_bytes,
            "category": stored_file.category,
            "status": stored_file.status,
            "created_at": stored_file.created_at,
            "preview_supported": preview_supported(stored_file.media_type),
        }
    ).model_dump(mode="json")


def _content_path(stored_file: StoredFile) -> Path:
    try:
        path = storage.resolve(stored_file.storage_key)
    except ValueError:
        raise APIError(404, "FILE_CONTENT_MISSING", "文件内容不存在") from None
    if not path.is_file():
        raise APIError(404, "FILE_CONTENT_MISSING", "文件内容不存在")
    return path
