from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

MODEL_VERSION = "graph_match_v1.0"
MASTERY_RANK = {
    "aware": 0,
    "了解": 0,
    "familiar": 1,
    "熟悉": 1,
    "proficient": 2,
    "熟练": 2,
    "expert": 3,
    "精通": 3,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeightedSkill(StrictModel):
    skill: str = Field(min_length=1, max_length=200)
    weight: float = Field(gt=0)


class JobDefinition(StrictModel):
    job_name: str | None = None
    required_skills: list[WeightedSkill]
    bonus_skills: list[str] = Field(default_factory=list)


class ResumeSkill(StrictModel):
    skill: str = Field(min_length=1, max_length=200)
    mastery: str = "proficient"


class ResumeDefinition(StrictModel):
    skills: list[str | ResumeSkill] = Field(default_factory=list)
    years_experience: float | None = None


class MatchRequest(StrictModel):
    job_id: str = Field(min_length=1, max_length=200)
    job: JobDefinition
    resume: list[str | ResumeSkill] | ResumeDefinition


app = FastAPI(title="Graph Match Model", version=MODEL_VERSION)


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _resume_skills(
    resume: list[str | ResumeSkill] | ResumeDefinition,
) -> dict[str, int]:
    values = resume.skills if isinstance(resume, ResumeDefinition) else resume
    result: dict[str, int] = {}
    for value in values:
        if isinstance(value, str):
            name, mastery = value, "proficient"
        else:
            name, mastery = value.skill, value.mastery
        key = _normalize(name)
        rank = MASTERY_RANK.get(mastery, MASTERY_RANK.get(_normalize(mastery), 2))
        result[key] = max(result.get(key, -1), rank)
    return result


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.post("/match")
def match(payload: MatchRequest) -> dict[str, Any]:
    resume = _resume_skills(payload.resume)
    required = payload.job.required_skills
    total_weight = sum(value.weight for value in required)
    satisfied = [
        value.skill
        for value in required
        if resume.get(_normalize(value.skill), -1) >= 1
    ]
    missing = [value.skill for value in required if value.skill not in satisfied]
    hit_weight = sum(
        value.weight for value in required if value.skill in satisfied
    )
    score = hit_weight / total_weight if total_weight else 0.0
    bonus_hit = [
        value
        for value in payload.job.bonus_skills
        if resume.get(_normalize(value), -1) >= 1
    ]
    level = "match" if score >= 0.8 else "partial" if score >= 0.5 else "mismatch"
    return {
        "job_id": payload.job_id,
        "match_score": score,
        "match_level": level,
        "required": {
            "total_weight": total_weight,
            "hit_weight": hit_weight,
            "coverage": score,
            "satisfied": satisfied,
            "missing": missing,
        },
        "bonus": {
            "hit": bonus_hit,
            "miss": [
                value for value in payload.job.bonus_skills if value not in bonus_hit
            ],
        },
        "gap_analysis": [{"skill": value} for value in missing],
        "learning_path": None,
        "meta": {"model_version": MODEL_VERSION},
    }
