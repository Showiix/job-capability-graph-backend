import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StructuredResponseResult[T: BaseModel]:
    payload: T
    response_id: str | None
    returned_model: str | None
    status: str
    usage: dict[str, int | None]
    provider_attempts: int
    response_sha256: str


class ResponsesAPIError(Exception):
    def __init__(
        self,
        code: str,
        stage: str,
        retryable: bool,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.http_status = http_status
        super().__init__(code)


class StructuredResponsesClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.http = http
        self.sleep = sleep

    async def generate[T: BaseModel](
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        instructions: str,
        input_text: str,
        schema_name: str,
        response_model: type[T],
        metadata: dict[str, str],
        max_output_tokens: int = 5000,
        request_id: str | None = None,
    ) -> StructuredResponseResult[T]:
        body = {
            "model": model,
            "instructions": instructions,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_text}],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                }
            },
            "max_output_tokens": max_output_tokens,
            "stream": False,
            "store": False,
            "metadata": metadata,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if request_id is not None:
            headers["X-Request-ID"] = request_id

        for attempt in (1, 2):
            response = None
            try:
                response = await self.http.post(url, headers=headers, json=body)
                if response.status_code >= 400:
                    raise _classify_http_error(response.status_code)
                return _parse_response(
                    response,
                    response_model=response_model,
                    provider_attempts=attempt,
                )
            except httpx.TimeoutException:
                error = ResponsesAPIError("LLM_TIMEOUT", "request", True)
            except httpx.RequestError:
                error = ResponsesAPIError("LLM_UPSTREAM_ERROR", "request", True)
            except ResponsesAPIError as caught:
                error = caught

            logger.warning(
                "responses attempt failed: operation=%s attempt=%s code=%s status=%s",
                metadata.get("operation"),
                attempt,
                error.code,
                error.http_status,
            )
            if not error.retryable or attempt == 2:
                raise error
            await self.sleep(_retry_delay(error, response))

        raise AssertionError("unreachable")


def create_responses_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)
    )


def _retry_delay(
    error: ResponsesAPIError,
    response: httpx.Response | None,
) -> float:
    if error.code == "LLM_RATE_LIMITED" and response is not None:
        try:
            return min(
                max(float(response.headers.get("Retry-After", "1")), 0.0),
                5.0,
            )
        except ValueError:
            return 1.0
    return 1.0


def _classify_http_error(status: int) -> ResponsesAPIError:
    if status == 429:
        return ResponsesAPIError("LLM_RATE_LIMITED", "request", True, status)
    if status >= 500:
        return ResponsesAPIError("LLM_UPSTREAM_ERROR", "request", True, status)
    return ResponsesAPIError("LLM_REQUEST_REJECTED", "request", False, status)


def _parse_response[T: BaseModel](
    response: httpx.Response,
    *,
    response_model: type[T],
    provider_attempts: int,
) -> StructuredResponseResult[T]:
    try:
        envelope = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ResponsesAPIError(
            "LLM_RESPONSE_INVALID", "validate_response", True
        ) from error
    if not isinstance(envelope, dict):
        raise ResponsesAPIError("LLM_RESPONSE_INVALID", "validate_response", True)

    status = envelope.get("status")
    if (
        status != "completed"
        or envelope.get("error") is not None
        or envelope.get("incomplete_details") is not None
    ):
        raise ResponsesAPIError("LLM_RESPONSE_INCOMPLETE", "validate_response", True)

    output_text = _read_output_text(envelope)
    try:
        payload = response_model.model_validate_json(output_text)
    except (ValidationError, ValueError) as error:
        raise ResponsesAPIError(
            "LLM_RESPONSE_INVALID", "validate_response", True
        ) from error

    return StructuredResponseResult(
        payload=payload,
        response_id=_optional_string(envelope.get("id")),
        returned_model=_optional_string(envelope.get("model")),
        status="completed",
        usage=_usage(envelope.get("usage")),
        provider_attempts=provider_attempts,
        response_sha256=hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
    )


def _read_output_text(envelope: dict[str, Any]) -> str:
    parts: list[str] = []
    refused = False
    completed_messages = 0
    outputs = envelope.get("output")
    if not isinstance(outputs, list):
        outputs = []

    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        contents = output.get("content")
        if not isinstance(contents, list):
            contents = []
        for content in contents:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                refused = True
            elif (
                output.get("status") == "completed"
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                parts.append(content["text"])
        if output.get("status") == "completed":
            completed_messages += 1

    if refused:
        raise ResponsesAPIError("LLM_RESPONSE_REFUSED", "validate_response", False)
    if completed_messages == 0 or not parts:
        raise ResponsesAPIError("LLM_RESPONSE_INVALID", "validate_response", True)
    return "".join(parts)


def _usage(value: Any) -> dict[str, int | None]:
    source = value if isinstance(value, dict) else {}
    usage = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        item = source.get(name)
        usage[name] = (
            item if isinstance(item, int) and not isinstance(item, bool) else None
        )
    return usage


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
