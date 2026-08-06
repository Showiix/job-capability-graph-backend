# Candidate Review Implementation Plan

> **Execution rule:** Follow TDD. Add the failing behavior test first, run it, then write the minimum production code required to pass. Commit and push each completed task independently.

**Goal:** 在 Batch C 的候选技能组合之上补齐比赛演示所需的人工审核闭环，让 `admin/hr` 能把候选转换为结构化岗位定义提案，并执行确认采纳、编辑后保留或不采纳，同时保存完整审核历史。

**Architecture:** 延续 FastAPI 模块化单体和 PostgreSQL 唯一事实源。审核提案与决定只写 PostgreSQL；批准表示“可以进入后续 Catalog/Graph 发布阶段”，不直接创建 active JobRole、不写 Neo4j。第一版岗位定义由候选技能组合确定性生成骨架，人工可以编辑；LLM 后续只需替换骨架生成步骤。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL、pytest、Ruff。

---

## 1. 范围

### 1.1 本批实现

- 从 `SkillCombinationCandidate` 创建唯一的岗位定义审核提案。
- 自动生成可编辑的结构化定义骨架：
  - 岗位名称
  - 核心职责
  - 必备技能 ID
  - 加分技能 ID
  - 典型行业应用场景
  - 生成来源和候选声明
- `admin/hr` 查询审核列表、详情和历史决定。
- `admin/hr` 执行：
  - `approve`：确认当前定义或带编辑后确认。
  - `revise`：保存修改后的定义，保持待处理。
  - `reject`：不采纳，要求填写理由。
- 保存每次决定的 before/after 快照、审核人、时间和意见。
- 写入现有 `audit_logs`。
- 数据库约束保护唯一性、状态、分数和 JSON 结构。

### 1.2 明确不做

- 不调用 LLM 或 Algorithm Service。
- 不自动生成长篇职责文本；第一版职责和行业场景允许为空，等待人工补充。
- 不创建或激活正式 `JobRole`。
- 不创建 Catalog Version。
- 不发布 Neo4j。
- 不实现多人会签、审批流编排、评论线程或消息通知。
- 不引入 LangGraph、工作流引擎或新依赖。

### 1.3 业务边界

```text
SkillCombinationCandidate
  -> ReviewProposal(pending)
  -> revise* | approve | reject

approve
  -> 仅获得后续发布资格
  -> 不等于 active JobRole
  -> 不等于 Neo4j 已发布节点
```

---

## 2. 数据模型

### 2.1 graph_change_candidates

第一版只承载“候选技能组合提出一个新岗位定义”这一种变化，不为了未来类型提前设计通用图 DSL。

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| id | uuid | 主键 |
| source_candidate_id | uuid nullable | FK `skill_combination_candidates.id`，`ON DELETE SET NULL` |
| change_type | varchar(40) | 第一版固定 `create_job_role` |
| proposed_payload | jsonb | 当前结构化岗位定义，必须为 object |
| source_snapshot | jsonb | 创建提案时的候选名称、技能和分数快照 |
| evidence_summary | jsonb | 支持岗位数、来源数、公司数和证据数 |
| confidence | numeric(5,4) | `[0,1]` |
| review_status | varchar(30) | `pending/needs_revision/approved/rejected` |
| created_by_user_id | uuid | 创建人 |
| reviewed_by_user_id | uuid nullable | 最近一次决定人 |
| reviewed_at | timestamptz nullable | 最近一次决定时间 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

数据库约束：

- 同一个非空 `source_candidate_id` 只能有一个提案。
- `change_type=create_job_role`。
- `confidence BETWEEN 0 AND 1`。
- 三个 JSON 快照字段必须是 object。
- 按 `review_status, created_at DESC` 建索引。

`source_candidate_id` 使用 `ON DELETE SET NULL`，因为 Discovery Run 重试可能替换候选行；审核提案必须依靠 `source_snapshot` 保留历史，不跟随候选删除。

### 2.2 review_decisions

| 字段 | 类型 | 约束/说明 |
| --- | --- | --- |
| id | uuid | 主键 |
| graph_change_candidate_id | uuid | FK，提案删除时级联 |
| reviewer_user_id | uuid | 审核人 |
| decision | varchar(20) | `approve/revise/reject` |
| before_payload | jsonb | 决定前结构化定义快照 |
| after_payload | jsonb | 决定后结构化定义快照；reject 时与 before 相同 |
| comment | text nullable | 意见；reject/revise 由 API 强制非空 |
| created_at | timestamptz | 决定时间 |

审核历史只追加，不提供修改和删除 API。

### 2.3 状态流转

