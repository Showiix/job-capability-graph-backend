from uuid import UUID

from pydantic import BaseModel, Field


class ImportCreatedResponse(BaseModel):
    resource_id: UUID
    run_id: UUID
    status: str
    poll_url: str


class ReprocessRequest(BaseModel):
    pipeline_version: str = Field(
        default="jd_normalization_v2",
        min_length=1,
        max_length=80,
    )
