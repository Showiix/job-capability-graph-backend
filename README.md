# 岗位能力图谱系统后端

面向比赛展示与团队内部真实使用的岗位能力图谱后端。当前已形成四段可运行闭环：

- Batch A：三角色内部账号、Session/CSRF、安全文件读取、Processing Run 生命周期和依赖健康诊断。
- Batch B：市场 JD 批量上传、来源 Adapter、Raw/Normalized 双层数据、质量警告、重新处理，以及技能/岗位 Catalog 骨架导入。
- Batch C：标准技能库精确映射、候选技能组合发现、可追溯 Evidence、Discovery Run 和 admin/hr 查询 API。
- Batch D：候选岗位定义提案、HR/admin 人工修改与确认、不采纳、不可变审核历史和审计记录。

本仓库只包含后端。当前没有公开注册接口，也没有脱离业务资源的通用文件上传接口。

## 技术栈

- Python 3.12、FastAPI、SQLAlchemy 2、Alembic
- PostgreSQL 16 + pgvector：业务事实与任务状态唯一真相源
- Neo4j 5 Community：后续只接收审核通过的正式图谱
- Redis 7 + Celery：异步任务投递和周期维护
- 本地 Docker Volume：内部演示文件存储
- Docker Compose：单机内部部署

## 快速启动

运行前需要安装 Docker Desktop，并确保 Docker daemon 已启动。

```bash
cp .env.example .env
docker compose up -d postgres redis neo4j
docker compose run --rm migrate
docker compose run --rm api uv run python scripts/create_user.py \
  --username admin --display-name 系统管理员 --role admin
docker compose up -d api worker scheduler
curl http://127.0.0.1:8000/health/ready
```

创建首个管理员时，命令行会通过 `getpass` 要求输入并确认密码；密码不会回显。首个账号必须是 `admin`，后续 applicant、hr、admin 账号由管理员 API 创建和维护。

启动成功后：

- OpenAPI / Swagger UI：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>
- API 根前缀：`/api/v1`

在尚未单独启动 Algorithm Service 时，Ready 响应中的 `algorithm_service` 会是 `degraded`；这是允许的降级状态。PostgreSQL、Redis、Neo4j 和文件卷四个必需依赖必须全部为 `ok`。

示例：

```json
{
  "status": "ready",
  "dependencies": {
    "postgresql": "ok",
    "redis": "ok",
    "neo4j": "ok",
    "file_volume": "ok",
    "algorithm_service": "degraded"
  }
}
```

## 当前 API 范围

### 认证与账号

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `GET /api/v1/auth/me`
- `POST /api/v1/admin/users`
- `GET /api/v1/admin/users`
- `GET /api/v1/admin/users/{user_id}`
- `PATCH /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/reset-password`

认证使用 HttpOnly 不透明 Session Cookie。所有登录后的写接口还需要把 `csrf` Cookie 的值放入 `X-CSRF-Token` Header。系统不提供公开注册。

### 文件受控读取

- `GET /api/v1/files/{file_id}`
- `GET /api/v1/files/{file_id}/content`
- `GET /api/v1/files/{file_id}/download`

Batch A 只提供可见性校验后的读取、Range 预览、附件下载和访问审计。业务上传入口将在对应的 Import、Resume 或 Recruitment 模块中实现，不提供无业务归属的普通上传 API。

### Processing Run

- `GET /api/v1/processing-runs`
- `GET /api/v1/processing-runs/{run_id}`
- `GET /api/v1/processing-runs/{run_id}/errors`
- `GET /api/v1/processing-runs/{run_id}/result`
- `POST /api/v1/processing-runs/{run_id}/retry`
- `POST /api/v1/processing-runs/{run_id}/cancel`

普通用户只能看到 `owner_scope_type=user` 且属于自己的任务；管理员可以查看全局任务。失败重试会创建新 Run，不会把旧 Run 改回 pending。

### 市场 JD 数据中心

- `POST /api/v1/imports`
- `GET /api/v1/imports`
- `GET /api/v1/imports/{batch_id}`
- `GET /api/v1/imports/{batch_id}/rows`
- `GET /api/v1/imports/{batch_id}/warnings`
- `POST /api/v1/imports/{batch_id}/reprocess`
- `POST /api/v1/imports/{batch_id}/archive`

导入接口仅管理员可用，支持 `.csv`、`.tsv`、`.txt` 和 `.json`，单文件默认不超过 50 MB、10 万行。当前内置 `standard_v1`、`liepin_v1`、`zhilian_v1` 三个 Adapter。原始 JD 行只追加，重新处理只新增 Normalized 版本；归档不会删除文件或数据库记录。

默认行查询不会返回完整原始载荷和正文。需要排查单行时显式使用：

```text
GET /api/v1/imports/{batch_id}/rows?include=raw_payload,full_text
```

### Catalog 骨架

