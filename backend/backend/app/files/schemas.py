from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_name: str
    media_type: str
    size_bytes: int
    category: str
    status: str
    created_at: datetime
    preview_supported: bool


def preview_supported(media_type: str) -> bool:
    return (
        media_type == "application/pdf"
        or media_type.startswith("text/")
        or media_type.startswith("image/")
        or media_type.startswith("video/")
    )
