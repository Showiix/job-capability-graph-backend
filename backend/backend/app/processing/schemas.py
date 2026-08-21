from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProcessingRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_type: str
    subject_type: str
    subject_id: UUID
    retry_of_run_id: UUID | None
    status: str
    current_stage: str | None
    pipeline_version: str
    celery_task_id: str | None
    total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    progress_percent: float
    cancel_requested: bool
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProcessingErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stage: str
    item_type: str | None
    item_id: UUID | None
    item_key: str | None
    error_code: str
    message: str
    retryable: bool
    details: dict
    occurred_at: datetime
