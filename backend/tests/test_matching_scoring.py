from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.matching.scoring import (
    EDUCATION_RANKS,
    EVIDENCE_FACTORS,
    WEIGHT_VERSION,
    WEIGHTS,
    CapabilityRequirementInput,
    JobRoleMatchInput,
    MatchCatalogInconsistent,
    ProfileMatchInput,
    ProfileSkillInput,
    ScoredJobRole,
    match_level,
    quantize_score,
    rank_scored_job_roles,
    score_job_role,
    weight_snapshot,
)


def _capability(
    name: str,
    requirement_type: str,
    importance: str,
    *,
    capability_id: UUID | None = None,
) -> CapabilityRequirementInput:
    return CapabilityRequirementInput(
        capability_id=capability_id or uuid4(),
        canonical_name=name,
        skill_type="tool",
        requirement_type=requirement_type,
        importance=Decimal(importance),
        domain_id=UUID("10000000-0000-4000-8000-000000000001"),
        domain_code="ai",
        domain_name="人工智能",
    )


def _skill(
    capability: CapabilityRequirementInput,
    evidence_strength: str,
) -> ProfileSkillInput:
    return ProfileSkillInput(
        id=uuid4(),
        capability_id=capability.capability_id,
        raw_name=capability.canonical_name,
        mapping_method="canonical_exact",
        evidence_strength=evidence_strength,
        evidence_quote=f"使用 {capability.canonical_name} 完成项目",
    )


def _role(
    capabilities: tuple[CapabilityRequirementInput, ...],
    *,
    canonical_name: str = "AI 应用工程师",
    minimum_education_level: str | None = "bachelor",
    recommended_experience_months: int | None = 24,
    job_role_id: UUID | None = None,
) -> JobRoleMatchInput:
    role_id = job_role_id or uuid4()
    return JobRoleMatchInput(
        job_role_id=role_id,
        canonical_name=canonical_name,
        description="负责 AI 应用开发",
        domain_id=UUID("10000000-0000-4000-8000-000000000001"),
        domain_code="ai",
        domain_name="人工智能",
        definition_payload={
            "role_name": canonical_name,
            "match_policy": {
                "minimum_education_level": minimum_education_level,
                "recommended_experience_months": recommended_experience_months,
            },
        },
        minimum_education_level=minimum_education_level,
        recommended_experience_months=recommended_experience_months,
        capabilities=capabilities,
    )


def _profile(
    skills: list[ProfileSkillInput],
    *,
    education: str | None = "associate",
    experience_months: int | None = 18,
) -> ProfileMatchInput:
    return ProfileMatchInput(
        highest_education_level=education,
        total_experience_months=experience_months,
        skills={skill.capability_id: skill for skill in skills},
    )


def test_weight_version_and_snapshot_are_fixed() -> None:
    assert WEIGHT_VERSION == "match_weights_v1"
    assert WEIGHTS == {
        "required_skill_coverage": Decimal("0.55"),
        "bonus_skill_coverage": Decimal("0.10"),
        "skill_evidence_quality": Decimal("0.15"),
        "experience": Decimal("0.15"),
        "education": Decimal("0.05"),
    }
    assert EVIDENCE_FACTORS == {
        "mention": Decimal("0.40"),
        "project": Decimal("0.70"),
        "work": Decimal("1.00"),
    }
    assert EDUCATION_RANKS == {
        "high_school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "doctor": 5,
    }
    assert weight_snapshot() == {
        "algorithm": "exact_capability_match_v1",
        "weights": {
            "required_skill_coverage": 0.55,
            "bonus_skill_coverage": 0.1,
            "skill_evidence_quality": 0.15,
            "experience": 0.15,
            "education": 0.05,
        },
        "evidence_factors": {"mention": 0.4, "project": 0.7, "work": 1.0},
        "education_ranks": EDUCATION_RANKS,
        "match_levels": {"high_minimum": 75.0, "medium_minimum": 50.0},
        "rounding": "ROUND_HALF_UP_2DP",
    }


