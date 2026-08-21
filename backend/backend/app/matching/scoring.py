from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

WEIGHT_VERSION = "match_weights_v1"
WEIGHTS = {
    "required_skill_coverage": Decimal("0.55"),
    "bonus_skill_coverage": Decimal("0.10"),
    "skill_evidence_quality": Decimal("0.15"),
    "experience": Decimal("0.15"),
    "education": Decimal("0.05"),
}
EVIDENCE_FACTORS = {
    "mention": Decimal("0.40"),
    "project": Decimal("0.70"),
    "work": Decimal("1.00"),
}
EDUCATION_RANKS = {
    "high_school": 1,
    "associate": 2,
    "bachelor": 3,
    "master": 4,
    "doctor": 5,
}
HIGH_MATCH_MINIMUM = Decimal("75.00")
MEDIUM_MATCH_MINIMUM = Decimal("50.00")
SCORE_QUANTUM = Decimal("0.01")

EvidenceStrength = Literal["mention", "project", "work"]
RequirementType = Literal["required", "bonus"]
MatchLevel = Literal["high", "medium", "low"]


class MatchCatalogInconsistent(ValueError):
    pass


@dataclass(frozen=True)
class ProfileSkillInput:
    id: UUID
    capability_id: UUID
    raw_name: str
    mapping_method: str
    evidence_strength: EvidenceStrength
    evidence_quote: str | None


@dataclass(frozen=True)
class ProfileMatchInput:
    highest_education_level: str | None
    total_experience_months: int | None
    skills: dict[UUID, ProfileSkillInput]


@dataclass(frozen=True)
class CapabilityRequirementInput:
    capability_id: UUID
    canonical_name: str
    skill_type: str
    requirement_type: RequirementType
    importance: Decimal
    domain_id: UUID
    domain_code: str
    domain_name: str


@dataclass(frozen=True)
class JobRoleMatchInput:
    job_role_id: UUID
    canonical_name: str
    description: str | None
    domain_id: UUID
    domain_code: str
    domain_name: str
    definition_payload: dict
    minimum_education_level: str | None
    recommended_experience_months: int | None
    capabilities: tuple[CapabilityRequirementInput, ...]


@dataclass(frozen=True)
class ScoredRequirements:
    total_score: Decimal
    match_level: MatchLevel
    required_skill_coverage: Decimal
    bonus_skill_coverage: Decimal
    skill_evidence_quality: Decimal
    experience_score: Decimal
    education_score: Decimal
    dimension_scores: dict
    matched_capabilities: list[dict]
    missing_capabilities: list[dict]
    gap_summary: dict


@dataclass(frozen=True)
class ScoredJobRole:
    job_role_id: UUID
    canonical_name: str
    total_score: Decimal
    match_level: MatchLevel
    required_skill_coverage: Decimal
    bonus_skill_coverage: Decimal
    skill_evidence_quality: Decimal
    experience_score: Decimal
    education_score: Decimal
    dimension_scores: dict
    matched_capabilities: list[dict]
    missing_capabilities: list[dict]
    gap_summary: dict
    job_role_snapshot: dict
    rank: int | None = None


def weight_snapshot() -> dict:
    return {
        "algorithm": "exact_capability_match_v1",
        "weights": {key: float(value) for key, value in WEIGHTS.items()},
        "evidence_factors": {
            key: float(value) for key, value in EVIDENCE_FACTORS.items()
        },
        "education_ranks": dict(EDUCATION_RANKS),
        "match_levels": {
            "high_minimum": float(HIGH_MATCH_MINIMUM),
            "medium_minimum": float(MEDIUM_MATCH_MINIMUM),
        },
        "rounding": "ROUND_HALF_UP_2DP",
    }


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def match_level(total_score: Decimal) -> MatchLevel:
    if total_score >= HIGH_MATCH_MINIMUM:
        return "high"
    if total_score >= MEDIUM_MATCH_MINIMUM:
        return "medium"
    return "low"


