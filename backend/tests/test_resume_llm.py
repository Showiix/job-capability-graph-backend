import asyncio
import copy
import json
from uuid import uuid4

import httpx
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


def completed_response(text: str, *, output_prefix=None) -> dict:
    return {
        "id": "resp_test",
        "model": "returned-model",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            *(output_prefix or []),
            {
                "type": "message",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }


async def test_posts_exact_responses_structured_output_contract() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=completed_response(json.dumps(VALID_PARSE)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient

        result = await ResponsesClient(http=http).parse_resume(
            url="https://provider.test/v1/responses",
            api_key="secret-test-key",
            model="test-model",
            redacted_text="Python 项目",
            processing_run_id=uuid4(),
        )

    request = captured["request"]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == "https://provider.test/v1/responses"
    assert request.headers["authorization"] == "Bearer secret-test-key"
    assert body["input"][0]["content"][0] == {
        "type": "input_text",
        "text": "Python 项目",
    }
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "resume_parse_v1"
    assert body["text"]["format"]["strict"] is True
    assert body["store"] is False
    assert body["stream"] is False
    assert body["max_output_tokens"] == 5000
    assert "tools" not in body
    assert "previous_response_id" not in body
    assert "messages" not in body
    assert result.payload.schema_version == "resume_parse_v1"


async def test_collects_multiple_output_text_parts_outside_first_output() -> None:
    serialized = json.dumps(VALID_PARSE)
    split = len(serialized) // 2
    envelope = completed_response(
        serialized[split:],
        output_prefix=[
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {"type": "annotation", "text": "ignored"},
                    {"type": "output_text", "text": serialized[:split]},
                ],
            },
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient

        result = await ResponsesClient(http=http).parse_resume(
            url="https://provider.test/v1/responses",
            api_key="secret-test-key",
            model="test-model",
            redacted_text="Python 项目",
            processing_run_id=uuid4(),
        )

    assert result.payload.skills[0].name == "Python"


async def test_refusal_wins_over_output_text(caplog) -> None:
    envelope = completed_response(json.dumps(VALID_PARSE))
    envelope["output"][0]["content"].insert(
        0,
        {"type": "refusal", "refusal": "cannot process"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient, ResumeLLMError

        with pytest.raises(ResumeLLMError) as error:
            await ResponsesClient(http=http).parse_resume(
                url="https://provider.test/v1/responses",
                api_key="secret-test-key",
                model="test-model",
                redacted_text="Python 项目",
                processing_run_id=uuid4(),
            )

    assert error.value.code == "LLM_RESPONSE_REFUSED"
    assert error.value.stage == "validate_response"
    assert "secret-test-key" not in caplog.text
    assert "cannot process" not in caplog.text
    assert "Python 项目" not in caplog.text


@pytest.mark.parametrize(
    ("variant", "expected_code"),
    [
        ("incomplete", "LLM_RESPONSE_INCOMPLETE"),
        ("missing_output_text", "LLM_RESPONSE_INVALID"),
        ("non_json", "LLM_RESPONSE_INVALID"),
        ("schema_invalid", "LLM_RESPONSE_INVALID"),
    ],
)
async def test_invalid_response_variants_are_retried_once(
    variant,
    expected_code,
    caplog,
) -> None:
    calls = 0

    if variant == "incomplete":
        envelope = completed_response(json.dumps(VALID_PARSE))
        envelope["status"] = "incomplete"
    elif variant == "missing_output_text":
        envelope = completed_response(json.dumps(VALID_PARSE))
        envelope["output"][0]["content"] = [{"type": "annotation", "text": "no"}]
    elif variant == "non_json":
        envelope = completed_response("not-json")
    else:
        invalid = copy.deepcopy(VALID_PARSE)
        del invalid["skills"]
        envelope = completed_response(json.dumps(invalid))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=envelope)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient, ResumeLLMError

        with pytest.raises(ResumeLLMError) as error:
            await ResponsesClient(
                http=http,
                sleep=lambda _seconds: asyncio.sleep(0),
            ).parse_resume(
                url="https://provider.test/v1/responses",
                api_key="secret-test-key",
                model="test-model",
                redacted_text="Python 项目",
                processing_run_id=uuid4(),
            )

    assert error.value.code == expected_code
    assert error.value.stage == "validate_response"
    assert calls == 2
    assert "secret-test-key" not in caplog.text
    assert "Python 项目" not in caplog.text


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_calls"),
    [
        (401, "LLM_REQUEST_REJECTED", 1),
        (403, "LLM_REQUEST_REJECTED", 1),
        (429, "LLM_RATE_LIMITED", 2),
        (500, "LLM_UPSTREAM_ERROR", 2),
        (503, "LLM_UPSTREAM_ERROR", 2),
    ],
)
async def test_http_error_classification_and_bounded_retry(
    status,
    expected_code,
    expected_calls,
    caplog,
) -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="provider-secret-body")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient, ResumeLLMError

        with pytest.raises(ResumeLLMError) as error:
            await ResponsesClient(http=http, sleep=fake_sleep).parse_resume(
                url="https://provider.test/v1/responses",
                api_key="secret-test-key",
                model="test-model",
                redacted_text="Python 项目",
                processing_run_id=uuid4(),
            )

    assert error.value.code == expected_code
    assert calls == expected_calls
    assert "secret-test-key" not in caplog.text
    assert "provider-secret-body" not in caplog.text
    assert "Python 项目" not in caplog.text
    assert "Authorization" not in caplog.text
    assert "Bearer" not in caplog.text
    if status == 429:
        assert sleeps == [1.0]


async def test_rate_limit_retry_after_is_capped() -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "20"},
            text="provider-secret-body",
        )

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient, ResumeLLMError

        with pytest.raises(ResumeLLMError):
            await ResponsesClient(http=http, sleep=fake_sleep).parse_resume(
                url="https://provider.test/v1/responses",
                api_key="secret-test-key",
                model="test-model",
                redacted_text="Python 项目",
                processing_run_id=uuid4(),
            )

    assert calls == 2
    assert sleeps == [5.0]


async def test_timeout_retries_once_then_succeeds() -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json=completed_response(json.dumps(VALID_PARSE)))

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient

        result = await ResponsesClient(http=http, sleep=fake_sleep).parse_resume(
            url="https://provider.test/v1/responses",
            api_key="secret-test-key",
            model="test-model",
            redacted_text="Python 项目",
            processing_run_id=uuid4(),
        )

    assert result.provider_attempts == 2
    assert calls == 2
    assert sleeps == [1.0]


async def test_timeout_exhaustion_has_stable_code_without_leaks(caplog) -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider-secret-body", request=request)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        from app.resumes.llm import ResponsesClient, ResumeLLMError

        with pytest.raises(ResumeLLMError) as error:
            await ResponsesClient(http=http, sleep=fake_sleep).parse_resume(
                url="https://provider.test/v1/responses",
                api_key="secret-test-key",
                model="test-model",
                redacted_text="Python 项目",
                processing_run_id=uuid4(),
            )

    assert error.value.code == "LLM_TIMEOUT"
    assert error.value.stage == "request"
    assert error.value.retryable is True
    assert calls == 2
    assert sleeps == [1.0]
    assert "secret-test-key" not in caplog.text
    assert "provider-secret-body" not in caplog.text
    assert "Python 项目" not in caplog.text
    assert "Authorization" not in caplog.text
    assert "Bearer" not in caplog.text