- `POST /api/v1/catalog/imports`
- `GET /api/v1/catalog/imports`
- `GET /api/v1/catalog/imports/{import_id}`
- `GET /api/v1/catalog/versions`
- `GET /api/v1/catalog/versions/current`
- `GET /api/v1/catalog/domains`
- `GET /api/v1/catalog/capabilities`
- `GET /api/v1/catalog/job-roles`

Catalog 文件支持 JSON/CSV/TSV，导入类型为 `capability` 或 `job_role`。`validate_only` 只记录逐行校验结果；`apply` 会创建 draft 版本。来源为 `model`、`llm` 或 `algorithm` 的条目始终写成 `candidate`，不能直接成为 active/published 正式知识。普通登录用户只看到当前 published 版本中的 active 条目；管理员可显式查询 draft/candidate。

### 候选技能组合发现

- `POST /api/v1/discovery-runs`
- `GET /api/v1/discovery-runs`
- `GET /api/v1/discovery-runs/{run_id}`
- `GET /api/v1/discovery-candidates`
- `GET /api/v1/discovery-candidates/{candidate_id}`
- `GET /api/v1/discovery-candidates/{candidate_id}/evidence`

创建 Discovery Run 仅限 `admin`；`admin` 和 `hr` 可以查询运行记录、候选和证据；`applicant` 不可访问。运行会复用已导入的市场 JD，先将 `tech_tags` 精确映射到 Catalog 中的 active Capability，再生成可解释的两技能共现候选。

前置条件：先通过 Catalog 导入并维护 active Capability。只有 active Capability 和 active Alias 会参与映射；未映射标签只写入 `JobSkillCandidate`，不会自动创建正式技能，也不会写入 Neo4j。

创建运行：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"batch_ids\": [\"${BATCH_ID}\"],
    \"minimum_support_jobs\": 2,
    \"minimum_source_count\": 1,
    \"minimum_quality_score\": 60,
    \"maximum_candidates\": 50
  }" \
  http://127.0.0.1:8000/api/v1/discovery-runs
```

返回的 `run_id` 是对应 Processing Run 的 ID，可通过 `/api/v1/processing-runs/{run_id}` 轮询任务状态；返回的 `resource_id` 是 Discovery Run 资源 ID，可通过 `/api/v1/discovery-runs/{resource_id}` 查询摘要。运行完成后查询候选：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/discovery-candidates?discovery_run_id=${DISCOVERY_RUN_ID}"
```

当前结果统一称为“候选技能组合”，不代表已经确认的长期市场趋势。第一版使用确定性的 pair co-occurrence baseline，暂不包括 Embedding/pgvector 聚类、Algorithm Service 语义聚类、LLM 岗位定义、时间趋势证明、HR Feedback、Neo4j 正式图谱发布和三技能及以上频繁项集。

### 候选岗位审核

- `POST /api/v1/review-proposals`
- `GET /api/v1/review-proposals`
- `GET /api/v1/review-proposals/{proposal_id}`
- `POST /api/v1/review-proposals/{proposal_id}/decisions`

`admin` 和 `hr` 可以把候选技能组合转换为结构化岗位定义提案，并执行 `approve`、`revise` 或 `reject`；`applicant` 不可访问。写接口需要 CSRF Token。

创建提案：

```bash
CANDIDATE_ID='替换为 discovery candidate id'

curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"candidate_id\": \"${CANDIDATE_ID}\"}" \
  http://127.0.0.1:8000/api/v1/review-proposals
```

提案会自动锚定原 Candidate 的技能和 Evidence Summary，并生成可人工编辑的岗位定义骨架。第一版不会凭空编写岗位职责和行业场景，这两个字段初始为空。

修改岗位定义后保留待审状态：

```bash
PROPOSAL_ID='替换为 review proposal id'

curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "decision": "revise",
    "after_payload": {
      "role_name": "AI 自动化测试工程师",
      "core_responsibilities": ["建设 AI 产品自动化测试体系"],
      "required_capability_ids": ["替换为技能 UUID", "替换为技能 UUID"],
      "bonus_capability_ids": [],
      "industry_scenarios": ["AI 产品质量保障"],
      "generation_source": "human_revision",
      "definition_status": "reviewed"
    },
    "comment": "补充岗位名称和职责"
  }' \
  "http://127.0.0.1:8000/api/v1/review-proposals/${PROPOSAL_ID}/decisions"
```

直接确认当前定义：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"approve","comment":"确认采纳"}' \
  "http://127.0.0.1:8000/api/v1/review-proposals/${PROPOSAL_ID}/decisions"
```

`approve` 只表示审核通过并获得后续发布资格，不会创建 active JobRole，不会创建正式 Catalog Version，也不会写入 Neo4j。每次决定都保存 before/after Payload、审核人、时间和意见；`approved/rejected` 是只读终态。

## 市场 JD 导入验收示例

先登录管理员账号并从 Cookie Jar 取出 CSRF Token：

```bash
curl -sS -c /tmp/job-graph-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"替换为管理员密码"}' \
  http://127.0.0.1:8000/api/v1/auth/login

