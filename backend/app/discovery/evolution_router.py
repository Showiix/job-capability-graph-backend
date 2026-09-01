import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/capability-evolution", tags=["discovery"])
DATA_FILE = Path(__file__).with_name("evolution_data.json")


@lru_cache(maxsize=1)
def load_evolution_data() -> dict:
    try:
        value = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise HTTPException(404, "能力演化数据不存在") from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(500, "能力演化数据读取失败") from error
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
        raise HTTPException(500, "能力演化数据格式无效")
    return value


@router.get("")
async def capability_evolution(
    query: str | None = None,
    change_type: str | None = None,
    confidence: Literal["高", "中", "低"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    value = load_evolution_data()
    normalized_query = query.strip().casefold() if query else None
    items = []
    for job in value["jobs"]:
        job_name = str(job.get("job_name", ""))
        for change in job.get("changes", []):
            skill = str(change.get("skill", ""))
            if (
                normalized_query
                and normalized_query not in f"{job_name} {skill}".casefold()
            ):
                continue
            if change_type and change.get("change_type") != change_type:
                continue
            if confidence and change.get("confidence") != confidence:
                continue
            items.append(
                {
                    "id": f"{job_name}:{skill}:{change.get('change_type', '')}",
                    "job_name": job_name,
                    "skill": skill,
                    "change_type": change.get("change_type"),
                    "effect_size": change.get("effect_size"),
                    "confidence": change.get("confidence"),
                    "action": change.get("action"),
                    "controls": change.get("controls", {}),
                    "evidence": change.get("evidence", {}),
                    "update_summary": job.get("update_summary"),
                    "trend_description": job.get("llm_trend_description"),
                }
            )
    items.sort(
        key=lambda item: (
            {"高": 0, "中": 1, "低": 2}.get(item["confidence"], 3),
            -float(item["effect_size"] or 0),
            item["job_name"],
            item["skill"],
        )
    )
    start = (page - 1) * page_size
    return {
        "data": {
            "items": items[start : start + page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "statistics": value.get("statistics", {}),
        }
    }
