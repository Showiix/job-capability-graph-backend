"""
JD数据知识图谱API路由
直接读取本地生成的JSON数据，无需数据库
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

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
