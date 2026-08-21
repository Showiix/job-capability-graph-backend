from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DiscoveryRunCreate(BaseModel):
    batch_ids: list[UUID] = Field(min_length=1, max_length=20)
    minimum_support_jobs: int = Field(default=3, ge=2, le=1000)
    minimum_source_count: int = Field(default=1, ge=1, le=10)
    minimum_quality_score: int = Field(default=60, ge=0, le=100)
    maximum_candidates: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def unique_batches(self):
        if len(self.batch_ids) != len(set(self.batch_ids)):
            raise ValueError("batch_ids must be unique")
        return self
