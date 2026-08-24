# 数据说明

`merged_data/` 是本项目使用的 JD 原始数据，按平台拆分：

- `boss/`
- `job51/`
- `liepin/`
- `zhilian/`

当前整理版包含 338 个 CSV、59,430 条 JD，知识图谱生成脚本会将同名岗位跨平台聚合为 112 个岗位类别。

字段说明：

```text
job_name             职位名称
company_name         公司名称
salary               薪资
work_area            工作区域
city                 城市
education            学历要求
work_year            经验要求
issue_date           发布日期
source               数据来源
skill_requirements   技能/任职要求文本
tech_tags            技术标签
job_url              原始链接
```
