from uuid import UUID

from pydantic import BaseModel


class CatalogImportResponse(BaseModel):
    import_id: UUID
    status: str
    summary: dict
    version_id: UUID | None = None