CSRF_TOKEN="$(awk '$6 == "csrf" {print $7}' /tmp/job-graph-cookies.txt)"
```

上传仓库中的猎聘真实样例。接口返回 `resource_id`（批次 ID）、`run_id` 和任务查询地址，Worker 会异步完成解析和标准化：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Idempotency-Key: demo-liepin-20260806' \
  -F source_code=liepin \
  -F collected_at=2026-08-06T00:00:00Z \
  -F source_format=tsv \
  -F schema_version=liepin_v1 \
  -F file=@backend/tests/fixtures/liepin_sample.tsv \
  http://127.0.0.1:8000/api/v1/imports
```

将返回的 `resource_id` 赋给 `BATCH_ID` 后查询处理结果：

```bash
BATCH_ID='替换为 resource_id'

curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/imports/${BATCH_ID}"
curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/imports/${BATCH_ID}/warnings"
curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/imports/${BATCH_ID}/rows?page_size=20"
```

智联样例使用相同命令，把 `source_code`、`schema_version` 和文件分别替换为 `zhilian`、`zhilian_v1`、`backend/tests/fixtures/zhilian_sample.tsv`。

Catalog 建议先校验、确认逐行错误后再应用：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -F import_type=capability \
  -F schema_version=catalog_v1 \
  -F mode=validate_only \
  -F file=@catalog.json \
  http://127.0.0.1:8000/api/v1/catalog/imports
```

### 系统诊断

- `GET /health/live`：只证明 API 进程存活，不探测依赖
- `GET /health/ready`：公开、脱敏的依赖状态
- `GET /api/v1/admin/system/dependencies`：管理员依赖延迟、任务积压和队列诊断
- `GET /api/v1/admin/system/versions`：管理员查看 API 与数据库版本

## 常用运维命令

查看服务状态和日志：

```bash
docker compose ps
docker compose logs -f api worker scheduler
```

应用数据库 Migration：

```bash
docker compose run --rm migrate
```

停止服务但保留 PostgreSQL、Neo4j 和文件卷数据：

```bash
docker compose down
```

再次执行 `docker compose up -d api worker scheduler` 时会继续使用原有命名卷。只有明确需要清空本地演示数据时才执行下面的命令；它会删除数据库、图数据库和文件卷，无法通过普通重启恢复：

```bash
docker compose down -v
```

## 开发与验收

本地测试依赖应迁移到 `0008`。创建测试库并应用 Migration：

```bash
docker compose up -d postgres
docker compose exec postgres createdb -U job_graph job_graph_test
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  migrate
```

如果 `job_graph_test` 已存在，`createdb` 会提示已存在，可直接继续。完整质量门禁：

```bash
docker compose config -q
docker compose run --rm api uv run ruff check .
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  api uv run pytest -q
git diff --check
```

真实样例专项验收：

```bash
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  api uv run pytest tests/test_import_api.py -q -k real_market_sample
```

也可以在 `backend/` 目录使用本地 `uv` 环境运行：

```bash
uv sync --frozen
uv run ruff check .
uv run pytest -q
```

## 配置与安全边界

- `.env` 已被 Git 忽略；不要提交真实密码、Session Secret 或外部服务凭证。
- `SESSION_SECRET` 至少 32 个字符，内部部署建议使用随机值。
- `APP_ENV=internal` 时 Session 与 CSRF Cookie 自动启用 `Secure`。
- Session、CSRF Token 和密码只保存 Hash；API 不返回密码或 Token Hash。
- 文件路径始终限制在 `FILE_STORAGE_ROOT` 内，数据库中的路径键不能逃逸根目录。
- Neo4j 当前只做连接检查，不接收导入数据，也不写入未经审核的算法或大模型候选知识。

## 设计文档

- [后端技术架构详细设计](./outputs/岗位能力图谱系统_后端技术架构详细设计.md)
- [数据库与 API 详细设计](./outputs/岗位能力图谱系统_数据库与API详细设计.md)
- [Batch A：后端基础闭环实施计划](./docs/superpowers/plans/2026-08-06-backend-foundation.md)
- [Batch B：市场 JD 数据中心实施计划](./docs/superpowers/plans/2026-08-06-market-jd-center.md)
- [Batch C：候选技能组合发现实施计划](./docs/superpowers/plans/2026-08-06-candidate-discovery.md)
- [Batch D：候选岗位审核实施计划](./docs/superpowers/plans/2026-08-06-candidate-review.md)

当前 Batch B/C/D 明确不包含爬虫管理、定时调度、算法/LLM 抽取、语义聚类和 Neo4j 发布。审核批准的提案仍然是 PostgreSQL 中的候选事实，后续只能通过正式 Catalog/Graph Version 发布接入，不能直接写图。
