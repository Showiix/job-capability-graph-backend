# Reviewed Job Role Graph Publication Plan

> **Execution rule:** Follow TDD. Write and run the failing test before production code. Commit and push every completed task independently.

**Goal:** 把 Batch D 审核通过的岗位定义提案正式发布为 PostgreSQL active JobRole、岗位—技能关系、Published Catalog Version 和 Neo4j 岗位能力子图，形成“发现 → 审核 → 正式发布”的后端闭环。

**Architecture:** PostgreSQL 仍是发布状态和正式主数据唯一真相源。管理员先从一个 approved Review Proposal 创建 Draft Graph Version，再同步执行小规模 Neo4j `MERGE` 和读回验证；只有验证成功后才激活 PostgreSQL JobRole、Catalog Version 和 Graph Version。失败版本可重试，Neo4j 使用稳定 UUID 和 relation key 保证重复执行不产生重复节点或关系。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、Neo4j Async Driver、pytest、Ruff。

---

## 1. 为什么使用同步发布

本项目是比赛展示和团队内部使用，单次只发布一个候选岗位及少量技能。第一版同步发布足够：

```text
admin request
  -> create/lock GraphVersion
  -> Neo4j MERGE role/capabilities/relations
  -> Neo4j read-back verification
  -> PostgreSQL finalize
```

当前明确不实现：

- Celery 发布 Worker。
- claim token、fencing token。
- graph_publication_attempts 表。
- 批量候选依赖拓扑。
- 多人会签和回滚编排。
- 图谱历史差异和关系失效区间。

当一次版本需要发布数百个变化、多人并发发布或 Neo4j 写入耗时超过 HTTP 超时后，再升级为异步 Worker。

---

## 2. 数据模型

### 2.1 job_roles 增加 definition_payload

现有 `description` 继续保存适合列表展示的职责摘要；新增 `definition_payload JSONB NOT NULL DEFAULT '{}'` 保存审核后的完整结构化定义。

### 2.2 job_role_capabilities

PostgreSQL 必须保存正式岗位—技能事实，Neo4j 只是查询投影。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| job_role_id | uuid | FK JobRole，复合主键 |
| capability_id | uuid | FK Capability，复合主键 |
| requirement_type | varchar(20) | required / bonus |
| importance | numeric(5,4) | `[0,1]` |
| source_candidate_id | uuid nullable | FK GraphChangeCandidate，删除时 SET NULL |
| created_at | timestamptz | 创建时间 |

### 2.3 graph_versions

第一版一个 Graph Version 只发布一个 approved Proposal。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | uuid | PK |
| version_no | integer | 单调递增、唯一、>=1 |
| source_proposal_id | uuid | FK GraphChangeCandidate，唯一 |
| catalog_version_id | uuid | FK CatalogVersion，唯一 |
| job_role_id | uuid | 创建 Draft 时预分配的稳定 UUID；发布前不创建 JobRole 行 |
| status | varchar(20) | draft / publishing / published / failed |
| is_current | boolean | 只有一个 published current |
| snapshot | jsonb | immutable 发布输入快照，必须为 object |
| attempt_count | integer | 实际发布次数，>=0 |
| last_error | text nullable | 脱敏失败信息 |
| created_by_user_id | uuid | admin |
| published_at | timestamptz nullable | published 时必填 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束：

- `(status='published') = (published_at IS NOT NULL)`。
- published current 使用 Partial Unique Index。
- 同一 Proposal 最多进入一个 Graph Version。
- 同一 Catalog Version 最多绑定一个 Graph Version。

### 2.4 Review Proposal 状态

`graph_change_candidates.review_status` 增加 `published`：

```text
approved -> published
```

`published` 为只读终态。

---

## 3. Draft 创建

```http
POST /api/v1/graph-versions

{
  "proposal_id": "uuid"
}
```

仅 admin 可用。创建时：

1. Proposal 必须是 `approved`。
2. Proposal 必须是 `create_job_role`。
3. `required_capability_ids` 至少两个且全部 active。
4. 必备技能必须属于同一 Domain；该 Domain 作为岗位 Domain。
5. 加分技能允许来自其他 Domain，但也必须 active。
6. 同一 Domain 内不能已有同名 JobRole。
7. 创建下一 `CatalogVersion(status=draft)`。
8. 创建 `GraphVersion(status=draft)` 并预分配 `job_role_id`。
9. 固化 Domain、岗位定义、技能名称、技能类型、证据摘要和 relation key 快照。
10. 重复创建返回既有 Version，不创建第二个。

错误码：

```text
GRAPH_SOURCE_PROPOSAL_NOT_FOUND
GRAPH_PROPOSAL_NOT_APPROVED
GRAPH_PROPOSAL_TYPE_UNSUPPORTED
GRAPH_CAPABILITY_INVALID
GRAPH_DOMAIN_AMBIGUOUS
GRAPH_JOB_ROLE_EXISTS
```

---

## 4. Neo4j 投影

节点：

- `(:Domain {id, code, name})`
- `(:JobRole {id, canonical_name, description, status, graph_version})`
- `(:Capability {id, canonical_name, skill_type, status, graph_version})`

关系：

- `(JobRole)-[:BELONGS_TO]->(Domain)`
- `(Capability)-[:BELONGS_TO]->(Domain)`
- `(JobRole)-[:REQUIRES]->(Capability)`
- `(JobRole)-[:BONUS]->(Capability)`

所有节点按 PostgreSQL UUID `MERGE`。所有关系携带稳定 `relation_key`：

```text
sha256(relation_type + source_uuid + target_uuid)
```

写入后读取目标 JobRole 的 `REQUIRES/BONUS`，核对：

