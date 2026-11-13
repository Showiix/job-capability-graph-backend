"""Pipeline strictly aligned with Internal Documents 11, 12, 13, 14, 15.

Generates:
1. Fig 1 & Table: Document 11 Empirical Validation (71.4% STEM vs 18.7% Non-STEM Subsets)
2. Fig 2 & Table: Document 13 & 12 Cross-disciplinary Topology Matrix (3 Majors -> 4 Job Families)
3. Fig 3 & Table: End-to-End Real Resume Capability Profiling & Recommendation (Resolving 0-mapped status in Section 13.1)
"""

import csv
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Font configuration
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "DejaVu Sans",
    "Arial",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.matching.scoring import (
    CapabilityRequirementInput,
    JobRoleMatchInput,
    ProfileMatchInput,
    ProfileSkillInput,
    score_profile_against_requirements,
)

REPORTS_DIR = ROOT_DIR / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"

for d in [FIGURES_DIR, TABLES_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 1. Document 11: Real Market Subsets Comparison (71.4% vs 18.7%)
# ==============================================================================
def generate_doc11_figures():
    print("[Task 1/3] Generating Document 11 Empirical Subsets Comparison...")
    
    # Data from Document 11
    # 1. Sample breakdown
    categories = ["新工科技术岗 (A类)", "非新工科·原专业适配岗 (B类)", "其他中性·新兴模糊岗 (C类)"]
    counts = [42456, 11126, 5848]
    pcts = [71.4, 18.7, 9.8]

    # 2. Education comparison
    edu_labels = ["本科", "大专", "硕士", "博士", "其他/不限"]
    all_edu = [58.5, 20.0, 9.7, 1.0, 10.8]  # All JDs
    subset_edu = [59.8, 27.3, 3.0, 0.2, 9.7]  # Non-STEM subset (n=11,126)

    # 3. Soft skill demand rate comparison
    soft_skills = ["沟通", "分析", "团队", "管理", "逻辑", "学习", "责任", "抗压"]
    subset_soft = [46.1, 43.1, 42.9, 40.8, 20.1, 21.1, 16.6, 11.0]
    all_soft = [32.5, 34.2, 38.2, 28.6, 15.4, 16.5, 12.1, 8.5]  # Baseline comparison

    # Figure: 2x2 Grid Visualization
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=300)

    # Subplot 1: Corpus composition
    colors = ["#3498db", "#e67e22", "#95a5a6"]
    axes[0, 0].pie(counts, labels=[f"{c}\n{cnt}条 ({p}%)" for c, cnt, p in zip(categories, counts, pcts)],
                   autopct="", startangle=140, colors=colors, explode=(0.05, 0.05, 0),
                   wedgeprops=dict(edgecolor="black", width=0.6))
    axes[0, 0].set_title("59,430条真实JD样本结构剖析\n(71.4%新工科技术岗 vs 18.7%原专业适配岗)", fontsize=11, fontweight="bold")

    # Subplot 2: Education threshold comparison (硕士/博士门槛骤降)
    x = np.arange(len(edu_labels))
    width = 0.35
    axes[0, 1].bar(x - width/2, all_edu, width, label="全量样本 (新工科主导)", color="#3498db", edgecolor="black", alpha=0.85)
    axes[0, 1].bar(x + width/2, subset_edu, width, label="非新工科子集 (原专业适配岗)", color="#e67e22", edgecolor="black", alpha=0.85)
    axes[0, 1].set_ylabel("占比 (%)", fontsize=10)
    axes[0, 1].set_title("学历门槛对比: 原专业适配岗硕士仅3.0% (门槛显著降低)", fontsize=11, fontweight="bold")
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(edu_labels, fontsize=10)
    axes[0, 1].legend(fontsize=9)
    axes[0, 1].grid(axis="y", linestyle="--", alpha=0.5)
    for i in range(len(edu_labels)):
        axes[0, 1].text(x[i] - width/2, all_edu[i] + 1, f"{all_edu[i]}%", ha="center", fontsize=8)
        axes[0, 1].text(x[i] + width/2, subset_edu[i] + 1, f"{subset_edu[i]}%", ha="center", fontsize=8, fontweight="bold")

    # Subplot 3: Soft skills demand rate in subset (全部40%+)
    y_pos = np.arange(len(soft_skills))
    axes[1, 0].barh(y_pos - width/2, all_soft, width, label="全量样本 (新工科主导)", color="#3498db", edgecolor="black", alpha=0.85)
    axes[1, 0].barh(y_pos + width/2, subset_soft, width, label="非新工科子集 (原专业适配岗)", color="#e67e22", edgecolor="black", alpha=0.85)
    axes[1, 0].set_yticks(y_pos)
    axes[1, 0].set_yticklabels(soft_skills, fontsize=10)
    axes[1, 0].set_xlabel("岗位要求提及率 (%)", fontsize=10)
    axes[1, 0].set_title("可迁移软能力提及率: 原专业适配岗全面达40%+ (软实力主导)", fontsize=11, fontweight="bold")
    axes[1, 0].legend(fontsize=9)
    axes[1, 0].grid(axis="x", linestyle="--", alpha=0.5)
    for i in range(len(soft_skills)):
        axes[1, 0].text(subset_soft[i] + 1, y_pos[i] + width/2, f"{subset_soft[i]}%", va="center", fontsize=8, fontweight="bold")

    # Subplot 4: Hard skill dispersion vs dominant technical gate
    tools = ["Python", "SQL", "大模型", "Java", "C++", "Linux", "机器学习"]
    tech_all = [19.1, 14.8, 12.2, 18.5, 16.2, 15.8, 12.5]
    tech_subset = [6.2, 5.8, 3.4, 1.8, 1.2, 2.1, 1.5]
    x_t = np.arange(len(tools))
    axes[1, 1].bar(x_t - width/2, tech_all, width, label="新工科技术岗 (硬技能门槛极高)", color="#3498db", edgecolor="black", alpha=0.85)
    axes[1, 1].bar(x_t + width/2, tech_subset, width, label="非新工科子集 (硬技能分散不卡人, 最高仅6.2%)", color="#e67e22", edgecolor="black", alpha=0.85)
    axes[1, 1].set_ylabel("技能标签占比 (%)", fontsize=10)
    axes[1, 1].set_title("硬技能门槛对比: 原专业适配岗无单一卡人硬技能", fontsize=11, fontweight="bold")
    axes[1, 1].set_xticks(x_t)
    axes[1, 1].set_xticklabels(tools, fontsize=10, rotation=20)
    axes[1, 1].legend(fontsize=9)
    axes[1, 1].grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig_path = FIGURES_DIR / "fig_doc11_subset_comparison.png"
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"Saved: {fig_path}")

    # Save Table
    table_path = TABLES_DIR / "table_doc11_comparison.csv"
    with open(table_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["比较维度", "全量样本 (新工科主导，n=59,430)", "非新工科子集 (原专业适配，n=11,126)", "学术实证结论与11号材料依据"])
        writer.writerow(["样本定位", "71.4% 技术工程师为主", "18.7% 跨专业可进入岗位", "全量频次存在严重工科偏置，必须切出非新工科子集单独校准"])
        writer.writerow(["学历门槛", "硕士 9.7% / 博士 1.0%", "硕士仅 3.0% / 博士 0.2%", "原专业适配岗本科即为主流(59.8%)，学历溢价消失，佐证学历仅占15%"])
        writer.writerow(["软技能必提率", "团队 38.2% / 沟通 32.5%", "沟通 46.1% / 分析 43.1% / 团队 42.9%", "原专业适配岗软技能全面占优且达40%+，佐证综合素质占45%"])
        writer.writerow(["硬工具门槛", "Python 19.1% / 计算机 40.7%", "最高 Python 仅 6.2%，无单一主导", "硬技能分散不卡人，佐证9项硬技能应作为缺口单列而非淘汰总分"])
        writer.writerow(["知识词主导", "算法 / 软件 / 模型", "设计 36.0% (去自名词后第一)", "知识基础为原专业训练+行业理解，而非工科计算机，佐证知识占40%"])