def test_complete_five_dimension_score_uses_unrounded_decimal_values() -> None:
    python = _capability("Python", "required", "1.0")
    pytorch = _capability("PyTorch", "required", "1.0")
    kubernetes = _capability("Kubernetes", "required", "0.5")
    docker = _capability("Docker", "bonus", "0.5")
    mlops = _capability("MLOps", "bonus", "0.5")
    role = _role((python, pytorch, kubernetes, docker, mlops))
    profile = _profile(
        [
            _skill(python, "work"),
            _skill(pytorch, "project"),
            _skill(docker, "mention"),
        ]
    )

    result = score_job_role(profile, role)

    assert result.required_skill_coverage == Decimal("80.00")
    assert result.bonus_skill_coverage == Decimal("50.00")
    assert result.skill_evidence_quality == Decimal("76.00")
    assert result.experience_score == Decimal("75.00")
    assert result.education_score == Decimal("66.67")
    assert result.total_score == Decimal("74.98")
    assert result.match_level == "medium"
    assert result.dimension_scores == {
        "required_skill_coverage": {
            "score": 80.0,
            "status": "evaluated",
            "matched_count": 2,
            "total_count": 3,
            "matched_importance": 2.0,
            "total_importance": 2.5,
        },
        "bonus_skill_coverage": {
            "score": 50.0,
            "status": "evaluated",
            "matched_count": 1,
            "total_count": 2,
            "matched_importance": 0.5,
            "total_importance": 1.0,
        },
        "skill_evidence_quality": {
            "score": 76.0,
            "status": "evaluated",
            "matched_count": 3,
            "evidence_weighted_importance": 1.9,
            "matched_importance": 2.5,
        },
        "experience": {
            "score": 75.0,
            "status": "partial",
            "candidate_months": 18,
            "recommended_months": 24,
        },
        "education": {
            "score": 66.67,
            "status": "partial",
            "candidate_level": "associate",
            "minimum_level": "bachelor",
        },
    }
    assert [item["canonical_name"] for item in result.matched_capabilities] == [
        "Python",
        "PyTorch",
        "Docker",
    ]
    assert [item["canonical_name"] for item in result.missing_capabilities] == [
        "Kubernetes",
        "MLOps",
    ]
    assert result.matched_capabilities[0]["resume_skill"]["evidence_factor"] == 1.0
    assert result.missing_capabilities[0]["domain"] == {
        "id": "10000000-0000-4000-8000-000000000001",
        "code": "ai",
        "name": "人工智能",
    }
    assert result.gap_summary == {
        "matched_required_count": 2,
        "missing_required_count": 1,
        "matched_bonus_count": 1,
        "missing_bonus_count": 1,
    }
    assert result.job_role_snapshot["id"] == str(role.job_role_id)
    assert result.job_role_snapshot["definition_payload"] == role.definition_payload


def test_no_bonus_is_neutral_and_no_matched_skill_has_zero_evidence() -> None:
    python = _capability("Python", "required", "1.0")
    result = score_job_role(
        _profile([], education=None, experience_months=None),
        _role(
            (python,),
            minimum_education_level=None,
            recommended_experience_months=None,
        ),
    )

    assert result.required_skill_coverage == Decimal("0.00")
    assert result.bonus_skill_coverage == Decimal("100.00")
    assert result.skill_evidence_quality == Decimal("0.00")
    assert result.dimension_scores["bonus_skill_coverage"]["status"] == ("not_required")
    assert result.dimension_scores["skill_evidence_quality"]["status"] == (
        "no_matched_skill"
    )
    assert result.experience_score == Decimal("100.00")
    assert result.education_score == Decimal("100.00")


@pytest.mark.parametrize(
    "capabilities",
    [
        (),
        (_capability("Python", "bonus", "1.0"),),
        (_capability("Python", "required", "0"),),
        (
            _capability("Python", "required", "1.0"),
            _capability("Docker", "bonus", "0"),
        ),
    ],
)
def test_invalid_catalog_importance_is_rejected(capabilities) -> None:
    with pytest.raises(MatchCatalogInconsistent):
        score_job_role(_profile([]), _role(capabilities))


@pytest.mark.parametrize(
    ("candidate", "recommended", "score", "status"),
    [
        (None, None, Decimal("100.00"), "not_required"),
        (None, 0, Decimal("100.00"), "not_required"),
        (None, 24, Decimal("0.00"), "unknown"),
        (0, 24, Decimal("0.00"), "unmet"),
        (18, 24, Decimal("75.00"), "partial"),
        (24, 24, Decimal("100.00"), "satisfied"),
        (36, 24, Decimal("100.00"), "satisfied"),
    ],
)
def test_experience_scoring(candidate, recommended, score, status) -> None:
    python = _capability("Python", "required", "1.0")
    result = score_job_role(
        _profile([_skill(python, "work")], experience_months=candidate),
        _role(
            (python,),
            minimum_education_level=None,
            recommended_experience_months=recommended,
        ),
    )

    assert result.experience_score == score
    assert result.dimension_scores["experience"]["status"] == status