def score_profile_against_requirements(
    profile: ProfileMatchInput,
    requirements: tuple[CapabilityRequirementInput, ...],
    *,
    minimum_education_level: str | None,
    recommended_experience_months: int | None,
    skill_snapshot_key: str,
) -> ScoredRequirements:
    required = tuple(
        value for value in requirements if value.requirement_type == "required"
    )
    bonus = tuple(value for value in requirements if value.requirement_type == "bonus")
    required_raw, required_data = _coverage(required, profile, required=True)
    bonus_raw, bonus_data = _coverage(bonus, profile, required=False)
    matched = tuple(
        value for value in requirements if value.capability_id in profile.skills
    )
    evidence_raw, evidence_data = _evidence_quality(matched, profile)
    experience_raw, experience_data = _experience_score(
        profile.total_experience_months,
        recommended_experience_months,
    )
    education_raw, education_data = _education_score(
        profile.highest_education_level,
        minimum_education_level,
    )
    total_raw = (
        required_raw * WEIGHTS["required_skill_coverage"]
        + bonus_raw * WEIGHTS["bonus_skill_coverage"]
        + evidence_raw * WEIGHTS["skill_evidence_quality"]
        + experience_raw * WEIGHTS["experience"]
        + education_raw * WEIGHTS["education"]
    )
    total = quantize_score(total_raw)
    matched_capabilities, missing_capabilities = _capability_snapshots(
        requirements,
        profile,
        skill_snapshot_key=skill_snapshot_key,
    )
    return ScoredRequirements(
        total_score=total,
        match_level=match_level(total),
        required_skill_coverage=quantize_score(required_raw),
        bonus_skill_coverage=quantize_score(bonus_raw),
        skill_evidence_quality=quantize_score(evidence_raw),
        experience_score=quantize_score(experience_raw),
        education_score=quantize_score(education_raw),
        dimension_scores={
            "required_skill_coverage": required_data,
            "bonus_skill_coverage": bonus_data,
            "skill_evidence_quality": evidence_data,
            "experience": experience_data,
            "education": education_data,
        },
        matched_capabilities=matched_capabilities,
        missing_capabilities=missing_capabilities,
        gap_summary=_gap_summary(requirements, profile),
    )


def score_job_role(
    profile: ProfileMatchInput,
    job_role: JobRoleMatchInput,
) -> ScoredJobRole:
    scored = score_profile_against_requirements(
        profile,
        job_role.capabilities,
        minimum_education_level=job_role.minimum_education_level,
        recommended_experience_months=job_role.recommended_experience_months,
        skill_snapshot_key="resume_skill",
    )
    return ScoredJobRole(
        job_role_id=job_role.job_role_id,
        canonical_name=job_role.canonical_name,
        total_score=scored.total_score,
        match_level=scored.match_level,
        required_skill_coverage=scored.required_skill_coverage,
        bonus_skill_coverage=scored.bonus_skill_coverage,
        skill_evidence_quality=scored.skill_evidence_quality,
        experience_score=scored.experience_score,
        education_score=scored.education_score,
        dimension_scores=scored.dimension_scores,
        matched_capabilities=scored.matched_capabilities,
        missing_capabilities=scored.missing_capabilities,
        gap_summary=scored.gap_summary,
        job_role_snapshot={
            "id": str(job_role.job_role_id),
            "canonical_name": job_role.canonical_name,
            "description": job_role.description,
            "domain": {
                "id": str(job_role.domain_id),
                "code": job_role.domain_code,
                "name": job_role.domain_name,
            },
            "definition_payload": deepcopy(job_role.definition_payload),
        },
    )


def rank_scored_job_roles(values: list[ScoredJobRole]) -> list[ScoredJobRole]:
    ordered = sorted(
        values,
        key=lambda value: (
            -value.total_score,
            -value.required_skill_coverage,
            -value.skill_evidence_quality,
            -value.experience_score,
            -value.bonus_skill_coverage,
            -value.education_score,
            value.canonical_name.casefold(),
            str(value.job_role_id),
        ),
    )
    return [replace(value, rank=index) for index, value in enumerate(ordered, 1)]


def _coverage(
    requirements: tuple[CapabilityRequirementInput, ...],
    profile: ProfileMatchInput,
    *,
    required: bool,
) -> tuple[Decimal, dict]:
    if not requirements:
        if required:
            raise MatchCatalogInconsistent("job role has no required capability")
        return Decimal("100"), {
            "score": 100.0,
            "status": "not_required",
            "matched_count": 0,
            "total_count": 0,
            "matched_importance": 0.0,
            "total_importance": 0.0,
        }
    total_importance = sum(
        (value.importance for value in requirements),
        start=Decimal("0"),
    )
    if total_importance <= 0:
        raise MatchCatalogInconsistent("capability importance sum is not positive")
    matched = tuple(
        value for value in requirements if value.capability_id in profile.skills
    )
    matched_importance = sum(
        (value.importance for value in matched),
        start=Decimal("0"),
    )
    score = matched_importance / total_importance * Decimal("100")
    return score, {
        "score": _score_number(score),
        "status": "evaluated",
        "matched_count": len(matched),
        "total_count": len(requirements),
        "matched_importance": float(matched_importance),
        "total_importance": float(total_importance),
    }


