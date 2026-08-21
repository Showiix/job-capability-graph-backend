#!/usr/bin/env python3
"""
从 merged_data 下的多平台 CSV 生成岗位-技能 3D 星图数据。

图中的恒星代表岗位类别，行星代表该岗位类别下高频技能；每颗恒星
同时保留少量真实 JD 样例，供前端详情抽屉展示。
"""

import csv
import json
import math
import os
import sqlite3
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Set


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JD_DATA_DIR = Path(os.getenv("JD_DATA_DIR", PROJECT_ROOT / "data"))
MERGED_DATA_DIR = Path(os.getenv("JD_MERGED_DATA_DIR", JD_DATA_DIR / "merged_data"))
SQLITE_DB = Path(os.getenv("JD_SQLITE_DB", JD_DATA_DIR / "outputs" / "tech_signals.sqlite"))
OUTPUT_FILE = Path(
    os.getenv(
        "JD_GRAPH_OUTPUT_FILE",
        PROJECT_ROOT / "backend" / "backend" / "app" / "graph" / "jd_graph_data.json",
    )
)
FRONTEND_PUBLIC_FILE = Path(
    os.getenv(
        "JD_GRAPH_FRONTEND_FILE",
        PROJECT_ROOT / "frontend" / "public" / "jd_graph_data.json",
    )
)

EMERGING_MARKERS = ("（新兴）", "(新兴)")