| 当前状态 | approve | revise | reject |
| --- | --- | --- | --- |
| pending | approved | needs_revision | rejected |
| needs_revision | approved | needs_revision | rejected |
| approved | 409 | 409 | 409 |
| rejected | 409 | 409 | 409 |

候选组合状态：

- 创建提案后：`proposed_for_review`
- revise 后：`feedback_collected`
- reject 后：`rejected`
- approve 后：保持 `proposed_for_review`；正式发布状态由后续 Graph/Catalog 批次负责。

---

## 3. 岗位定义 Payload

```json
{
  "role_name": "Python + 自动化测试",
  "core_responsibilities": [],
  "required_capability_ids": ["uuid", "uuid"],
  "bonus_capability_ids": [],
  "industry_scenarios": [],
  "generation_source": "deterministic_baseline",
  "definition_status": "needs_enrichment",
  "disclaimer": "该定义是待审核岗位候选，不代表已发布的标准岗位"
}
```

校验规则：

- `role_name`：1 到 200 字符，去除首尾空白。
- `core_responsibilities`：最多 20 项，每项 1 到 500 字符。
- `required_capability_ids`：2 到 20 个、不可重复。
- `bonus_capability_ids`：最多 20 个、不可重复。
- 必备技能和加分技能不可重叠。
- 所有技能 ID 必须存在且状态为 active。
- `industry_scenarios`：最多 20 项，每项 1 到 300 字符。
- 人工提交后 `generation_source=human_revision`。
- 第一版允许职责和行业场景为空，避免伪造 LLM 输出。

---

## 4. API

所有接口仅允许 `admin/hr`，需要登录；写接口还需要 CSRF。

### 4.1 创建提案

```http
POST /api/v1/review-proposals
Content-Type: application/json

{
  "candidate_id": "uuid"
}
```

行为：

- 候选必须存在。
- 候选必须至少有 2 个 active Capability 和 1 条 Evidence。
- 自动生成确定性岗位定义骨架。
- 重复创建返回既有提案，不新增第二条。
- 候选状态更新为 `proposed_for_review`。

### 4.2 查询列表与详情

```http
GET /api/v1/review-proposals?status=pending&page=1&page_size=20
GET /api/v1/review-proposals/{proposal_id}
```

详情返回：

- 当前岗位定义
- 候选分数和来源快照
- Evidence Summary
- 审核状态
- 最近审核人和时间
- 全部 Review Decision 历史

不返回原始 JD 正文和 `raw_payload`。

### 4.3 提交决定

```http
POST /api/v1/review-proposals/{proposal_id}/decisions
Content-Type: application/json

{
  "decision": "revise",
  "after_payload": {
    "role_name": "AI 自动化测试工程师",
    "core_responsibilities": ["建设 AI 产品自动化测试体系"],
    "required_capability_ids": ["uuid", "uuid"],
    "bonus_capability_ids": [],
    "industry_scenarios": ["AI 产品质量保障"],
    "generation_source": "human_revision",
    "definition_status": "reviewed",
    "disclaimer": "该定义是待审核岗位候选，不代表已发布的标准岗位"
  },
  "comment": "岗位名称和职责需要更明确"
}
```

规则：

- `revise`：`after_payload` 和 `comment` 必填。
- `reject`：`comment` 必填，`after_payload` 不需要。
- `approve`：可以不传 `after_payload`；传入时按“编辑后确认”处理。
- `approved/rejected` 为终态，再提交返回 409。

### 4.4 错误码

```text
REVIEW_PROPOSAL_NOT_FOUND
REVIEW_SOURCE_CANDIDATE_NOT_FOUND
REVIEW_PROPOSAL_SOURCE_INVALID
REVIEW_PROPOSAL_ALREADY_FINAL
REVIEW_DECISION_COMMENT_REQUIRED
REVIEW_DEFINITION_REQUIRED
REVIEW_CAPABILITY_INVALID
REVIEW_CAPABILITY_OVERLAP
```

---

## 5. 文件范围

```text
backend/app/reviews/__init__.py
backend/app/reviews/models.py
backend/app/reviews/schemas.py
backend/app/reviews/service.py
backend/app/reviews/router.py
backend/app/api/router.py
backend/alembic/env.py
backend/alembic/versions/0008_create_review_tables.py
backend/tests/test_review_database_constraints.py
backend/tests/test_review_service.py
backend/tests/test_review_api.py
README.md
docs/superpowers/plans/2026-08-06-candidate-review.md
```

不修改 Discovery 挖掘算法，不增加依赖。

---

## Task 1: 计划与隔离分支

