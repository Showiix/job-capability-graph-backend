# 多源异构数据驱动岗位能力图谱系统

本目录是 GitHub 上传整理版，已经按模块拆分为前端、后端、知识图谱和数据四个部分。已排除 `node_modules`、`dist`、`.env`、`.git`、缓存文件、抓站参考素材、Figma 临时文件和交接文档。

## 目录结构

```text
.
├── frontend/          # 前端应用，Vite + React + Three.js
├── backend/           # 后端 API，FastAPI + PostgreSQL/Redis/Neo4j 配置
├── knowledge-graph/   # JD 图谱生成脚本、图谱 JSON 产物和旧版图谱产物
└── data/              # 原始 JD CSV 数据，按招聘平台拆分
```

## 前端

位置：`frontend/`

主要功能：

- Apollo / 21hrs 风格首页和页面壳
- 3D 岗位-技能知识图谱
- 简历评估与 HR 工作台页面
- 前端静态兜底图谱数据：`frontend/public/jd_graph_data.json`

启动：

```bash
cd frontend
npm install
npm run dev
```

构建：

```bash
cd frontend
npm run build
```

## 后端

位置：`backend/`

后端保留原项目结构：

```text
backend/
├── README.md
├── compose.yaml
├── .env.example
└── backend/
    ├── app/
    ├── scripts/
    ├── tests/
    ├── pyproject.toml
    └── uv.lock
```

注意：

- `.env` 已排除，不要上传真实密钥。
- 需要复制 `.env.example` 为 `.env` 后再填写数据库、Redis、Neo4j 和 LLM 配置。
- 当前 JD 图谱静态接口在 `backend/backend/app/graph/`。

## 知识图谱

位置：`knowledge-graph/`

内容：

- `scripts/load_jd_data.py`：从 `data/merged_data` 聚合 JD CSV，生成岗位-技能图谱 JSON。
- `generated/jd_graph_data.json`：当前已生成的 3D 图谱数据。
- `legacy-artifacts/`：原“知识图谱后端”目录中的旧版 JSON 产物和接口说明。

重新生成图谱：

```bash
python3 knowledge-graph/scripts/load_jd_data.py
```

脚本会生成并同步：

- `backend/backend/app/graph/jd_graph_data.json`
- `frontend/public/jd_graph_data.json`

默认读取 `data/merged_data`。如需改路径，可设置环境变量：

```bash
JD_MERGED_DATA_DIR=/path/to/merged_data python3 knowledge-graph/scripts/load_jd_data.py
```

## 数据

位置：`data/merged_data/`

数据概况：

- 4 个平台目录：`boss`、`job51`、`liepin`、`zhilian`
- 338 个 CSV
- 59,430 条 JD
- 112 个岗位类别

CSV 字段：

```text
job_name, company_name, salary, work_area, city, education,
work_year, issue_date, source, skill_requirements, tech_tags, job_url
```

## 上传前检查

建议在本目录执行：

```bash
find . -name node_modules -o -name dist -o -name .env -o -name .DS_Store
rg "sk-" . -g '!data/merged_data/**'
```

正常情况下不应该出现真实密钥、依赖目录或构建产物。
