import copy
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.growth.schemas import (
    GrowthPathScopeError,
    GrowthPlanLLM,
    validate_capability_scope,
)

CAPABILITY_A = UUID("00000000-0000-0000-0000-000000000001")
CAPABILITY_B = UUID("00000000-0000-0000-0000-000000000002")
CAPABILITY_C = UUID("00000000-0000-0000-0000-000000000003")

VALID_PLAN = {
    "schema_version": "growth_path_v1",
    "summary": "先掌握基础能力，再完成综合实践。",
    "stages": [
        {
            "stage_no": 1,
            "title": "基础阶段",
            "objective": "掌握两个缺失的必备技能。",
            "capability_ids": [str(CAPABILITY_A), str(CAPABILITY_B)],
            "estimated_weeks": 2,
            "actions": ["完成基础练习"],
            "completion_criteria": ["能够独立完成练习"],
        }
    ],
    "final_project": "完成一个覆盖全部缺失能力的综合项目。",
}


def plan_with_ids(capability_ids: list[UUID]) -> GrowthPlanLLM:
    values = copy.deepcopy(VALID_PLAN)
    values["stages"][0]["capability_ids"] = [str(item) for item in capability_ids]
    return GrowthPlanLLM.model_validate(values)


def test_growth_plan_accepts_exact_contract() -> None:
    plan = GrowthPlanLLM.model_validate(VALID_PLAN)

    assert plan.schema_version == "growth_path_v1"
    assert plan.stages[0].capability_ids == [CAPABILITY_A, CAPABILITY_B]


def test_growth_plan_rejects_extra_fields_and_invalid_limits() -> None:
    with pytest.raises(ValidationError):
        GrowthPlanLLM.model_validate({**VALID_PLAN, "unexpected": True})

    invalid = copy.deepcopy(VALID_PLAN)
    invalid["stages"][0]["estimated_weeks"] = 0
    with pytest.raises(ValidationError):
        GrowthPlanLLM.model_validate(invalid)


def test_validate_capability_scope_rejects_missing_duplicate_and_unknown() -> None:
    expected = {CAPABILITY_A, CAPABILITY_B}

    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan_with_ids([CAPABILITY_A]), expected)
    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan_with_ids([CAPABILITY_A, CAPABILITY_A]), expected)
    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(
            plan_with_ids([CAPABILITY_A, CAPABILITY_B, CAPABILITY_C]),
            expected,
        )


def test_validate_capability_scope_requires_contiguous_stage_numbers() -> None:
    values = copy.deepcopy(VALID_PLAN)
    values["stages"][0]["stage_no"] = 2
    plan = GrowthPlanLLM.model_validate(values)

    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan, {CAPABILITY_A, CAPABILITY_B})