@pytest.mark.parametrize(
    ("candidate", "minimum", "score", "status"),
    [
        (None, None, Decimal("100.00"), "not_required"),
        (None, "bachelor", Decimal("0.00"), "unknown"),
        ("other", "bachelor", Decimal("0.00"), "unknown"),
        ("unknown", "bachelor", Decimal("0.00"), "unknown"),
        ("associate", "bachelor", Decimal("66.67"), "partial"),
        ("bachelor", "bachelor", Decimal("100.00"), "satisfied"),
        ("master", "bachelor", Decimal("100.00"), "satisfied"),
    ],
)
def test_education_scoring(candidate, minimum, score, status) -> None:
    python = _capability("Python", "required", "1.0")
    result = score_job_role(
        _profile([_skill(python, "work")], education=candidate),
        _role(
            (python,),
            minimum_education_level=minimum,
            recommended_experience_months=None,
        ),
    )

    assert result.education_score == score
    assert result.dimension_scores["education"]["status"] == status


def test_rounding_and_match_level_boundaries() -> None:
    assert quantize_score(Decimal("66.665")) == Decimal("66.67")
    assert match_level(Decimal("49.99")) == "low"
    assert match_level(Decimal("50.00")) == "medium"
    assert match_level(Decimal("74.99")) == "medium"
    assert match_level(Decimal("75.00")) == "high"


def _scored(
    *,
    job_role_id: UUID | None = None,
    canonical_name: str = "Role",
    total: str = "80",
    required: str = "80",
    evidence: str = "80",
    experience: str = "80",
    bonus: str = "80",
    education: str = "80",
) -> ScoredJobRole:
    return ScoredJobRole(
        job_role_id=job_role_id or uuid4(),
        canonical_name=canonical_name,
        total_score=Decimal(total),
        match_level="high",
        required_skill_coverage=Decimal(required),
        bonus_skill_coverage=Decimal(bonus),
        skill_evidence_quality=Decimal(evidence),
        experience_score=Decimal(experience),
        education_score=Decimal(education),
        dimension_scores={},
        matched_capabilities=[],
        missing_capabilities=[],
        gap_summary={},
        job_role_snapshot={},
    )


@pytest.mark.parametrize(
    ("winner", "loser"),
    [
        ({"total": "81"}, {"total": "80"}),
        ({"required": "81"}, {"required": "80"}),
        ({"evidence": "81"}, {"evidence": "80"}),
        ({"experience": "81"}, {"experience": "80"}),
        ({"bonus": "81"}, {"bonus": "80"}),
        ({"education": "81"}, {"education": "80"}),
        ({"canonical_name": "alpha"}, {"canonical_name": "Beta"}),
    ],
)
def test_stable_ranking_uses_each_score_and_name_tie_break(winner, loser) -> None:
    ranked = rank_scored_job_roles([_scored(**loser), _scored(**winner)])

    assert ranked[0].rank == 1
    assert ranked[1].rank == 2
    attribute_names = {
        "total": "total_score",
        "required": "required_skill_coverage",
        "evidence": "skill_evidence_quality",
        "experience": "experience_score",
        "bonus": "bonus_skill_coverage",
        "education": "education_score",
        "canonical_name": "canonical_name",
    }
    for key, value in winner.items():
        assert getattr(ranked[0], attribute_names[key]) == (
            Decimal(value) if key != "canonical_name" else value
        )


def test_stable_ranking_uses_uuid_as_final_tie_break() -> None:
    first_id = UUID("00000000-0000-4000-8000-000000000001")
    second_id = UUID("00000000-0000-4000-8000-000000000002")

    ranked = rank_scored_job_roles(
        [
            _scored(job_role_id=second_id),
            _scored(job_role_id=first_id),
        ]
    )

    assert [item.job_role_id for item in ranked] == [first_id, second_id]
    assert [item.rank for item in ranked] == [1, 2]
