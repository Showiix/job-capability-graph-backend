from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.algorithm.lgf import (
    LGFClient,
    LGFMatchRequest,
    LGFMatchResponse,
    LGFMatchResult,
)
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
                job={
                    "job_name": "AI Engineer",
                    "required_skills": [{"skill": "Python", "weight": 1.0}],
                    "bonus_skills": [],
                },
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
            LGFMatchRequest(
                job_id="ai-engineer",
                job={"required_skills": [], "bonus_skills": []},
                resume=[],
            )
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


@pytest.mark.asyncio
async def test_recruitment_match_sends_dynamic_job_and_canonical_skills(
    monkeypatch,
) -> None:
    capability_id = uuid4()
    candidate_id = uuid4()
    profile_id = uuid4()
    captured = {}

    async def match(_self, payload):
        captured["payload"] = payload
        return LGFMatchResult(
            status="ok",
            payload=LGFMatchResponse(match_score=1.0, match_level="match"),
        )

    monkeypatch.setattr(
        "app.recruitment.service.get_settings",
        lambda: SimpleNamespace(
            lgf_enabled=True,
            lgf_match_url="http://algorithm:8001/match",
            lgf_api_key=None,
            lgf_timeout_seconds=1,
        ),
    )
    monkeypatch.setattr(LGFClient, "match", match)
    scored = SimpleNamespace(dimension_scores={})
    ranked = [
        SimpleNamespace(candidate=SimpleNamespace(id=candidate_id), scored=scored)
    ]
    profile = SimpleNamespace(id=profile_id, total_experience_months=24)
    skill = SimpleNamespace(
        capability_id=capability_id,
        raw_name="py",
        proficiency="familiar",
    )

    await _attach_lgf_signals(
        ranked,
        project_title="AI 招聘",
        snapshot={
            "job_title": "AI 工程师",
            "requirements": [
                {
                    "capability_id": str(capability_id),
                    "canonical_name": "Python",
                    "importance": 1.0,
                    "requirement_type": "required",
                }
            ],
        },
        profiles_by_candidate={candidate_id: profile},
        skills_by_profile={profile_id: [skill]},
    )

    assert captured["payload"].job["required_skills"] == [
        {"skill": "Python", "weight": 1.0}
    ]
    assert captured["payload"].resume["skills"] == [
        {"skill": "Python", "mastery": "familiar"}
    ]
    assert scored.dimension_scores["lgf"]["score"] == 1.0
