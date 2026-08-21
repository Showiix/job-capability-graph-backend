from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.recruitment.matching import (
    RecruitmentCandidateMatchInput,
    canonical_candidate_selection,
    profile_input,
    rank_candidate_matches,
    requirement_inputs,
    sha256_json,
)


def _requirement(capability_id: UUID, name: str, requirement_type: str) -> dict:
    return {
        "capability_id": str(capability_id),
        "canonical_name": name,
        "skill_type": "technical",
        "requirement_type": requirement_type,
        "importance": 1.0,
        "domain": {
            "id": str(UUID("10000000-0000-4000-8000-000000000001")),
            "code": "ai",
            "name": "人工智能",
        },
    }


def _candidate_input(
    candidate_id: UUID,
    display_name: str,
    skills: list,
) -> RecruitmentCandidateMatchInput:
    profile = SimpleNamespace(
        id=uuid4(),
        extraction_version="resume_parse_v1",
        highest_education_level="bachelor",
        total_experience_months=24,
        structured_payload={"validation_warnings": []},
    )
    candidate = SimpleNamespace(
        id=candidate_id,
        display_name=display_name,
        file_id=uuid4(),
    )
    return RecruitmentCandidateMatchInput(
        candidate=candidate,
        profile_record=profile,
        profile=profile_input(profile, skills),
    )


def test_requirement_and_profile_inputs_reuse_shared_scoring_contract() -> None:
    python_id = uuid4()
    docker_id = uuid4()
    snapshot = {
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
        "requirements": [
            _requirement(python_id, "Python", "required"),
            _requirement(docker_id, "Docker", "bonus"),
        ],
    }
    profile = SimpleNamespace(
        highest_education_level="master",
        total_experience_months=36,
    )
    skill = SimpleNamespace(
        id=uuid4(),
        capability_id=python_id,
        raw_name="Python",
        mapping_method="canonical_exact",
        evidence_strength="work",
        evidence_quote="负责 Python 后端开发",
    )

    requirements = requirement_inputs(snapshot)
    converted = profile_input(profile, [skill])

    assert [item.requirement_type for item in requirements] == ["required", "bonus"]
    assert converted.highest_education_level == "master"
    assert converted.skills[python_id].evidence_strength == "work"


def test_candidate_selection_hash_is_stable_and_includes_failed_candidates() -> None:
    ready = SimpleNamespace(id=uuid4(), parse_status="ready")
    failed = SimpleNamespace(id=uuid4(), parse_status="failed")
    profile = SimpleNamespace(id=uuid4(), extraction_version="resume_parse_v1")

    first = canonical_candidate_selection(
        [failed, ready],
        {ready.id: profile},
    )
    second = canonical_candidate_selection(
        [ready, failed],
        {ready.id: profile},
    )

    assert first == second
    assert sha256_json(first) == sha256_json(second)
    assert {item["parse_status"] for item in first} == {"ready", "failed"}
    assert (
        next(item for item in first if item["parse_status"] == "failed")["profile_id"]
        is None
    )


def test_candidate_ranking_uses_shared_five_dimensions_and_stable_tie_break() -> None:
    python_id = uuid4()
    requirements = requirement_inputs(
        {"requirements": [_requirement(python_id, "Python", "required")]}
    )
    skill = SimpleNamespace(
        id=uuid4(),
        capability_id=python_id,
        raw_name="Python",
        mapping_method="canonical_exact",
        evidence_strength="work",
        evidence_quote="负责 Python 后端开发",
    )
    candidate_b = _candidate_input(uuid4(), "B 候选人", [skill])
    candidate_a = _candidate_input(uuid4(), "A 候选人", [skill])
    missing = _candidate_input(uuid4(), "C 候选人", [])

    ranked = rank_candidate_matches(
        [candidate_b, missing, candidate_a],
        requirements,
        minimum_education_level="bachelor",
        recommended_experience_months=24,
    )

    assert [item.candidate.display_name for item in ranked] == [
        "A 候选人",
        "B 候选人",
        "C 候选人",
    ]
    assert [item.rank for item in ranked] == [1, 2, 3]
    assert ranked[0].scored.total_score == Decimal("100.00")
    assert ranked[-1].scored.missing_capabilities[0]["canonical_name"] == "Python"
    assert "candidate_skill" in ranked[0].scored.matched_capabilities[0]
