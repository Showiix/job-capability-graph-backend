import json
from uuid import uuid4

import httpx

from app.recruitment.llm import RecruitmentJDResponsesClient
from tests.test_recruitment_schemas import VALID_JD_PARSE


def completed_response(text: str) -> dict:
    return {
        "id": "resp_recruitment",
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


async def test_posts_recruitment_jd_responses_contract() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=completed_response(json.dumps(VALID_JD_PARSE, ensure_ascii=False)),
        )

    run_id = uuid4()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await RecruitmentJDResponsesClient(http=http).parse_jd(
            url="https://provider.test/v1/responses",
            api_key="secret-test-key",
            model="test-model",
            source_text="熟练掌握 Python",
            processing_run_id=run_id,
        )

    request = captured["request"]
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer secret-test-key"
    assert request.headers["x-request-id"] == str(run_id)
    assert body["input"][0]["content"][0]["text"] == "熟练掌握 Python"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "recruitment_jd_parse_v1"
    assert body["text"]["format"]["strict"] is True
    assert body["metadata"] == {
        "operation": "parse_recruitment_jd",
        "processing_run_id": str(run_id),
    }
    assert body["store"] is False
    assert body["stream"] is False
    assert result.payload.skills[0].name == "Python"
    assert result.response_id == "resp_recruitment"