# 统一技能展示名，避免中英文、大小写、缩写被拆成多个节点。
SKILL_ALIASES = {
    "Python": ("python",),
    "Java": ("java",),
    "C++": ("c++", "cpp"),
    "C": (" c ", "c语言", "c语言开发"),
    "Go": ("golang", " go "),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "SQL": ("sql",),
    "R语言": ("r语言",),
    "Shell": ("shell", "bash"),
    "Spring": ("spring",),
    "Django": ("django",),
    "Flask": ("flask",),
    "FastAPI": ("fastapi",),
    "React": ("react",),
    "Vue": ("vue",),
    "Node.js": ("node.js", "nodejs"),
    "MySQL": ("mysql",),
    "PostgreSQL": ("postgresql",),
    "MongoDB": ("mongodb",),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch",),
    "Spark": ("spark",),
    "Hadoop": ("hadoop",),
    "Kafka": ("kafka",),
    "Flink": ("flink",),
    "Hive": ("hive",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "Linux": ("linux",),
    "Git": ("git",),
    "微服务": ("微服务",),
    "分布式系统": ("分布式",),
    "数据结构": ("数据结构",),
    "算法": ("算法",),
    "机器学习": ("机器学习", "machine learning"),
    "深度学习": ("深度学习", "deep learning"),
    "自然语言处理": ("自然语言处理", "nlp"),
    "计算机视觉": ("计算机视觉", "computer vision", "cv"),
    "图像处理": ("图像处理",),
    "图像算法": ("图像算法",),
    "目标检测": ("目标检测",),
    "语音识别": ("语音识别",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "Transformer": ("transformer",),
    "BERT": ("bert",),
    "大模型": ("大模型", "llm", "large language model"),
    "AIGC": ("aigc",),
    "生成式 AI": ("生成式ai", "生成式 ai", "生成式人工智能"),
    "RAG": ("rag", "检索增强"),
    "Prompt 工程": ("prompt",),
    "知识图谱": ("知识图谱",),
    "数据分析": ("数据分析",),
    "数据挖掘": ("数据挖掘",),
    "数据仓库": ("数据仓库",),
    "数据开发": ("数据开发",),
    "数据架构": ("数据架构",),
    "ETL": ("etl",),
    "BI": ("bi", "商业智能"),
    "统计学": ("统计学",),
    "嵌入式": ("嵌入式",),
    "单片机": ("单片机",),
    "物联网": ("物联网",),
    "传感器": ("传感器",),
    "芯片": ("芯片",),
    "FPGA": ("fpga",),
    "Verilog": ("verilog",),
    "CMake": ("cmake",),
    "自动化测试": ("自动化测试",),
    "软件测试": ("软件测试",),
    "项目管理": ("项目管理",),
    "需求分析": ("需求分析",),
    "产品设计": ("产品设计",),
    "云计算": ("云计算",),
    "云原生": ("云原生",),
    "数字孪生": ("数字孪生",),
    "机器人": ("机器人",),
}

JOB_SKILL_MAP = {
    "Python": ["Python", "算法", "数据结构"],
    "Java": ["Java", "Spring", "SQL", "数据结构"],
    "自然语言处理算法": ["Python", "自然语言处理", "深度学习", "Transformer"],
    "深度学习": ["Python", "深度学习", "PyTorch", "算法"],
    "机器学习": ["Python", "机器学习", "数据分析", "算法"],
    "大模型算法": ["Python", "大模型", "深度学习", "Transformer"],
    "AIGC算法": ["Python", "AIGC", "生成式 AI", "大模型"],
    "图像算法": ["Python", "计算机视觉", "图像处理", "深度学习"],
    "数据开发": ["SQL", "数据开发", "数据仓库", "ETL"],
    "数据架构师": ["数据架构", "数据仓库", "分布式系统", "SQL"],
    "数据挖掘": ["Python", "数据挖掘", "机器学习", "SQL"],
    "数据仓库": ["SQL", "数据仓库", "ETL", "数据开发"],
    "嵌入式软件工程师": ["C", "C++", "嵌入式", "单片机"],
    "单片机": ["C", "嵌入式", "单片机", "物联网"],
    "芯片工程师": ["芯片", "C++", "FPGA", "Verilog"],
    "物联网安装调试员": ["物联网", "传感器", "嵌入式"],
    "具身智能机器人应用技术员": ["机器人", "Python", "算法", "物联网"],
    "云计算工程师": ["云计算", "Linux", "Docker", "Kubernetes"],
    "云网智能运维员": ["云计算", "Linux", "Docker", "自动化测试"],
    "数字孪生工程技术人员": ["数字孪生", "数据分析", "物联网"],
}

ROLE_COLORS = ["#fff3ea", "#e4b592", "#dad0c8", "#b9aea4", "#ee1212"]
SOURCE_ALIASES = {
    "zhilian_direct": "zhilian",
    "zhilian": "zhilian",
    "job51zp": "job51",
    "job51": "job51",
    "bosszp": "boss",
    "boss": "boss",
    "liepin": "liepin",
}


def strip_emerging_marker(category: str) -> str:
    for marker in EMERGING_MARKERS:
        category = category.replace(marker, "")
    return category.strip()


def category_from_file(path: Path) -> str:
    category = path.stem
    for prefix in ("zhilian_direct_", "job51zp_", "bosszp_", "liepin_"):
        if category.startswith(prefix):
            category = category[len(prefix):]
            break
    return category.strip() or "未命名岗位"


def normalize_source(raw: str, fallback: str) -> str:
    candidate = (raw or "").strip().lower()
    if candidate in SOURCE_ALIASES:
        return SOURCE_ALIASES[candidate]
    for key, value in SOURCE_ALIASES.items():
        if candidate.startswith(key):
            return value
    return fallback


def row_to_sample(row: Dict[str, str], source: str) -> Dict[str, str]:
    return {
        "jobName": (row.get("job_name") or "").strip(),
        "companyName": (row.get("company_name") or "").strip(),
        "salary": (row.get("salary") or "").strip(),
        "city": (row.get("city") or row.get("work_area") or "").strip(),
        "education": (row.get("education") or "").strip(),
        "workYear": (row.get("work_year") or "").strip(),
        "source": source,
        "url": (row.get("job_url") or "").strip(),
    }


def load_csv_files() -> tuple[Dict[str, List[Dict[str, str]]], Dict[str, Set[str]], int]:
    """递归读取 merged_data 下全部 CSV，并按岗位类别聚合。"""
    if not MERGED_DATA_DIR.exists():
        raise FileNotFoundError(f"merged_data 不存在: {MERGED_DATA_DIR}")

    jobs_by_category: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    sources_by_category: Dict[str, Set[str]] = defaultdict(set)
    csv_files = sorted(MERGED_DATA_DIR.rglob("*.csv"))

    for csv_file in csv_files:
        category = category_from_file(csv_file)
        try:
            with open(csv_file, "r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    source = normalize_source(row.get("source") or csv_file.parent.name, csv_file.parent.name)
                    row["_source"] = source
                    jobs_by_category[category].append(row)
                    sources_by_category[category].add(source)
        except OSError as exc:
            print(f"读取失败，跳过 {csv_file}: {exc}")

    total_jobs = sum(len(rows) for rows in jobs_by_category.values())
    print(f"已读取 {len(csv_files)} 个 CSV，{len(jobs_by_category)} 个岗位类别，{total_jobs} 条 JD")
    return dict(jobs_by_category), dict(sources_by_category), len(csv_files)


def load_sqlite_trends() -> Dict[str, Dict[str, float]]:
    """读取已有技能趋势；没有数据库时不影响本地 JD 图谱生成。"""
    if not SQLITE_DB.exists():
        return {}

    trends: Dict[str, Dict[str, float]] = {}
    try:
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT keyword, last_count, last_burst_score FROM keyword_stats")
            for keyword, count, burst_score in cursor.fetchall():
                trends[str(keyword).lower()] = {
                    "count": float(count or 0),
                    "burst_score": float(burst_score or 0),
                    "is_emerging": float(burst_score or 0) > 1.5,
                }
    except (OSError, sqlite3.Error) as exc:
        print(f"读取技能趋势失败，继续生成图谱: {exc}")
    return trends


def extract_skills_from_text(text: str) -> Set[str]:
    normalized = f" {text.lower()} "
    skills: Set[str] = set()
    for display_name, aliases in SKILL_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            skills.add(display_name)
    return skills


def role_seed_skills(category: str) -> Set[str]:
    base = strip_emerging_marker(category)
    skills: Set[str] = set()
    for role_name, mapped_skills in JOB_SKILL_MAP.items():
        if base == role_name or role_name in base or base in role_name:
            skills.update(mapped_skills)
    return skills


def is_emerging_skill(skill: str, trends: Dict[str, Dict[str, float]]) -> bool:
    lowered = skill.lower()
    trend = trends.get(lowered)
    if trend and trend.get("is_emerging"):
        return True
    return skill in {"大模型", "AIGC", "生成式 AI", "RAG", "数字孪生", "机器人", "芯片"}


def role_domain(category: str) -> str:
    base = strip_emerging_marker(category)
    if "数据" in base or "仓库" in base or "ETL" in base:
        return "数据工程"
    if any(token in base for token in ("算法", "机器学习", "深度学习", "人工智能", "大模型", "自然语言", "图像")):
        return "人工智能"
    if any(token in base for token in ("芯片", "嵌入式", "单片机", "电子", "FPGA", "物联网")):
        return "智能硬件"
    if any(token in base for token in ("云", "运维", "系统集成")):
        return "云与基础设施"
    return "软件与产品"


def stable_position(index: int) -> List[float]:
    """用黄金角生成稳定的 3D 视野分布，避免每次刷新位置都跳动。"""
    golden_angle = math.pi * (3 - math.sqrt(5))
    ring = 7.5 + (index % 8) * 1.35
    angle = index * golden_angle
    y_cycle = (index * 5) % 9
    y = (y_cycle - 4) * 0.75
    return [round(math.cos(angle) * ring, 3), round(y, 3), round(math.sin(angle) * ring, 3)]


def skill_type(skill: str, frequency: int, job_count: int, category: str, trends: Dict[str, Dict[str, float]]) -> str:
    if is_emerging_skill(skill, trends):
        return "frontier"
    if frequency >= max(2, int(job_count * 0.28)):
        return "core"
    return "foundation"


def build_graph(
    jobs_by_category: Dict[str, List[Dict[str, str]]],
    sources_by_category: Dict[str, Set[str]],
    total_files: int,
    trends: Dict[str, Dict[str, float]],
) -> Dict:
    categories = sorted(
        jobs_by_category,
        key=lambda category: ("新兴" not in category, -len(jobs_by_category[category]), category),
    )

    global_skill_frequency: Counter[str] = Counter()
    category_skill_frequency: Dict[str, Counter[str]] = {}
    category_samples: Dict[str, List[Dict[str, str]]] = {}
    source_totals: Counter[str] = Counter()

    for category in categories:
        rows = jobs_by_category[category]
        skill_frequency: Counter[str] = Counter()
        seen_sample_keys: Set[str] = set()
        samples: List[Dict[str, str]] = []
        seeded_skills = role_seed_skills(category)

        for row in rows:
            source = row.get("_source", "unknown")
            source_totals[source] += 1
            text = " ".join((row.get(column) or "") for column in ("job_name", "skill_requirements", "tech_tags"))
            row_skills = extract_skills_from_text(text) | seeded_skills
            for skill in row_skills:
                skill_frequency[skill] += 1
                global_skill_frequency[skill] += 1

            sample = row_to_sample(row, source)
            sample_key = sample["url"] or "|".join((sample["jobName"], sample["companyName"], sample["city"]))
            if sample["jobName"] and sample_key not in seen_sample_keys and len(samples) < 5:
                seen_sample_keys.add(sample_key)
                samples.append(sample)

        category_skill_frequency[category] = skill_frequency
        category_samples[category] = samples

    stars: List[Dict] = []
    planets: List[Dict] = []
    emerging_categories = [category for category in categories if "新兴" in category]
    featured_categories = sorted(
        emerging_categories or categories,
        key=lambda category: (-len(jobs_by_category[category]), category),
    )[:8]

    if len(featured_categories) < 8:
        for category in categories:
            if category not in featured_categories:
                featured_categories.append(category)
            if len(featured_categories) >= 8:
                break

    star_ids: Dict[str, str] = {}
    category_colors: Dict[str, str] = {}

    for index, category in enumerate(categories):
        star_id = f"star_{index}"
        star_ids[category] = star_id
        is_emerging = "新兴" in category
        category_colors[category] = "#ee1212" if is_emerging else ROLE_COLORS[index % len(ROLE_COLORS)]
        frequency = category_skill_frequency[category]
        max_frequency = max(frequency.values() or [1])
        required_skills = [
            skill
            for skill, count in frequency.most_common(8)
            if count >= max(2, int(len(jobs_by_category[category]) * 0.28))
        ][:5]
        bonus_skills = [skill for skill, _ in frequency.most_common(10) if skill not in required_skills][:5]

        stars.append({
            "id": star_id,
            "name": category,
            "label": category,
            "domain": role_domain(category),
            "position": stable_position(index),
            "color": category_colors[category],
            "size": round(0.86 + min(len(jobs_by_category[category]) / 900, 0.62), 3),
            "jobCount": len(jobs_by_category[category]),
            "sources": len(jobs_by_category[category]),
            "sourceCounts": dict(Counter(row.get("_source", "unknown") for row in jobs_by_category[category])),
            "isEmerging": is_emerging,
            "requiredSkills": required_skills,
            "bonusSkills": bonus_skills,
            "sampleJobs": category_samples[category],
        })

        for skill_index, (skill, frequency_count) in enumerate(frequency.most_common(10)):
            current_type = skill_type(skill, frequency_count, len(jobs_by_category[category]), category, trends)
            is_required = skill in required_skills
            related_categories = sum(skill in freq for freq in category_skill_frequency.values())
            orbit_radius = 2.35 + (skill_index if is_required else skill_index + 3) * 0.46
            type_colors = {"core": "#ee1212", "foundation": "#dad0c8", "frontier": "#e4b592"}

            planets.append({
                "id": f"{star_id}_planet_{skill_index}",
                "name": skill,
                "label": skill,
                "type": current_type,
                "starId": star_id,
                "isRequired": is_required,
                "distance": round(orbit_radius, 3),
                "orbitRadius": round(orbit_radius, 3),
                "speed": round(0.24 if is_required else 0.14, 3),
                "size": 0.18 if not is_required else 0.23,
                "color": type_colors[current_type],
                "relatedJobs": related_categories,
                "frequency": frequency_count,
                "confidence": round(min(98, 52 + (frequency_count / max_frequency) * 46), 1),
                "isEmerging": is_emerging_skill(skill, trends),
            })

    featured_star_ids = [star_ids[category] for category in featured_categories]

    return {
        "stars": stars,
        "planets": planets,
        "metadata": {
            "total_jobs": sum(len(rows) for rows in jobs_by_category.values()),
            "total_categories": len(categories),
            "total_skills": len(global_skill_frequency),
            "total_planets": len(planets),
            "total_files": total_files,
            "source_counts": dict(source_totals),
            "featured_star_ids": featured_star_ids,
            "featured_categories": featured_categories,
            "generated_at": date.today().isoformat(),
        },
    }


def save_graph_data(graph_data: Dict) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(graph_data, handle, ensure_ascii=False, indent=2)
    FRONTEND_PUBLIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUTPUT_FILE, FRONTEND_PUBLIC_FILE)
    print(f"已保存: {OUTPUT_FILE}")
    print(f"已同步: {FRONTEND_PUBLIC_FILE}")
    print(
        "图谱完成: "
        f"{graph_data['metadata']['total_categories']} 个岗位类别, "
        f"{graph_data['metadata']['total_jobs']} 条 JD, "
        f"{graph_data['metadata']['total_planets']} 个技能节点"
    )


def main() -> None:
    print("开始生成 JD 岗位-技能知识图谱")
    jobs_by_category, sources_by_category, total_files = load_csv_files()
    trends = load_sqlite_trends()
    graph_data = build_graph(jobs_by_category, sources_by_category, total_files, trends)
    save_graph_data(graph_data)


if __name__ == "__main__":
    main()
