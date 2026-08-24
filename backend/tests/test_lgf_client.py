from types import SimpleNamespace

import httpx
import pytest

from app.algorithm.lgf import LGFClient, LGFMatchRequest
from app.recruitment.service import _attach_lgf_signals


@pytest.mark.asyncio
async def test_lgf_client_parses_match_response() -> None:
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "job_id": "ai-engineer",
                "match_score": 0.84,
                "match_level": "match",
                "required": {"missing": ["CUDA"]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LGFClient(
            url="http://lgf/match",
            api_key="test-only-key",
            http=http,
        ).match(
            LGFMatchRequest(
                job_id="ai-engineer",
                resume={"skills": [{"skill": "Python", "mastery": "proficient"}]},
            )
        )

    assert result.status == "ok"
    assert result.payload is not None
    assert result.payload.match_score == 0.84
    assert captured["authorization"] == "Bearer test-only-key"


@pytest.mark.asyncio
async def test_lgf_client_degrades_on_invalid_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"match_score": "not-a-score"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await LGFClient(url="http://lgf/match", http=http).match(
            LGFMatchRequest(job_id="ai-engineer", resume=[])
        )

    assert result.status == "degraded"
    assert result.error_code == "LGF_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_recruitment_match_keeps_explicit_disabled_lgf_signal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.recruitment.service.get_settings",
        lambda: SimpleNamespace(lgf_enabled=False),
    )
    scored = SimpleNamespace(dimension_scores={})
    ranked = [SimpleNamespace(scored=scored)]

    await _attach_lgf_signals(
        ranked,
        project_title="AI 工程师",
        snapshot={},
        profiles_by_candidate={},
        skills_by_profile={},
    )

    assert scored.dimension_scores["lgf"] == {
        "status": "disabled",
        "score": None,
        "match_level": None,
        "error_code": None,
    }
