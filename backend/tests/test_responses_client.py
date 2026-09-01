import json

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.llm.responses import StructuredResponsesClient


class DemoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)


def completed_response(text: str) -> dict:
    return {
        "id": "resp_test",
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
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    }


async def test_structured_client_posts_strict_responses_schema() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=completed_response(json.dumps({"value": "ok"})),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await StructuredResponsesClient(http=http).generate(
            url="https://provider.test/v1/responses",
            api_key="secret",
            model="test-model",
            instructions="return the schema",
            input_text="context",
            schema_name="demo_v1",
            response_model=DemoPayload,
            metadata={"operation": "demo"},
        )

    body = json.loads(captured["request"].content)
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "demo_v1",
        "strict": True,
        "schema": DemoPayload.model_json_schema(),
    }
    assert body["store"] is False
    assert body["stream"] is False
    assert "tools" not in body
    assert result.payload.value == "ok"


async def test_structured_client_sends_image_to_responses_api() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json=completed_response(json.dumps({"value": "text"}))
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await StructuredResponsesClient(http=http).generate(
            url="https://provider.test/v1/responses",
            api_key="secret",
            model="vision-model",
            instructions="transcribe",
            input_text="read image",
            input_image=b"jpeg-bytes",
            input_image_media_type="image/jpeg",
            schema_name="image_v1",
            response_model=DemoPayload,
            metadata={"operation": "image"},
        )

    content = captured["body"]["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
