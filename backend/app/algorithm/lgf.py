from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class LGFMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=200)
    resume: list[str | dict[str, Any]] | dict[str, Any]


class LGFMatchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str | None = None
    match_score: float = Field(ge=0, le=1)
    match_level: str | None = None
    required: dict[str, Any] | None = None
    bonus: dict[str, Any] | None = None
    gap_analysis: list[dict[str, Any]] = Field(default_factory=list)
    learning_path: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LGFMatchResult:
    status: str
    payload: LGFMatchResponse | None = None
    error_code: str | None = None


class LGFClient:
    """Thin client for the teammate's optional ``POST /match`` service."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        http: httpx.AsyncClient,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.http = http

    async def match(self, payload: LGFMatchRequest) -> LGFMatchResult:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = await self.http.post(
                self.url,
                headers=headers,
                json=payload.model_dump(mode="json"),
            )
        except httpx.TimeoutException:
            return LGFMatchResult(status="degraded", error_code="LGF_TIMEOUT")
        except httpx.RequestError:
            return LGFMatchResult(status="degraded", error_code="LGF_UPSTREAM_ERROR")
        if response.status_code >= 400:
            return LGFMatchResult(
                status="degraded",
                error_code=(
                    "LGF_RATE_LIMITED"
                    if response.status_code == 429
                    else "LGF_REQUEST_REJECTED"
                ),
            )
        try:
            parsed = LGFMatchResponse.model_validate(response.json())
        except (ValueError, TypeError):
            return LGFMatchResult(status="degraded", error_code="LGF_RESPONSE_INVALID")
        return LGFMatchResult(status="ok", payload=parsed)
