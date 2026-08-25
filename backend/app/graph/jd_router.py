"""
JD数据知识图谱API路由
直接读取本地生成的JSON数据，无需数据库
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.imports.models import NormalizedJobPosting, RawJobPosting
from app.infrastructure.database import SessionFactory

router = APIRouter(prefix="/jd-graph", tags=["jd-graph"])

# JSON数据文件路径
GRAPH_DATA_FILE = Path(__file__).parent / "jd_graph_data.json"


def load_graph_data() -> dict:
    """加载图谱数据"""
    if not GRAPH_DATA_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="图谱数据文件不存在，请先运行 scripts/load_jd_data.py 生成数据",
        )

    try:
        return json.loads(GRAPH_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=500,
            detail="读取图谱数据失败",
        ) from error


@router.get("")
async def get_jd_graph() -> dict:
    """
    获取JD数据知识图谱

    返回格式：
    {
        "code": 200,
        "data": {
            "stars": [...],  # 恒星（岗位类别）
            "planets": [...],  # 行星（技能）
            "metadata": {...}  # 元数据
        },
        "message": "success"
    }
    """
    graph_data = load_graph_data()

    return {"code": 200, "data": graph_data, "message": "success"}


@router.get("/stats")
async def get_graph_stats() -> dict:
    """
    获取图谱统计信息
    """
    graph_data = load_graph_data()
    metadata = graph_data.get("metadata", {})

    # 统计技能类型分布
    planets = graph_data.get("planets", [])
    skill_types = {"core": 0, "foundation": 0, "frontier": 0}
    emerging_count = 0

    for planet in planets:
        skill_type = planet.get("type", "foundation")
        skill_types[skill_type] = skill_types.get(skill_type, 0) + 1
        if planet.get("isEmerging", False):
            emerging_count += 1

    return {
        "code": 200,
        "data": {
            "total_jobs": metadata.get("total_jobs", 0),
            "total_categories": metadata.get("total_categories", 0),
            "total_skills": metadata.get("total_skills", 0),
            "skill_distribution": skill_types,
            "emerging_skills": emerging_count,
            "generated_at": metadata.get("generated_at", ""),
        },
        "message": "success",
    }


@router.get("/trends")
async def get_graph_trends(months: int = 7) -> dict:
    months = max(1, min(months, 24))
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(NormalizedJobPosting.published_at, RawJobPosting.source_tags)
                .join(
                    RawJobPosting,
                    RawJobPosting.id == NormalizedJobPosting.raw_job_id,
                )
                .where(
                    NormalizedJobPosting.is_current.is_(True),
                    NormalizedJobPosting.published_at.is_not(None),
                )
            )
        ).all()
    by_month: dict[str, Counter[str]] = defaultdict(Counter)
    for published_at, tags in rows:
        month = published_at.strftime("%Y-%m")
        for tag in tags or []:
            if isinstance(tag, str) and tag.strip():
                by_month[month][tag.strip()] += 1
    selected_months = sorted(by_month)[-months:]
    top_skills = [
        name
        for name, _ in sum(
            (by_month[m] for m in selected_months), Counter()
        ).most_common(8)
    ]
    timeline = [
        {"month": month, **{skill: by_month[month][skill] for skill in top_skills}}
        for month in selected_months
    ]
    totals = Counter()
    for month in selected_months:
        totals.update(by_month[month])
    hot_skills = [
        {"name": name, "count": count}
        for name, count in totals.most_common(10)
    ]
    return {
        "data": {
            "months": selected_months,
            "timeline": timeline,
            "hot_skills": hot_skills,
            "coverage": {
                "months": len(selected_months),
                "dated_rows": sum(
                    by_month[m].total() for m in selected_months
                ),
            },
        }
    }
