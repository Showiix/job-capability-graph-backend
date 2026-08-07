import json
from uuid import uuid4

import httpx

from app.growth.llm import INSTRUCTIONS, generate_growth_path


def completed_response(text: str) -> dict:
    return {
        "id": "resp_growth",
        "model": "returned-model",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "type": "message",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }


async def test_growth_prompt_uses_only_structured_match_context() -> None:
    growth_path_id = uuid4()
    match_run_id = uuid4()
    job_role_id = uuid4()
    capability_id = uuid4()
    context = {
        "job_role": {"id": str(job_role_id), "canonical_name": "AI 工程师"},
        "missing_required_capabilities": [
            {"id": str(capability_id), "canonical_name": "Kubernetes"}
        ],
    }
    plan = {
        "schema_version": "growth_path_v1",
        "summary": "先学习缺失能力。",
        "stages": [
            {
                "stage_no": 1,
                "title": "基础阶段",
                "objective": "掌握 Kubernetes。",
                "capability_ids": [str(capability_id)],
                "estimated_weeks": 2,
                "actions": ["完成部署练习"],
                "completion_criteria": ["能够独立完成部署"],
            }
        ],
        "final_project": "完成一个容器化部署项目。",
    }
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=completed_response(json.dumps(plan)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await generate_growth_path(
            http=http,
            url="https://provider.test/v1/responses",
            api_key="secret",
            model="test-model",
            growth_path_id=growth_path_id,
            match_run_id=match_run_id,
            job_role_id=job_role_id,
            context=context,
            request_id="request-growth",
        )

    request = captured["request"]
    body = json.loads(request.content)
    input_text = body["input"][0]["content"][0]["text"]
    assert json.loads(input_text) == context
    assert "evidence_quote" not in input_text
    assert "extracted_text" not in input_text
    assert body["text"]["format"]["name"] == "growth_path_v1"
    assert body["max_output_tokens"] == 4000
    assert body["metadata"] == {
        "operation": "generate_growth_path",
        "growth_path_id": str(growth_path_id),
        "match_run_id": str(match_run_id),
        "job_role_id": str(job_role_id),
    }
    assert request.headers["X-Request-ID"] == "request-growth"
    assert result.payload.schema_version == "growth_path_v1"


def test_growth_instructions_anchor_capability_scope() -> None:
    assert "不可信" in INSTRUCTIONS
    assert "missing_required_capabilities" in INSTRUCTIONS
    assert "必须且只能" in INSTRUCTIONS
    assert "简体中文" in INSTRUCTIONS
