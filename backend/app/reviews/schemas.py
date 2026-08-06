from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.reviews import REVIEW_DISCLAIMER

RoleName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
Responsibility = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
IndustryScenario = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]


class RoleDefinitionPayload(BaseModel):
    role_name: RoleName
    core_responsibilities: list[Responsibility] = Field(
        default_factory=list,
        max_length=20,
    )
    required_capability_ids: list[UUID] = Field(min_length=2, max_length=20)
    bonus_capability_ids: list[UUID] = Field(default_factory=list, max_length=20)
    industry_scenarios: list[IndustryScenario] = Field(
        default_factory=list,
        max_length=20,
    )
    generation_source: Literal[
        "deterministic_baseline",
        "human_revision",
        "llm_candidate",
    ] = "human_revision"
    definition_status: Literal["needs_enrichment", "reviewed"] = "reviewed"
    disclaimer: str = REVIEW_DISCLAIMER

    @field_validator("required_capability_ids", "bonus_capability_ids")
    @classmethod
    def unique_capabilities(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("capability ids must be unique")
        return value


class ReviewProposalCreate(BaseModel):
    candidate_id: UUID


class ReviewDecisionCreate(BaseModel):
    decision: Literal["approve", "revise", "reject"]
    after_payload: RoleDefinitionPayload | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