- JobRole 存在。
- 技能节点数量等于快照数量。
- REQUIRES/BONUS 关系数量等于快照数量。

不验证全图库，不删除其他版本节点。

---

## 5. 正式发布

```http
POST /api/v1/graph-versions/{version_id}/publish
```

仅 admin 可用，当前同步返回。

状态：

```text
draft -> publishing -> published
failed -> publishing -> published
draft/failed -> publishing -> failed
```

Neo4j 验证成功后的 PostgreSQL finalize 事务：

1. 创建 active JobRole，ID 使用 GraphVersion 预分配值。
2. 创建 JobRoleCapability required/bonus 行。
3. 将所有 active Capability、既有 active JobRole 和新 JobRole 写入 Draft Catalog Version，形成完整快照。
4. 旧 Current Catalog Version `is_current=false`。
5. Draft Catalog Version -> published/current。
6. 旧 Current Graph Version `is_current=false`。
7. Graph Version -> published/current。
8. Proposal -> published。
9. 写 Audit Log。

如果 Neo4j 或 finalize 失败：

- Graph Version -> failed。
- `last_error` 只保存安全信息。
- JobRole、JobRoleCapability 和 Catalog Version 不激活。
- 再次调用 publish 使用同一 JobRole UUID 和 relation keys 重试。

错误码：

```text
GRAPH_VERSION_NOT_FOUND
GRAPH_VERSION_NOT_PUBLISHABLE
GRAPH_PUBLICATION_FAILED
```

---

## 6. API

```text
POST /api/v1/graph-versions
GET  /api/v1/graph-versions
GET  /api/v1/graph-versions/{version_id}
POST /api/v1/graph-versions/{version_id}/publish
```

第一版全部仅 admin 使用。Graph 读 API 在下一批实现；本批通过 Catalog API 和 GraphVersion 详情验证发布结果。

---

## 7. 文件范围

```text
backend/app/catalog/models.py
backend/app/reviews/models.py
backend/app/reviews/service.py
backend/app/graph/__init__.py
backend/app/graph/models.py
backend/app/graph/neo4j.py
backend/app/graph/schemas.py
backend/app/graph/service.py
backend/app/graph/router.py
backend/app/api/router.py
backend/alembic/env.py
backend/alembic/versions/0009_create_graph_publication_tables.py
backend/tests/test_graph_database_constraints.py
backend/tests/test_graph_neo4j.py
backend/tests/test_graph_service.py
backend/tests/test_graph_api.py
README.md
docs/superpowers/plans/2026-08-06-graph-publication.md
```

不增加第三方依赖。

---

## Task 1: 计划与隔离分支

- [x] **Step 1: 创建 `codex/graph-publication` worktree**
- [x] **Step 2: 运行 153 个基线测试和 Ruff**
- [x] **Step 3: 提交并推送计划**

Commit：`docs: plan reviewed graph publication`

---

## Task 2: 模型与 Migration 0009

- [x] **Step 1: 写数据库 RED 测试**
- [x] **Step 2: 运行 RED**
- [x] **Step 3: 实现 JobRole definition、JobRoleCapability、GraphVersion 和 published Review 状态**
- [x] **Step 4: 生成、应用并检查 Migration 0009**
- [x] **Step 5: 运行 GREEN、全量回归、Ruff、Alembic check**
- [x] **Step 6: 提交并推送**

约束测试覆盖：复合主键、relation type、importance、Version 唯一性、状态、published_at 一致性、JSON object 和 current partial unique。

Commit：`feat: add graph publication schema`

---

## Task 3: Neo4j 幂等投影

- [x] **Step 1: 使用 Fake Async Driver 写 RED 测试**
- [x] **Step 2: 实现最小 MERGE 和读回验证**
- [x] **Step 3: 验证相同快照重复执行结果不变**
- [x] **Step 4: 运行 GREEN 和 Ruff**
- [x] **Step 5: 提交并推送**

Commit：`feat: publish reviewed role to neo4j`

---

## Task 4: GraphVersion Service

- [x] **Step 1: 写 Draft 创建和发布 RED 测试**
- [x] **Step 2: 实现快照、状态流转、Catalog finalize 和失败重试**
- [x] **Step 3: 验证 Neo4j 失败不创建 active JobRole**
- [x] **Step 4: 验证成功后 PostgreSQL/Catalog/Proposal 一致**
- [x] **Step 5: 运行 GREEN、全量回归和 Ruff**
- [x] **Step 6: 提交并推送**

Commit：`feat: publish approved graph versions`

---

## Task 5: API、README 与最终门禁

- [ ] **Step 1: 写 admin、HR/applicant 禁止、CSRF、幂等和失败错误码 API 测试**
- [ ] **Step 2: 实现 Router 并挂载**
- [ ] **Step 3: 补 README curl、状态和边界**
- [ ] **Step 4: 执行完整门禁**
- [ ] **Step 5: 提交并推送**

完整门禁：

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

Commit：`docs: document reviewed graph publication`

---

## Task 6: 分支收尾

- [ ] **Step 1: 功能分支完整门禁**
- [ ] **Step 2: Fast-forward 合并 main**
- [ ] **Step 3: main 完整门禁**
- [ ] **Step 4: 推送 origin/main**
- [ ] **Step 5: 清理本地 worktree 和分支；保留远端功能分支和 Docker Volume**

---

## 8. 完成标准

- 未审核或已拒绝提案无法发布。
- Neo4j 失败时 PostgreSQL 不出现 active JobRole。
- 成功发布后 PostgreSQL JobRole、岗位技能关系、Catalog Version、Graph Version、Proposal 状态一致。
- 相同失败版本可以安全重试，不重复创建节点、关系或 JobRole。
- 当前 Migration 为 `0009`，全量测试和 Ruff 通过。