- [x] **Step 1: 创建 `codex/candidate-review` worktree**
- [x] **Step 2: 运行基线测试和 Ruff**
- [x] **Step 3: 提交并推送本计划**

```bash
git add docs/superpowers/plans/2026-08-06-candidate-review.md
git commit -m "docs: plan candidate review workflow"
git push -u origin codex/candidate-review
```

---

## Task 2: 审核模型与 Migration 0008

- [x] **Step 1: 写数据库 RED 测试**

覆盖：

- 同一候选只能创建一个提案。
- 非法 `change_type/review_status/decision` 被数据库拒绝。
- confidence 超界被拒绝。
- JSON 字段不是 object 时被拒绝。
- 删除源候选后提案保留且 `source_candidate_id=NULL`。
- 删除提案后决定级联删除。

- [x] **Step 2: 运行 RED，确认 `app.reviews` 不存在**
- [x] **Step 3: 实现最小模型和 metadata 注册**
- [x] **Step 4: 生成、检查并应用 Migration 0008**
- [x] **Step 5: 运行 GREEN、Alembic check 和 Ruff**
- [x] **Step 6: 独立提交并推送**

```bash
git commit -m "feat: add candidate review schema"
```

---

## Task 3: Review Service

- [x] **Step 1: 写 Service RED 测试**

覆盖：

- 从真实 Candidate/Skill/Evidence 创建 baseline proposal。
- 重复创建返回同一提案。
- 无技能或无证据时拒绝。
- revise 保存 before/after 快照并更新当前 payload。
- approve 可以确认当前 payload，也可以编辑后确认。
- reject 要求意见并进入终态。
- 终态不能再次决定。
- 技能不存在、非 active 或必备/加分重叠时拒绝。
- 所有写操作产生 Audit Log。

- [x] **Step 2: 运行 RED**
- [x] **Step 3: 实现 Pydantic Schema 和 Service**
- [x] **Step 4: 运行 GREEN 和 Ruff**
- [x] **Step 5: 独立提交并推送**

```bash
git commit -m "feat: review candidate role proposals"
```

---

## Task 4: Review API

- [x] **Step 1: 写 API RED 测试**

覆盖：

- admin/hr 可以创建、查询和决定。
- applicant 所有接口返回 403。
- 写接口缺 CSRF 返回 403。
- 列表支持状态过滤和分页。
- 详情包含定义、Evidence Summary 和完整决定历史。
- 详情不暴露原始 JD Payload/正文。
- 错误码和 HTTP 状态稳定。

- [x] **Step 2: 运行 RED，确认路由 404**
- [x] **Step 3: 实现 Router 并挂载 `/api/v1`**
- [x] **Step 4: 运行 API GREEN 和全量回归**
- [x] **Step 5: 独立提交并推送**

```bash
git commit -m "feat: add candidate review APIs"
```

---

## Task 5: README 与最终验收

- [x] **Step 1: 补充 README**

说明：

- Review API 列表和 curl 示例。
- approve 只代表审核通过，不代表正式发布。
- 当前不调用 LLM、不创建 active JobRole、不写 Neo4j。

- [x] **Step 2: 执行完整门禁**

```bash
docker compose config -q
cd backend
uv run pytest -q
uv run ruff check .
env \
  APP_ENV=test APP_BASE_URL=http://test \
  DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  REDIS_URL=redis://127.0.0.1:6379/0 \
  NEO4J_URI=bolt://127.0.0.1:7687 NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=job_graph_dev FILE_STORAGE_ROOT=/tmp/job-graph-tests \
  SESSION_SECRET=test-secret-at-least-32-characters \
  CORS_ORIGINS='["http://localhost:3000"]' \
  ALGORITHM_SERVICE_URL=http://127.0.0.1:8001 \
  uv run alembic check
git diff --check
```

- [x] **Step 3: 提交并推送**

```bash
git commit -m "docs: document candidate review workflow"
```

---

## Task 6: 分支收尾

- [x] **Step 1: 功能分支全量门禁**
- [x] **Step 2: Fast-forward 合并 `main`**
- [x] **Step 3: 合并后再次运行全量门禁**
- [x] **Step 4: 推送 `origin/main`**
- [x] **Step 5: 删除本地 worktree 和功能分支，保留远端功能分支和 Docker Volume**

---

## 6. 完成标准

- HR 能对候选岗位卡片执行确认、编辑和不采纳。
- 每次决定都有 before/after、审核人、时间和意见。
- 候选和批准结果仍是 PostgreSQL 事实，不直接污染正式 Catalog/Neo4j。
- 现有 Batch A/B/C API 和测试无回归。
- Migration 当前 revision 为 `0008` 且 Alembic 无待生成操作。
