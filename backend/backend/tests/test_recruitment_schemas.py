import copy
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.recruitment.schemas import (
    RecruitmentJDParseResponse,
    RequirementsReplaceRequest,
)

VALID_JD_PARSE = {
    "job_title": "AI 应用开发工程师",
    "summary": "负责大模型应用开发",
    "responsibilities": [
        {
            "text": "负责 RAG 应用开发",
            "evidence_quote": "负责基于 RAG 的企业知识库应用开发",
        }
    ],
    "minimum_education_level": "bachelor",
    "recommended_experience_months": 24,
    "skills": [
        {
            "name": "Python",
            "requirement_type": "required",
            "importance": 1.0,
            "evidence_quote": "熟练掌握 Python",
            "confidence": 0.98,
        }
    ],
}


def test_jd_parse_response_accepts_exact_contract() -> None:
    parsed = RecruitmentJDParseResponse.model_validate(VALID_JD_PARSE)

    assert parsed.skills[0].requirement_type == "required"


@pytest.mark.parametrize("location", ["top", "responsibility", "skill"])
def test_jd_parse_response_rejects_extra_fields(location) -> None:
    invalid = copy.deepcopy(VALID_JD_PARSE)
    if location == "top":
        invalid["unexpected"] = True
    elif location == "responsibility":
        invalid["responsibilities"][0]["unexpected"] = True
    else:
        invalid["skills"][0]["unexpected"] = True

    with pytest.raises(ValidationError):
        RecruitmentJDParseResponse.model_validate(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("importance", 0),
        ("importance", 1.01),
        ("confidence", -0.01),
        ("confidence", 1.01),
    ],
)
def test_jd_parse_skill_scores_are_bounded(field, value) -> None:
    invalid = copy.deepcopy(VALID_JD_PARSE)
    invalid["skills"][0][field] = value

    with pytest.raises(ValidationError):
        RecruitmentJDParseResponse.model_validate(invalid)


def test_jd_parse_schema_is_strict_for_responses_api() -> None:
    schema = RecruitmentJDParseResponse.model_json_schema()

    def assert_strict_objects(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                assert_strict_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict_objects(value)

    assert_strict_objects(schema)
    assert "capability_id" not in json.dumps(schema, sort_keys=True)


def test_requirements_replace_rejects_duplicate_capabilities() -> None:
    capability_id = uuid4()
    payload = {
        "job_title": "AI 工程师",
        "summary": None,
        "responsibilities": [],
        "minimum_education_level": None,
        "recommended_experience_months": None,
        "requirements": [
            {
                "capability_id": capability_id,
                "requirement_type": "required",
                "importance": 1.0,
            },
            {
                "capability_id": capability_id,
                "requirement_type": "bonus",
                "importance": 0.5,
            },
        ],
        "unmapped_skills": [],
    }

    with pytest.raises(ValidationError):
        RequirementsReplaceRequest.model_validate(payload)


def test_requirements_replace_accepts_client_owned_fields_only() -> None:
    payload = {
        "job_title": "AI 工程师",
        "summary": None,
        "responsibilities": ["负责 RAG 应用开发"],
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
        "requirements": [
            {
                "capability_id": uuid4(),
                "requirement_type": "required",
                "importance": 1.0,
            }
        ],
        "unmapped_skills": [{"raw_name": "新框架", "requirement_type": "bonus"}],
    }

    parsed = RequirementsReplaceRequest.model_validate(payload)

    assert parsed.requirements[0].importance == 1.0

    invalid = copy.deepcopy(payload)
    invalid["requirements"][0]["canonical_name"] = "伪造名称"
    with pytest.raises(ValidationError):
        RequirementsReplaceRequest.model_validate(invalid)
