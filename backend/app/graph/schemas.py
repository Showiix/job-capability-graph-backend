from uuid import UUID

from pydantic import BaseModel


class GraphVersionCreate(BaseModel):
    proposal_id: UUID