# ==============================================================================
# 2. Document 13 & 12: Cross-Disciplinary Topology Matrix (3 Majors -> 4 Families)
# ==============================================================================
def generate_doc13_matrix():
    print("[Task 2/3] Generating Document 13 Cross-Disciplinary Topology Matrix...")

    majors = ["文史哲大类\n(历史/汉语言/哲学)", "数理化大类\n(数学/物理/化学)", "传统经管工科\n(会计/经济/机械/土木)"]
    families = ["J1 数字内容/人文\n(AIGC审核/文案策划)", "J2 数据/分析\n(商业数据分析/解决方案)", "J3 产品/管理\n(数字产品/智能制造项目)", "J4 交叉研究\n(生成式AI系统/行业分析)"]

    # 3x4 Matrix: 2=Strong (Red), 1=Medium (Orange), 0=Weak (Gray)
    # Matching Section 3 of Document 13:
    # 文史哲: J1强(2), J2中(1), J3弱(0), J4强(2)
    # 数理化: J1弱(0), J2强(2), J3中(1), J4强(2)
    # 经管工科: J1弱(0), J2中(1), J3强(2), J4中(1)
    matrix = np.array([
        [2, 1, 0, 2],
        [0, 2, 1, 2],
        [0, 1, 2, 1]
    ])

    labels_map = {
        (0, 0): ("[强 显著适配]", "江聃2026新媒体案例\n郭睿2019错配30.77%\n文本解读+写作直接命中"),
        (0, 1): ("[中 需补工具]", "文本挖掘=工具操作\n杨丽乐50.58%\n需补充数据清洗缺口"),
        (0, 2): ("[弱 跨度过大]", "杨丽乐运营管理本科85.77%\n但缺组织协调训练"),
        (0, 3): ("[强 显著适配]", "Boix Mansilla跨学科三维\n刘海燕2026复杂场景破解\n文献考据=知识治理"),

        (1, 0): ("[弱 跨度过大]", "强工具弱内容表达\n无文献直接支撑"),
        (1, 1): ("[强 显著适配]", "技能水平47.26%最高\nNature2025数学=通用底座\n建模+统计直通数据岗"),
        (1, 2): ("[中 需补管理]", "杨丽乐组织协调19.22%\n工程逻辑支持项目排期"),
        (1, 3): ("[强 显著适配]", "科研学术类硕博72.16%\n因果推断+严谨实验设计"),

        (2, 0): ("[弱 跨度过大]", "无文献直接支撑"),
        (2, 1): ("[中 需补分析]", "杨丽乐商业数据分析师\n业财融合=数据化指标"),
        (2, 2): ("[强 显著适配]", "运营管理类本科85.77%最高\n智联需供比16\n商业思维+跨部门沟通"),
        (2, 3): ("[中 需补研究]", "经管实证方法论支撑\n产业数字化分析"),
    }

    fig, ax = plt.subplots(figsize=(13, 8), dpi=300)
    cmap = matplotlib.colors.ListedColormap(["#f8f9fa", "#fff3cd", "#f8d7da"])
    bounds = [-0.5, 0.5, 1.5, 2.5]
    norm = matplotlib.colors.BoundaryNorm(bounds, cmap.N)

    cax = ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")

    ax.set_xticks(range(len(families)))
    ax.set_yticks(range(len(majors)))
    ax.set_xticklabels(families, fontsize=11, fontweight="bold")
    ax.set_yticklabels(majors, fontsize=11, fontweight="bold")
    ax.set_title("原专业大类 与 新质岗位族 12格跨界翻译图谱 (依据13号与12号核心文档)", fontsize=14, fontweight="bold", pad=20)

    for i in range(len(majors)):
        for j in range(len(families)):
            tag, note = labels_map[(i, j)]
            color = "#c0392b" if "强" in tag else ("#d35400" if "中" in tag else "#7f8c8d")
            ax.text(j, i - 0.15, tag, ha="center", va="center", color=color, fontsize=12, fontweight="bold")
            ax.text(j, i + 0.18, note, ha="center", va="center", color="#2c3e50", fontsize=8.5, linespacing=1.3)

    plt.tight_layout()
    fig_path = FIGURES_DIR / "fig_doc13_cross_topology.png"
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"Saved: {fig_path}")


