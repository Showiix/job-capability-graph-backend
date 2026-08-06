import copy
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.resumes.schemas import (
    ManualProfileReplaceRequest,
    ResumeCreatedResponse,
    ResumeParseResponse,
)

VALID_PARSE = {
    "schema_version": "resume_parse_v1",
    "document_language": "zh-CN",
    "summary": "具有 Python 项目经验",
    "educations": [
        {
            "school_name": "示例大学",
            "major": "计算机科学",
            "education_level": "bachelor",
            "start_month": "2021-09",
            "end_month": "2025-06",
            "is_current": False,
            "evidence_quote": "2021-09 至 2025-06 示例大学 计算机科学 本科",
            "confidence": 0.98,
        }
    ],
    "experiences": [],
    "projects": [],
    "skills": [
        {
            "name": "Python",
            "proficiency": "intermediate",
            "explicit_experience_months": 24,
            "evidence_strength": "project",
            "evidence_quote": "使用 Python 开发数据处理项目",
            "confidence": 0.95,
        }
    ],
}

VALID_MANUAL = {
    "document_language": "zh-CN",
    "summary": None,
    "educations": [
        {
            "school_name": "示例大学",
            "major": None,
            "education_level": "bachelor",
            "start_month": None,
            "end_month": None,
            "is_current": False,
            "evidence_quote": None,
        }
    ],
    "experiences": [],
    "projects": [],
    "skills": [
        {
            "raw_name": "新技能",
            "capability_id": None,
            "proficiency": None,
            "explicit_experience_months": None,
            "evidence_strength": "mention",
            "evidence_quote": None,
        }
    ],
}


def test_parse_response_accepts_exact_contract() -> None:
    parsed = ResumeParseResponse.model_validate(VALID_PARSE)

    assert parsed.schema_version == "resume_parse_v1"


def test_parse_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(
            {**VALID_PARSE, "capability_id": "forbidden"}
        )


@pytest.mark.parametrize("value", ["2026", "2026-13", "2026-1", ""])
def test_parse_response_rejects_invalid_month(value) -> None:
    invalid = copy.deepcopy(VALID_PARSE)
    invalid["educations"][0]["start_month"] = value

    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(invalid)


def test_current_item_requires_null_end_month() -> None:
    invalid = copy.deepcopy(VALID_PARSE)
    invalid["educations"][0]["is_current"] = True

    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(invalid)


def test_end_month_cannot_precede_start_month() -> None:
    invalid = copy.deepcopy(VALID_PARSE)
    invalid["educations"][0]["end_month"] = "2020-01"

    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(invalid)


def test_array_and_string_limits_are_enforced() -> None:
    too_many = copy.deepcopy(VALID_PARSE)
    too_many["skills"] = [
        copy.deepcopy(VALID_PARSE["skills"][0]) for _ in range(101)
    ]
    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(too_many)

    too_long = copy.deepcopy(VALID_PARSE)
    too_long["summary"] = "x" * 1001
    with pytest.raises(ValidationError):
        ResumeParseResponse.model_validate(too_long)


def test_created_response_matches_async_contract() -> None:
    response = ResumeCreatedResponse(
        resource_id=uuid4(),
        run_id=uuid4(),
        status="processing",
        poll_url="/api/v1/processing-runs/example",
    )

    assert response.status == "processing"


def test_json_schema_has_no_business_ids() -> None:
    serialized = json.dumps(ResumeParseResponse.model_json_schema(), sort_keys=True)

    assert "capability_id" not in serialized
    assert "total_experience_months" not in serialized
    assert "highest_education_level" not in serialized


def test_manual_request_allows_null_evidence_and_capability() -> None:
    parsed = ManualProfileReplaceRequest.model_validate(VALID_MANUAL)

    assert parsed.educations[0].evidence_quote is None
    assert parsed.skills[0].capability_id is None


@pytest.mark.parametrize("location", ["top", "education", "skill"])
def test_manual_request_rejects_extra_fields_at_every_level(location) -> None:
    invalid = copy.deepcopy(VALID_MANUAL)
    if location == "top":
        invalid["unexpected"] = True
    elif location == "education":
        invalid["educations"][0]["unexpected"] = True
    else:
        invalid["skills"][0]["unexpected"] = True

    with pytest.raises(ValidationError):
        ManualProfileReplaceRequest.model_validate(invalid)


def test_generated_schema_uses_strict_objects() -> None:
    schema = ResumeParseResponse.model_json_schema()

    def assert_strict_objects(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(
                    node.get("properties", {})
                )
            for value in node.values():
                assert_strict_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict_objects(value)

    assert_strict_objects(schema)
