import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/emerging-jobs", tags=["discovery"])
DATA_FILE = Path(__file__).parents[1] / "graph" / "emerging_jobs.json"


def load_emerging_jobs() -> dict:
    try:
        value = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(404, "新兴岗位快照不存在") from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(500, "新兴岗位快照读取失败") from error
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
        raise HTTPException(500, "新兴岗位快照格式无效")
    return value


@router.get("")
async def emerging_jobs(
    query: str | None = None,
    industry: str | None = None,
    status: Literal["pending", "approved", "rejected"] | None = None,
    sort_by: Literal["jdCount", "companyCount", "title"] = "jdCount",
) -> dict:
    value = load_emerging_jobs()
    normalized_query = query.strip().casefold() if query else None
    jobs = [
        job
        for job in value["jobs"]
        if (status is None or job.get("reviewStatusCode") == status)
        and (industry is None or industry in job.get("industryScenes", []))
        and (
            normalized_query is None
            or normalized_query
            in " ".join(
                [
                    str(job.get("title", "")),
                    str(job.get("normalizedName", "")),
                    *job.get("aliases", []),
                ]
            ).casefold()
        )
    ]
    key = {
        "jdCount": lambda job: (-int(job.get("jdCount", 0)), str(job.get("title", ""))),
        "companyCount": lambda job: (
            -int(job.get("companyCount", 0)),
            str(job.get("title", "")),
        ),
        "title": lambda job: str(job.get("title", "")),
    }[sort_by]
    return {"data": {**value, "jobs": sorted(jobs, key=key), "total": len(jobs)}}