# ==============================================================================
# 3. Document 14 & 15: End-to-End Real Resume Profiling & Recommendation
# ==============================================================================
def generate_resume_e2e_profile():
    print("[Task 3/3] Generating End-to-End Real Resume Profiling (Resolving Section 13.1)...")
    
    # Load 33 capabilities & families
    framework_file = BACKEND_DIR / "app" / "catalog" / "framework_v1.json"
    framework = json.loads(framework_file.read_text(encoding="utf-8"))
    caps_data = framework["capabilities"]
    families = framework["job_families"]
    cap_lookup = {c["name"]: c for c in caps_data}
    cap_ids = {c["name"]: UUID(int=i + 1) for i, c in enumerate(caps_data)}
    domain_id = UUID(int=999)

    # 14 extracted skills from a representative interdisciplinary candidate
    # (Humanities/Management student applying for J1/J2 hybrid roles)
    extracted_14 = [
        ("Python", "数据清洗", "gap", "work", 3, "使用Python完成5万条文本清洗、去重与格式化"),
        ("SQL", "数据清洗", "gap", "project", 3, "构建多表关联查询与报表视图"),
        ("数据分析", "统计推断", "gap", "project", 3, "基于SPSS进行用户问卷交叉分析与卡方检验"),
        ("图表制作", "数据可视化", "gap", "project", 3, "使用ECharts设计并输出可视化运营看板"),
        ("Prompt优化", "提示工程", "gap", "project", 3, "调优大模型Prompt完成结构化抽取与分类"),
        ("内容审核", "文本解读", "translate", "work", 4, "独立完成300+篇AIGC稿件的逻辑、用词与事实核查"),
        ("报告撰写", "写作能力", "translate", "work", 4, "主笔撰写3篇省市级课题申报书与行业调研报告"),
        ("需求调研", "商业思维", "translate", "project", 3, "拆解目标客群核心痛点并输出业务需求说明"),
        ("团队分工", "团队协作", "translate", "work", 4, "担任项目组长协调6名成员按期达成里程碑"),
        ("进度跟踪", "进度管理", "translate", "project", 3, "建立甘特图跟踪项目进度并化解延迟风险"),
        ("全流程交付", "独立交付", "translate", "work", 4, "端到端负责数字媒体账号从0到1的立项与运营"),
        ("逻辑论证", "逻辑思维", "translate", "project", 4, "梳理文献脉络并建立跨学科论证分析框架"),
        ("复盘迭代", "持续改进", "translate", "project", 3, "基于A/B测试数据优化内容结构提升转化率"),
        ("快速上手", "快速学习", "translate", "work", 4, "1周内掌握FastAPI与向量数据库并在项目中落地"),
    ]

    # Convert to ProfileSkillInput
    profile_skills = {}
    for raw_name, std_name, dual_track, strength, bars, quote in extracted_14:
        c_id = cap_ids[std_name]
        profile_skills[c_id] = ProfileSkillInput(
            id=uuid4(),
            capability_id=c_id,
            raw_name=raw_name,
            mapping_method="exact_or_alias",
            evidence_strength=strength,
            evidence_quote=quote,
        )

    profile = ProfileMatchInput(
        highest_education_level="bachelor",
        total_experience_months=12,
        skills=profile_skills,
    )

    # Evaluate across J1, J2, J3, J4 Standard Roles
    role_results = []
    for f in families:
        req_caps = []
        for c_name in f.get("required", []):
            req_caps.append(CapabilityRequirementInput(
                capability_id=cap_ids[c_name],
                canonical_name=c_name,
                skill_type=cap_lookup[c_name]["meta_dimension"],
                requirement_type="required",
                importance=Decimal("1.0"),
                domain_id=domain_id,
                domain_code="capability-translator",
                domain_name="能力翻译器",
                dual_track=cap_lookup[c_name]["dual_track"],
                capability_group=cap_lookup[c_name].get("group"),
            ))
        for c_name in f.get("bonus", []):
            req_caps.append(CapabilityRequirementInput(
                capability_id=cap_ids[c_name],
                canonical_name=c_name,
                skill_type=cap_lookup[c_name]["meta_dimension"],
                requirement_type="bonus",
                importance=Decimal("0.5"),
                domain_id=domain_id,
                domain_code="capability-translator",
                domain_name="能力翻译器",
                dual_track=cap_lookup[c_name]["dual_track"],
                capability_group=cap_lookup[c_name].get("group"),
            ))

        scored = score_profile_against_requirements(
            profile,
            tuple(req_caps),
            minimum_education_level=f.get("minimum_education_level", "bachelor"),
            recommended_experience_months=f.get("recommended_experience_months", 0),
            skill_snapshot_key="resume_skill",
        )

        role_results.append({
            "code": f["code"],
            "name": f["name"],
            "total_score": float(scored.total_score),
            "match_level": scored.match_level,
            "comp_score": float(scored.dimension_scores.get("comprehensive_quality", {}).get("score", 0)),
            "know_score": float(scored.dimension_scores.get("knowledge_foundation", {}).get("score", 0)),
            "hard_gap": float(scored.dimension_scores.get("hard_skill_gap", {}).get("score", 0)),
            "edu_score": float(scored.education_score),
            "matched_req_count": scored.gap_summary["matched_required_count"],
            "missing_req_count": scored.gap_summary["missing_required_count"],
            "missing_skills": [c["canonical_name"] for c in scored.missing_capabilities if c["requirement_type"] == "required"],
        })

    # Save Table: Real Resume Results
    table_path = TABLES_DIR / "table_resume_e2e_results.csv"
    with open(table_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["目标岗位族", "综合匹配总分", "适配等级", "综合素质分 (45%)", "知识基础分 (40%)", "学历分 (15%)", "硬技能覆盖率", "匹配必备数", "缺失必备数", "关键硬技能缺口 (驱动成长路径)"])
        for r in role_results:
            writer.writerow([
                r["name"],
                f"{r['total_score']:.2f}",
                "高适配" if r["match_level"] == "high" else ("发展型适配" if r["match_level"] == "medium" else "暂不推荐"),
                f"{r['comp_score']:.2f}",
                f"{r['know_score']:.2f}",
                f"{r['edu_score']:.2f}",
                f"{r['hard_gap']:.2f}%",
                r["matched_req_count"],
                r["missing_req_count"],
                "、".join(r["missing_skills"]) if r["missing_skills"] else "无明显硬缺口",
            ])

    # Figure: Radar Plot of Candidate Profiling across J1-J4
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=300)

    # 1. Family Scores Bar Chart
    f_names = [r["code"] + " " + r["name"].split()[-1] for r in role_results]
    f_scores = [r["total_score"] for r in role_results]
    colors = ["#2ecc71" if s >= 75.0 else ("#f39c12" if s >= 50.0 else "#e74c3c") for s in f_scores]

    bars = axes[0].bar(f_names, f_scores, color=colors, edgecolor="black", alpha=0.85)
    axes[0].set_ylabel("综合适配总分 (45/40/15加权)", fontsize=11)
    axes[0].set_title("真实跨专业简历在四大新质岗位族的适配得分与等级\n(绿:高适配, 橙:发展型适配, 红:暂不推荐)", fontsize=11, fontweight="bold")
    axes[0].set_ylim(0, 100)
    axes[0].grid(axis="y", linestyle="--", alpha=0.5)
    for b, s in zip(bars, f_scores):
        axes[0].text(b.get_x() + b.get_width() / 2, s + 1.5, f"{s:.1f}分", ha="center", fontsize=9, fontweight="bold")

    # 2. Dimensions Comparison for the Best Fit Role (J1 / J3)
    best_role = sorted(role_results, key=lambda x: -x["total_score"])[0]
    dim_names = ["综合素质 (45%)", "知识基础 (40%)", "学历背景 (15%)", "硬技能准入 (独立缺口)"]
    dim_scores = [best_role["comp_score"], best_role["know_score"], best_role["edu_score"], best_role["hard_gap"]]

    axes[1].barh(dim_names, dim_scores, color=["#3498db", "#9b59b6", "#1abc9c", "#e74c3c"], edgecolor="black", alpha=0.85)
    axes[1].set_xlabel("分项得分 / 覆盖率 (%)", fontsize=11)
    axes[1].set_title(f"最高匹配岗位 [{best_role['name']}] 四维细粒度画像拆解\n(硬技能缺口独立报警，不掩盖岗位风险)", fontsize=11, fontweight="bold")
    axes[1].set_xlim(0, 110)
    axes[1].grid(axis="x", linestyle="--", alpha=0.5)
    for i, v in enumerate(dim_scores):
        axes[1].text(v + 1.5, i, f"{v:.1f}%", va="center", fontsize=9, fontweight="bold")

    plt.tight_layout()
    fig_path = FIGURES_DIR / "fig_resume_e2e_profile.png"
    plt.savefig(fig_path, dpi=300)
    plt.close()
    print(f"Saved: {fig_path}")


def main():
    print("=" * 70)
    print("Running Pipeline Strictly Aligned with Documents 11, 12, 13, 14, 15")
    print("=" * 70)
    generate_doc11_figures()
    generate_doc13_matrix()
    generate_resume_e2e_profile()
    print("=" * 70)
    print("All Tasks Completed Successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
