from uuid import UUID

from pydantic import BaseModel


class ImportCreatedResponse(BaseModel):
    resource_id: UUID
    run_id: UUID
    status: str
    poll_url: str