def _evidence_quality(
    matched: tuple[CapabilityRequirementInput, ...],
    profile: ProfileMatchInput,
) -> tuple[Decimal, dict]:
    if not matched:
        return Decimal("0"), {
            "score": 0.0,
            "status": "no_matched_skill",
            "matched_count": 0,
            "evidence_weighted_importance": 0.0,
            "matched_importance": 0.0,
        }
    matched_importance = sum(
        (value.importance for value in matched),
        start=Decimal("0"),
    )
    weighted_importance = sum(
        (
            value.importance
            * EVIDENCE_FACTORS[profile.skills[value.capability_id].evidence_strength]
            for value in matched
        ),
        start=Decimal("0"),
    )
    score = weighted_importance / matched_importance * Decimal("100")
    return score, {
        "score": _score_number(score),
        "status": "evaluated",
        "matched_count": len(matched),
        "evidence_weighted_importance": float(weighted_importance),
        "matched_importance": float(matched_importance),
    }


def _experience_score(
    candidate_months: int | None,
    recommended_months: int | None,
) -> tuple[Decimal, dict]:
    if recommended_months is None or recommended_months == 0:
        score = Decimal("100")
        status = "not_required"
    elif candidate_months is None:
        score = Decimal("0")
        status = "unknown"
    elif candidate_months == 0:
        score = Decimal("0")
        status = "unmet"
    elif candidate_months < recommended_months:
        score = Decimal(candidate_months) / Decimal(recommended_months) * Decimal("100")
        status = "partial"
    else:
        score = Decimal("100")
        status = "satisfied"
    return score, {
        "score": _score_number(score),
        "status": status,
        "candidate_months": candidate_months,
        "recommended_months": recommended_months,
    }


def _education_score(
    candidate_level: str | None,
    minimum_level: str | None,
) -> tuple[Decimal, dict]:
    if minimum_level is None:
        score = Decimal("100")
        status = "not_required"
    elif candidate_level not in EDUCATION_RANKS:
        score = Decimal("0")
        status = "unknown"
    elif EDUCATION_RANKS[candidate_level] < EDUCATION_RANKS[minimum_level]:
        score = (
            Decimal(EDUCATION_RANKS[candidate_level])
            / Decimal(EDUCATION_RANKS[minimum_level])
            * Decimal("100")
        )
        status = "partial"
    else:
        score = Decimal("100")
        status = "satisfied"
    return score, {
        "score": _score_number(score),
        "status": status,
        "candidate_level": candidate_level,
        "minimum_level": minimum_level,
    }


def _capability_snapshots(
    requirements: tuple[CapabilityRequirementInput, ...],
    profile: ProfileMatchInput,
    *,
    skill_snapshot_key: str,
) -> tuple[list[dict], list[dict]]:
    matched = []
    missing = []
    for capability in sorted(requirements, key=_capability_sort_key):
        skill = profile.skills.get(capability.capability_id)
        if skill is None:
            missing.append(
                {
                    "capability_id": str(capability.capability_id),
                    "canonical_name": capability.canonical_name,
                    "skill_type": capability.skill_type,
                    "requirement_type": capability.requirement_type,
                    "importance": float(capability.importance),
                    "domain": {
                        "id": str(capability.domain_id),
                        "code": capability.domain_code,
                        "name": capability.domain_name,
                    },
                }
            )
            continue
        matched.append(
            {
                "capability_id": str(capability.capability_id),
                "canonical_name": capability.canonical_name,
                "requirement_type": capability.requirement_type,
                "importance": float(capability.importance),
                skill_snapshot_key: {
                    "id": str(skill.id),
                    "raw_name": skill.raw_name,
                    "mapping_method": skill.mapping_method,
                    "evidence_strength": skill.evidence_strength,
                    "evidence_factor": float(EVIDENCE_FACTORS[skill.evidence_strength]),
                    "evidence_quote": skill.evidence_quote,
                },
            }
        )
    return matched, missing


def _gap_summary(
    requirements: tuple[CapabilityRequirementInput, ...],
    profile: ProfileMatchInput,
) -> dict:
    return {
        "matched_required_count": sum(
            value.requirement_type == "required"
            and value.capability_id in profile.skills
            for value in requirements
        ),
        "missing_required_count": sum(
            value.requirement_type == "required"
            and value.capability_id not in profile.skills
            for value in requirements
        ),
        "matched_bonus_count": sum(
            value.requirement_type == "bonus" and value.capability_id in profile.skills
            for value in requirements
        ),
        "missing_bonus_count": sum(
            value.requirement_type == "bonus"
            and value.capability_id not in profile.skills
            for value in requirements
        ),
    }


def _capability_sort_key(value: CapabilityRequirementInput) -> tuple:
    return (
        0 if value.requirement_type == "required" else 1,
        -value.importance,
        value.canonical_name.casefold(),
        str(value.capability_id),
    )


def _score_number(value: Decimal) -> float:
    return float(quantize_score(value))
