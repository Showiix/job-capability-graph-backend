import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.matching.scoring import (
    CapabilityRequirementInput,
    ProfileMatchInput,
    ProfileSkillInput,
    ScoredRequirements,
    score_profile_against_requirements,
)


@dataclass(frozen=True, slots=True)
class RecruitmentCandidateMatchInput:
    candidate: Any
    profile_record: Any
    profile: ProfileMatchInput


@dataclass(frozen=True, slots=True)
class RankedCandidateMatch:
    candidate: Any
    profile_record: Any
    scored: ScoredRequirements
    rank: int | None = None


def requirement_inputs(snapshot: dict) -> tuple[CapabilityRequirementInput, ...]:
    return tuple(
        CapabilityRequirementInput(
            capability_id=UUID(item["capability_id"]),
            canonical_name=item["canonical_name"],
            skill_type=item["skill_type"],
            requirement_type=item["requirement_type"],
            importance=Decimal(str(item["importance"])),
            domain_id=UUID(item["domain"]["id"]),
            domain_code=item["domain"]["code"],
            domain_name=item["domain"]["name"],
        )
        for item in snapshot.get("requirements", [])
    )


def profile_input(profile: Any, skills: list[Any]) -> ProfileMatchInput:
    mapped = {
        skill.capability_id: ProfileSkillInput(
            id=skill.id,
            capability_id=skill.capability_id,
            raw_name=skill.raw_name,
            mapping_method=skill.mapping_method,
            evidence_strength=skill.evidence_strength,
            evidence_quote=skill.evidence_quote,
        )
        for skill in skills
        if skill.capability_id is not None
    }
    return ProfileMatchInput(
        highest_education_level=profile.highest_education_level,
        total_experience_months=profile.total_experience_months,
        skills=mapped,
    )


def canonical_candidate_selection(
    candidates: list[Any],
    profiles_by_candidate: dict[UUID, Any],
) -> list[dict]:
    selection = []
    for candidate in sorted(candidates, key=lambda item: str(item.id)):
        profile = profiles_by_candidate.get(candidate.id)
        selection.append(
            {
                "candidate_id": str(candidate.id),
                "parse_status": candidate.parse_status,
                "profile_id": str(profile.id) if profile is not None else None,
                "profile_version": 1 if profile is not None else None,
                "extraction_version": (
                    profile.extraction_version if profile is not None else None
                ),
            }
        )
    return selection


def rank_candidate_matches(
    candidates: list[RecruitmentCandidateMatchInput],
    requirements: tuple[CapabilityRequirementInput, ...],
    *,
    minimum_education_level: str | None,
    recommended_experience_months: int | None,
) -> list[RankedCandidateMatch]:
    scored = [
        RankedCandidateMatch(
            candidate=value.candidate,
            profile_record=value.profile_record,
            scored=score_profile_against_requirements(
                value.profile,
                requirements,
                minimum_education_level=minimum_education_level,
                recommended_experience_months=recommended_experience_months,
                skill_snapshot_key="candidate_skill",
            ),
        )
        for value in candidates
    ]
    ordered = sorted(
        scored,
        key=lambda value: (
            -value.scored.total_score,
            -value.scored.required_skill_coverage,
            -value.scored.skill_evidence_quality,
            -value.scored.experience_score,
            -value.scored.bonus_skill_coverage,
            -value.scored.education_score,
            value.candidate.display_name.casefold(),
            str(value.candidate.id),
        ),
    )
    return [replace(value, rank=index) for index, value in enumerate(ordered, 1)]


def candidate_snapshot(candidate: Any, profile: Any) -> dict:
    return {
        "candidate": {
            "id": str(candidate.id),
            "display_name": candidate.display_name,
            "file_id": str(candidate.file_id),
        },
        "profile": {
            "id": str(profile.id),
            "extraction_version": profile.extraction_version,
            "highest_education_level": profile.highest_education_level,
            "total_experience_months": profile.total_experience_months,
            "validation_warnings": list(
                profile.structured_payload.get("validation_warnings", [])
            ),
        },
    }


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
