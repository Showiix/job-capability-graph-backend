from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.matching.schemas import DomainSnapshotRead, JobRoleSnapshotRead

ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GrowthStageLLM(StrictSchema):
    stage_no: Annotated[int, Field(ge=1, le=8)]
    title: Annotated[str, Field(min_length=1, max_length=100)]
    objective: Annotated[str, Field(min_length=1, max_length=500)]
    capability_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    estimated_weeks: Annotated[int, Field(ge=1, le=12)]
    actions: Annotated[list[ShortText], Field(min_length=1, max_length=5)]
    completion_criteria: Annotated[
        list[ShortText], Field(min_length=1, max_length=5)
    ]


class GrowthPlanLLM(StrictSchema):
    schema_version: Literal["growth_path_v1"]
    summary: Annotated[str, Field(min_length=1, max_length=1000)]
    stages: Annotated[list[GrowthStageLLM], Field(min_length=1, max_length=8)]
    final_project: Annotated[str, Field(min_length=1, max_length=1000)]


class GrowthCapabilityRead(StrictSchema):
    id: UUID
    canonical_name: str
    skill_type: str
    domain: DomainSnapshotRead


class GrowthStageRead(StrictSchema):
    stage_no: int
    title: str
    objective: str
    capabilities: list[GrowthCapabilityRead]
    estimated_weeks: int
    actions: list[str]
    completion_criteria: list[str]


class GrowthPlanRead(StrictSchema):
    schema_version: Literal["growth_path_v1"]
    target_role: JobRoleSnapshotRead
    summary: str
    total_estimated_weeks: int
    stages: list[GrowthStageRead]
    final_project: str


class GrowthSourceRead(StrictSchema):
    match_run: dict[str, Any]
    match_result: dict[str, Any]


class GrowthPathRead(StrictSchema):
    id: UUID
    match_run_id: UUID
    job_role_id: UUID
    prompt_version: Literal["growth_path_v1"]
    source: GrowthSourceRead
    plan: GrowthPlanRead
    created_at: datetime


class GrowthPathCreateResponse(StrictSchema):
    reused: bool
    growth_path: GrowthPathRead


class GrowthPathScopeError(ValueError):
    pass


def validate_capability_scope(
    plan: GrowthPlanLLM,
    expected_capability_ids: set[UUID],
) -> None:
    stage_numbers = [stage.stage_no for stage in plan.stages]
    if stage_numbers != list(range(1, len(plan.stages) + 1)):
        raise GrowthPathScopeError("stage numbers must be contiguous")

    capability_ids = [
        capability_id
        for stage in plan.stages
        for capability_id in stage.capability_ids
    ]
    if len(capability_ids) != len(set(capability_ids)):
        raise GrowthPathScopeError("capabilities must not be duplicated")
    if set(capability_ids) != expected_capability_ids:
        raise GrowthPathScopeError("capabilities must match the required gaps")
