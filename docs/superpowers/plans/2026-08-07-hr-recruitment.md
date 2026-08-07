# HR Recruitment Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Keep each task independently verifiable and do not expand the approved scope.

**Goal:** 在现有 FastAPI 模块化单体中交付一个可用于内部比赛演示的 HR 私有 JD 与批量候选人匹配闭环：HR 创建招聘项目，输入并确认 JD 要求，批量上传候选人简历，异步解析候选画像，同步执行确定性的五维匹配，保存不可变排名和差距快照，并提供项目、候选人、运行记录和文件读取 API。

**Architecture:** PostgreSQL 是 Recruitment 业务和快照的唯一真相源。HR 私有 JD、外部候选人和候选画像使用独立 Recruitment 模型，不把 HR 候选人伪装成 Applicant Resume，也不改变 Applicant Resume 的所有权。LLM/Algorithm Service 只负责产生候选抽取结果，后端用现有 Capability/CapabilityAlias 和 Evidence 规则校验、映射并持久化。匹配复用 `match_weights_v1` 五维确定性评分；Neo4j、Celery、Redis、LLM 和 Algorithm Service 不参与匹配计算。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 AsyncSession、PostgreSQL 16/JSONB/Numeric、Alembic、Celery + Redis、Pydantic 2、现有 PDF/DOCX 解析器、pytest、Ruff、Docker Compose。

## 0. 已锁定范围、文件责任和实施规则

本计划严格实现已批准的 [HR 私有 JD 与批量候选人匹配详细设计](../specs/2026-08-07-hr-recruitment-design.md)。它是内部展示版的完整后端闭环，不是公开 SaaS 或 ATS。

### 本批实现

```text
HR 创建 recruitment project
输入/上传私有 JD
LLM 提取候选岗位要求
Evidence 校验 + 标准 Capability 精确映射
HR 修订并确认要求版本
批量上传 1-20 份候选简历，可向同一项目追加批次
Celery 异步解析每份候选简历为 CandidateProfile
同步执行 match_weights_v1 五维评分
保存不可变 MatchRun、Result、requirements/candidate 快照和审计
按项目所有权读取候选人、结果和原始文件
```

### 明确不实现

```text
Applicant Resume 与 HR Candidate 自动合并
多态 Resume 所有者改造
ATS、面试、Offer、消息、候选人外部账号
多租户、组织层级、公开访问、复杂 IAM
HR 候选人材料解析（作品集只保留既有文件中转能力）
私有 JD 写入正式 JobRole/Catalog/Graph
Neo4j 参与私有 JD 匹配
LLM 二次排序、动态权重、LangGraph、向量检索
爬虫调度和定时任务
SSE/WebSocket；使用 PostgreSQL-backed ProcessingRun + HTTP polling
```

### 固定模型和公共契约

Recruitment 表为六张：

```text
recruitment_projects
recruitment_candidates
candidate_profiles
candidate_skills
recruitment_match_runs
recruitment_match_results
```

固定公共名字：

```python
# backend/app/catalog/mapping.py
CapabilityResolution
CapabilityResolutionResult
resolve_capability_labels

# backend/app/matching/scoring.py
ScoredRequirements
score_profile_against_requirements

# backend/app/resumes/analysis.py
ResumeAnalysisResult
analyze_resume_document

# backend/app/recruitment/tasks.py
run_parse_recruitment_jd
parse_recruitment_jd_task
run_parse_recruitment_candidates
parse_recruitment_candidates_task
```

固定评分权重：

```text
required skill coverage = 55%
bonus skill coverage    = 10%
skill evidence quality = 15%
experience             = 15%
education              = 5%
weight_version         = match_weights_v1
```

实现顺序固定为 `共享映射 -> 共享评分 -> ORM/migration -> JD -> Candidate -> Match -> E2E`。每个任务完成后先跑任务内测试，再进入下一任务；不得为了“以后扩展”增加 Repository、Provider Factory、通用 Workflow 抽象或配置表。

### 当前基线

已验证：Docker daemon/Compose 可用，pytest `479 passed`，`ruff check .` 通过，Alembic head 为 `0012`。裸本机执行 `uv run alembic current` 因缺少必需环境变量失败，不代表 schema 错误；实施时用完整 Compose 环境验证 migration。全仓 `ruff format --check .` 的 28 个既有格式漂移不属于本任务，不能顺手格式化无关文件。

## Task 0: 运行基线与环境确认

**Files:**

- Verify only: `compose.yaml`
- Verify only: `backend/tests/conftest.py`
- Verify only: `backend/alembic/versions/0012_*.py`
- No production code changes

- [ ] **Step 1: 确认分支、远端和工作树**

Run:

```bash
git status --short --branch
git log -1 --oneline
git rev-parse HEAD
git rev-parse origin/codex/hr-recruitment
git diff --check
```

Expected: 当前分支为 `codex/hr-recruitment`，HEAD 与远端一致，除本计划外无业务改动。若出现用户已有改动，保留并从本任务提交中排除。

- [ ] **Step 2: 启动已有 Compose 依赖**

Run:

```bash
docker info
docker compose version
docker compose config >/dev/null
docker compose up -d postgres redis neo4j
docker compose ps
```

Expected: PostgreSQL、Redis、Neo4j healthy。不得执行 `docker compose down -v`，不得删除已有数据库或 volume。

- [ ] **Step 3: 在 primary/test 数据库确认 Alembic 0012**

Run：

```bash
docker compose run --rm migrate
docker compose exec -T postgres psql -U job_graph -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datname = 'job_graph_test'"
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  migrate
```

若测试库不存在，只创建缺失的 `job_graph_test`，然后再执行测试库 migration；不重建已有库。

- [ ] **Step 4: 重新跑真实回归基线**

Run:

```bash
cd backend
uv run pytest -q
uv run ruff check .
cd ..
git diff --check
```

Expected: `479 passed`、`All checks passed!`。记录 formatter 基线但不修复无关文件。

- [ ] **Step 5: 检查环境产物**

Run `git status --short`，确认没有 `.env`、API key、真实简历、数据库 dump、容器产物或缓存文件进入版本控制。Task 0 不创建 commit。

## Task 1: 抽取 Capability 精确映射核心

**Files:**

- Create: `backend/app/catalog/mapping.py`
- Create: `backend/tests/test_capability_mapping.py`
- Modify: `backend/app/resumes/service.py`
- Modify: `backend/tests/test_resume_tasks.py`

**Purpose:** 让 JD 和 Candidate Resume 共享同一个 active `Capability`/`CapabilityAlias` 精确解析器，保证标准技能库是唯一真相源；保留现有 `map_resume_skills()` 对外接口和行为。

- [ ] **Step 1: 写 RED 测试**

覆盖：canonical label 命中、alias 命中、大小写/空白规范化、inactive capability 不命中、inactive alias 不命中、重复输入去重、未知标签进入 unmapped、同名歧义不静默选择错误记录。测试使用现有 SQLAlchemy fixture，不创建第二套 Capability seed。

示例契约：

```python
result = await resolve_capability_labels(session, [" Python ", "PyTorch", "新技能"])
assert result.mapped[0].capability_id == python_id
assert result.unmapped == ["新技能"]
```

- [ ] **Step 2: 实现最小纯边界**

在 `mapping.py` 定义 `CapabilityResolution`（输入标签、normalized label、matched capability、match kind、confidence/source）和 `CapabilityResolutionResult`（mapped、unmapped、warnings）。查询 active capability/alias，统一用现有 normalized 字段规则；不引入模糊匹配、embedding 或 LLM。

- [ ] **Step 3: 迁移 Resume 调用方**

让 `backend/app/resumes/service.py::map_resume_skills()` 调用共享解析器，再转换回现有返回结构。保留现有排序、错误行为和数据库写入事务。更新 `test_resume_tasks.py`，证明 Applicant Resume 解析回归不变。

- [ ] **Step 4: 验证**

```bash
cd backend
uv run pytest -q tests/test_capability_mapping.py tests/test_resume_tasks.py
uv run ruff check app/catalog/mapping.py app/resumes/service.py tests/test_capability_mapping.py tests/test_resume_tasks.py
uv run ruff format --check app/catalog/mapping.py app/resumes/service.py tests/test_capability_mapping.py tests/test_resume_tasks.py
```

## Task 2: 抽取共享五维评分核心

**Files:**

- Modify: `backend/app/matching/scoring.py`
- Modify: `backend/tests/test_matching_scoring.py`

**Purpose:** Applicant 正式岗位推荐和 HR 私有 JD 匹配必须使用同一套确定性、可解释、可复现的评分规则；只抽取输入适配，不改变现有 Applicant 输出。

- [ ] **Step 1: 写 RED 测试**

新增 `ScoredRequirements` 输入测试，覆盖 required/bonus 能力、mention/project/work evidence、experience、education、缺失 required、空技能但有项目/经历、Decimal 边界和稳定排序。保留现有 `score_job_role()` 全部回归断言。

- [ ] **Step 2: 实现 `score_profile_against_requirements()`**

该函数只接收已解析的 profile evidence 和已确认的 requirements，不导入 FastAPI、SQLAlchemy、Celery、Neo4j 或 LLM。输出总分、五维分数、matched/missing capability 以及每项 Evidence 摘要。使用现有 `Decimal` 权重、阈值和 evidence quality 规则；所有舍入沿用当前实现。

- [ ] **Step 3: 让 `score_job_role()` 包装共享核心**

把 Applicant 现有岗位输入转换为 `ScoredRequirements` 后调用共享函数；保持字段名、match level、排序和快照结构不变。禁止在 Recruitment 模块复制一份评分公式。

- [ ] **Step 4: 验证**

```bash
cd backend
uv run pytest -q tests/test_matching_scoring.py
uv run ruff check app/matching/scoring.py tests/test_matching_scoring.py
uv run ruff format --check app/matching/scoring.py tests/test_matching_scoring.py
```

## Task 3: 建立六表 ORM 与 Alembic 0013

**Files:**

- Create: `backend/app/recruitment/__init__.py`
- Create: `backend/app/recruitment/models.py`
- Create: `backend/alembic/versions/0013_create_recruitment_tables.py`
- Create: `backend/tests/recruitment_fixtures.py`
- Create: `backend/tests/test_recruitment_database_constraints.py`
- Modify: `backend/alembic/env.py`

**Purpose:** 把 HR 私有 JD、候选人、解析画像和匹配快照落到明确的 Recruitment ownership boundary；PostgreSQL 约束优先于应用层约定。

- [ ] **Step 1: 先写 schema/constraint RED 测试**

覆盖以下约束和删除行为：

```text
recruitment_projects.owner_user_id -> users.id
recruitment_projects.requirements_revision >= 0
requirements_revision = 0 时 confirmed_requirement_sha256 必须为空
requirements_revision >= 1 时 confirmed_requirement_sha256 必须为 64 位 hex
recruitment_candidates.project_id/file_id 外键
candidate_profiles.candidate_id UNIQUE
candidate_skills.profile_id/capability_id 外键
match_runs.project_id/confirmed requirement revision 外键语义
match_results (match_run_id, candidate_id) 复合主键
match_results (match_run_id, rank) UNIQUE
match_level 只能是 high/medium/low
JSONB snapshot 类型必须正确
删除 Project 级联候选、Profile、Skill、Run、Result
```

测试不能用 SQLite 替代 PostgreSQL；使用现有 transactional PostgreSQL fixture，并验证提交时约束生效。

- [ ] **Step 2: 实现 ORM**

在 `models.py` 只定义本批需要的六个模型和关系：

```text
RecruitmentProject
  id, owner_user_id, name, status, jd_source_type, jd_file_id,
  jd_source_sha256, jd_source_text, jd_draft_payload,
  confirmed_requirements, confirmed_requirement_sha256,
  requirements_revision, confirmed_at, confirmed_by_user_id,
  created_at, updated_at

RecruitmentCandidate
  id, project_id, display_name, source_file_id, status,
  latest_run_id, parse_error_code, parse_error_message,
  created_at, updated_at

CandidateProfile
  id, candidate_id, summary, education_evidence, experience_evidence,
  project_evidence, raw_extracted_payload, parser_version,
  created_at, updated_at

CandidateSkill
  id, profile_id, capability_id, display_name, evidence_type,
  evidence_text, evidence_strength, source_span, created_at

RecruitmentMatchRun
  id, project_id, requirements_revision, requirements_sha256,
  candidate_selection_sha256, weight_version, status, total_count,
  ready_count, skipped_count, skipped_candidates, created_at,
  completed_at, created_by_user_id

RecruitmentMatchResult
  match_run_id, candidate_id, candidate_profile_id, rank, score,
  match_level, matched_capabilities, missing_capabilities,
  dimension_scores, gap_summary, candidate_snapshot,
  requirements_snapshot, created_at
```

沿用现有 `Base`、时间戳 mixin、UUID 类型、JSONB 和 Numeric 精度。不要把原始简历正文复制进 Match Result；候选快照仅保存展示和评分所需摘要。

- [ ] **Step 3: 编写 migration 0013**

`revision = "0013"`、`down_revision = "0012"`。按外键依赖顺序创建表和索引，至少包括：project owner/status、candidate project/status、profile candidate unique、candidate skill profile/capability、run project/自然唯一键、result run/rank 索引。`downgrade()` 按反向依赖删除六表和索引。

- [ ] **Step 4: 注册模型与 migration metadata**

让 Alembic `env.py` 导入 Recruitment models，使 autogenerate 和 runtime metadata 都能看到六表；不改既有模型表名或 Applicant ownership。

- [ ] **Step 5: 验证**

```bash
docker compose run --rm migrate
cd backend
uv run pytest -q tests/test_recruitment_database_constraints.py
uv run alembic heads
uv run ruff check app/recruitment/models.py tests/recruitment_fixtures.py tests/test_recruitment_database_constraints.py
uv run ruff format --check app/recruitment/models.py tests/recruitment_fixtures.py tests/test_recruitment_database_constraints.py
cd ..
git diff --check
```

Expected Alembic head 为 `0013`，所有 PostgreSQL 约束测试通过。

## Task 4: JD Schema、文件解析、Evidence 校验和 LLM 适配

**Files:**

- Create: `backend/app/recruitment/schemas.py`
- Create: `backend/app/recruitment/parsing.py`
- Create: `backend/app/recruitment/llm.py`
- Create: `backend/tests/test_recruitment_schemas.py`
- Create: `backend/tests/test_recruitment_parsing.py`
- Create: `backend/tests/test_recruitment_llm.py`

**Purpose:** 把 JD 输入、解析候选结果和确认请求固定成可验证的边界。外部 LLM 只通过 OpenAI Responses endpoint 的既有客户端/配置调用，不能直接写数据库。

- [ ] **Step 1: 定义 Pydantic 契约**

至少定义：

```python
RecruitmentJDParseResponse
RequirementsReplaceRequest
RequirementsConfirmResponse
RecruitmentProjectCreateRequest/Response
RecruitmentCandidateUploadResponse
MatchRunResponse/MatchResultResponse
```

JD parse payload 包含岗位标题、摘要、职责顺序、学历/经验、required/bonus requirements、unmapped skills、warnings、source metadata；`requirement_type` 只能为 `required` 或 `bonus`，技能引用必须携带原始 label 和 evidence。

- [ ] **Step 2: 复用现有 PDF/DOCX 文本提取**

实现固定函数：

```python
detect_jd_document(filename: str, content_type: str | None) -> str
extract_jd_text(filename: str, content: bytes) -> str
```

支持 TXT/PDF/DOCX，复用 Resume parser 的底层逻辑；拒绝未知扩展名、空文件和超过既有上传上限的文件，错误映射到明确的 API error code。保留 source hash 和原始文本用于确认哈希/审计。

- [ ] **Step 3: 实现 Evidence exact-match 校验**

`validate_jd_evidence()` 只接受 LLM 输出中的 source span/quote，检查其确实出现在脱敏前的 JD 文本中；不存在的 evidence 进入 warnings 并不允许直接成为 confirmed requirement。随后调用 Task 1 的 `resolve_capability_labels()`。未知技能保留在 `unmapped_skills`，等待 HR 编辑，不伪造 Capability ID。

- [ ] **Step 4: 实现 `RecruitmentJDResponsesClient`**

客户端负责：构造结构化 response schema 请求、传入经过截断/安全处理的 JD 文本、解析 JSON schema 结果、记录 model/prompt/parser metadata 和 request id。客户端异常统一转换为可重试的 `RECRUITMENT_JD_LLM_FAILED`；不在 client 内做业务提交、重试循环或 Celery 调度。测试使用 fake client，断言没有真实网络请求。

- [ ] **Step 5: 验证**

```bash
cd backend
uv run pytest -q tests/test_recruitment_schemas.py tests/test_recruitment_parsing.py tests/test_recruitment_llm.py
uv run ruff check app/recruitment/schemas.py app/recruitment/parsing.py app/recruitment/llm.py tests/test_recruitment_*.py
uv run ruff format --check app/recruitment/schemas.py app/recruitment/parsing.py app/recruitment/llm.py tests/test_recruitment_*.py
```

## Task 5: Project/JD workflow、确认版本和 API

**Files:**

- Create: `backend/app/recruitment/service.py`
- Create: `backend/app/recruitment/tasks.py`
- Create: `backend/app/recruitment/router.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/worker.py`
- Create: `backend/tests/test_recruitment_project_api.py`
- Create: `backend/tests/test_recruitment_jd_tasks.py`

**Endpoints:**

```text
POST /api/v1/recruitment-projects
GET  /api/v1/recruitment-projects
GET  /api/v1/recruitment-projects/{project_id}
POST /api/v1/recruitment-projects/{project_id}/jd
PUT  /api/v1/recruitment-projects/{project_id}/requirements
POST /api/v1/recruitment-projects/{project_id}/requirements/confirm
```

- [ ] **Step 1: 写 Project/JD API RED 测试**

覆盖 HR 创建、列表分页、详情、跨 HR 隔离、Admin 可见、Applicant 拒绝/脱敏 404、文本 JD、文件 JD、空 JD、超限文件、重复 idempotency key 和不存在 project。测试只通过 HTTP API 进入 service，不直接调用 router 内部函数。

- [ ] **Step 2: 实现 Project service/router**

创建项目时锁定 `owner_user_id = actor.id`，状态初始为 `draft`；列表和详情统一使用 project ownership loader。router 只负责 request parsing、actor/CSRF/idempotency 传递和 response envelope，不直接 commit。

- [ ] **Step 3: 实现 JD 提交和异步 ProcessingRun**

文本直接保存 source hash/text；文件复用现有 File service 后保存 `jd_file_id`。数据库提交 Project/Run 后再投递 `app.parse_recruitment_jd`，投递失败将 Run 标为 `enqueue_failed`。`run_parse_recruitment_jd()` 在事务内读取 project、解析文本、调用 fake/real client、Evidence 校验、写入 draft payload；不直接修改 confirmed snapshot。

- [ ] **Step 4: 实现整体替换和确认**

`PUT .../requirements` 只替换 draft，要求 Pydantic 校验和 Capability 映射结果一致。确认时在 project row lock 下计算 canonical `confirmed_requirement_sha256`：排除 `revision_no`、`confirmed_at`、`confirmed_by_user_id` 和 LLM metadata；requirements 按 `requirement_type + capability_id` 排序，unmapped/warnings 按规范化顺序排序，responsibilities 保留展示顺序。相同 hash 返回 `reused=true` 且 revision 不变；不同 hash 才递增 revision 并写 confirmed snapshot/audit。

- [ ] **Step 5: 注册 task/router**

在 `backend/app/api/router.py` include recruitment router；在 `backend/app/worker.py` 注册 Celery task 名称 `app.parse_recruitment_jd`，task wrapper 只接收 `run_id`，真正业务逻辑进入 `run_parse_recruitment_jd()`，以便单测和 retry 复用。

- [ ] **Step 6: 验证**

```bash
cd backend
uv run pytest -q tests/test_recruitment_project_api.py tests/test_recruitment_jd_tasks.py
uv run ruff check app/recruitment/service.py app/recruitment/tasks.py app/recruitment/router.py app/api/router.py app/worker.py tests/test_recruitment_project_api.py tests/test_recruitment_jd_tasks.py
uv run ruff format --check app/recruitment/service.py app/recruitment/tasks.py app/recruitment/router.py app/api/router.py app/worker.py tests/test_recruitment_project_api.py tests/test_recruitment_jd_tasks.py
```

## Task 6: ProcessingRun、文件可见性和 CORS 权限

**Files:**

- Modify: `backend/app/processing/service.py`
- Modify: `backend/app/files/service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_processing_runs.py`
- Modify: `backend/tests/test_files.py`
- Create: `backend/tests/test_recruitment_access.py`

**Purpose:** Recruitment Run 和文件必须遵循同一 ownership 规则，避免通过 run/file ID 跨 HR 泄露 JD 或简历。

- [ ] **Step 1: 写权限 RED 测试**

覆盖 owner HR、另一个 HR、Applicant、Admin 对 Project/JD Run/Candidate Run/JD file/Candidate Resume file 的访问矩阵；跨项目 run_id、candidate_id、file_id 必须得到拒绝或脱敏 404，不能通过猜 ID 读取正文。

- [ ] **Step 2: 扩展 `visible_run_predicate()`**

当 `scope_type == "recruitment_project"` 时使用 `EXISTS` 子查询连接 `recruitment_projects.owner_user_id == actor.id`。不要在 API 层先查 project 再用不带 scope 的通用 run 查询，以免形成 TOCTOU 或遗漏路径。

- [ ] **Step 3: 扩展文件 ownership**

```text
JD file -> RecruitmentProject.owner_user_id
Candidate Resume file -> RecruitmentCandidate -> Project.owner_user_id
```

沿用现有 file download/metadata service；只添加 Recruitment 关系判断，不改变 Applicant Resume file 规则。错误统一为既有 not-found/forbidden 行为，避免暴露资源存在性。

- [ ] **Step 4: 更新 CORS**

在 `allow_headers` 中增加 `Idempotency-Key`，保留现有明确 header 白名单；不要改成 `allow_headers=["*"]`，不要增加任意新 origin。

- [ ] **Step 5: 验证**

```bash
cd backend
uv run pytest -q tests/test_processing_runs.py tests/test_files.py tests/test_recruitment_access.py
uv run ruff check app/processing/service.py app/files/service.py app/main.py tests/test_processing_runs.py tests/test_files.py tests/test_recruitment_access.py
uv run ruff format --check app/processing/service.py app/files/service.py app/main.py tests/test_processing_runs.py tests/test_files.py tests/test_recruitment_access.py
```

## Task 7: 共享 Resume Analysis 与候选人批量解析

**Files:**

- Create: `backend/app/resumes/analysis.py`
- Create: `backend/tests/test_resume_analysis.py`
- Create: `backend/tests/test_recruitment_candidate_api.py`
- Create: `backend/tests/test_recruitment_candidate_tasks.py`
- Modify: `backend/app/resumes/tasks.py`
- Modify: `backend/app/recruitment/service.py`
- Modify: `backend/app/recruitment/tasks.py`
- Modify: `backend/app/recruitment/router.py`

**Endpoints:**

```text
POST /api/v1/recruitment-projects/{project_id}/candidates
GET  /api/v1/recruitment-projects/{project_id}/candidates
GET  /api/v1/recruitment-projects/{project_id}/candidates/{candidate_id}
```

**Purpose:** Candidate Resume 与 Applicant Resume 共享“文档转画像”的纯分析核心，但持久化所有权和结果表完全分离。

- [ ] **Step 1: 写共享分析 RED 测试**

固定 `ResumeAnalysisResult`，覆盖姓名/摘要、学历证据、工作经历证据、项目证据、技能原始标签、source span、空技能但存在其他 evidence、空文档、解析失败、PII 脱敏后外部调用。验证 Candidate 和 Applicant 都能调用同一个纯函数，而不共享 Resume ORM 行。

- [ ] **Step 2: 实现 `analyze_resume_document()`**

函数负责文件类型检测、PDF/DOCX/TXT 文本提取、复用现有 PII 脱敏和已有算法/LLM 分析入口，返回结构化 `ResumeAnalysisResult`；不执行 SQL、不写 profile、不创建 task。旧 `backend/app/resumes/tasks.py` 适配该函数，保持 Applicant 任务状态和输出不变。

- [ ] **Step 3: 写候选批量 API RED 测试**

覆盖单批 1-20 份、超出 20 拒绝、空 batch 拒绝、同一 project 追加、文件类型/大小校验、候选 display name、202 response、每个 candidate id 返回、owner/Admin/other HR 权限、同一 `Idempotency-Key` 重放不重复创建。

- [ ] **Step 4: 实现 Candidate upload/list/detail**

上传在一个事务中创建候选行和一个 project-scoped ProcessingRun；候选初始状态为 `uploaded`，`latest_run_id` 指向本次 Run。提交后投递 Celery；投递失败保留已创建资源并标记 Run `enqueue_failed`，禁止静默丢失候选。

- [ ] **Step 5: 实现逐候选异步任务**

固定函数：

```python
run_parse_recruitment_candidates(run_id: UUID) -> None
parse_recruitment_candidates_task(run_id: str) -> None
```

任务按 candidate UUID 稳定顺序逐个处理，每个 Candidate 单独事务：读取文件、调用 `analyze_resume_document()`、Evidence exact-match 校验、调用 `resolve_capability_labels()`、写入/替换 CandidateProfile 和 CandidateSkill、更新 candidate 为 `ready`。Profile 可以有 0 个 Skill，只要有有效学历、经历或项目证据。

- [ ] **Step 6: 处理失败、重试和取消**

单项失败只回滚该 Candidate，写 `ProcessingError(item_type="recruitment_candidate", item_id=...)`，错误正文不包含简历原文；继续处理其他 Candidate。任一 item 失败时 Run 最终为 `failed`，错误码固定为 `CANDIDATE_BATCH_PARTIAL_FAILURE`。通用 retry 创建新 Run，复用原 candidate ids，跳过已经 `ready` 且有 profile 的 Candidate，只接管非 ready 或失败项；在 Candidate 之间检查现有 cancel 标志。

- [ ] **Step 7: 验证**

```bash
cd backend
uv run pytest -q tests/test_resume_analysis.py tests/test_recruitment_candidate_api.py tests/test_recruitment_candidate_tasks.py tests/test_resume_tasks.py
uv run ruff check app/resumes/analysis.py app/resumes/tasks.py app/recruitment/service.py app/recruitment/tasks.py app/recruitment/router.py tests/test_resume_analysis.py tests/test_recruitment_candidate_api.py tests/test_recruitment_candidate_tasks.py
uv run ruff format --check app/resumes/analysis.py app/resumes/tasks.py app/recruitment/service.py app/recruitment/tasks.py app/recruitment/router.py tests/test_resume_analysis.py tests/test_recruitment_candidate_api.py tests/test_recruitment_candidate_tasks.py
```

## Task 8: 同步 Recruitment Match Run 与不可变排名

**Files:**

- Create: `backend/app/recruitment/matching.py`
- Create: `backend/tests/test_recruitment_matching.py`
- Create: `backend/tests/test_recruitment_match_api.py`
- Modify: `backend/app/recruitment/service.py`
- Modify: `backend/app/recruitment/schemas.py`
- Modify: `backend/app/recruitment/router.py`

**Endpoints:**

```text
POST /api/v1/recruitment-projects/{project_id}/match-runs
GET  /api/v1/recruitment-projects/{project_id}/match-runs
GET  /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results
GET  /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results/{candidate_id}
```

**Purpose:** 匹配是同步、确定性、可复现的数据库事务；每次运行保存 requirements/candidate 输入水位和展示所需快照。

- [ ] **Step 1: 写纯匹配 RED 测试**

固定输入转换和输出契约，覆盖 required/bonus 计算、五维分数、缺失技能、Evidence 摘要、high/medium/low 分级、failed candidate skipped snapshot、ready candidate 缺 Profile 拒绝、uploaded/processing candidate 阻止匹配、稳定排序 tie-break。测试中不得 mock 出第二套评分公式。

- [ ] **Step 2: 实现 `matching.py` 输入转换**

定义 `requirement_inputs`、`profile_input` 和 `canonical_candidate_selection` 的最小结构。`canonical_candidate_selection` 对项目全部 Candidate 按 UUID 排序，保存每项 `candidate_id/status/profile_id/profile_version`；`sha256_json()` 使用 UTF-8、排序 key、紧凑 separators 计算 SHA-256。

- [ ] **Step 3: 实现 `create_match_run()` 事务**

事务流程固定：

```text
lock project
要求 requirements_revision >= 1
lock project candidates in UUID order
uploaded/processing -> 409 CANDIDATES_NOT_READY
failed -> skipped_candidates snapshot
ready -> 必须存在 CandidateProfile
计算 requirements_sha256 + candidate_selection_sha256
按自然唯一键查已有 Run，存在则返回 reused=true
调用 score_profile_against_requirements()
一次事务写 Run、全部 Results、Audit
unique conflict 后 rollback，再读取胜出 Run
```

自然唯一键：`project_id + requirements_sha256 + candidate_selection_sha256 + weight_version`。不接受请求体中的 candidate_ids、权重、阈值；匹配始终使用项目当前确认要求和项目全部候选。

- [ ] **Step 4: 实现结果查询 API**

列表按 `rank` 分页，返回 score、level、candidate snapshot、dimension scores、gap summary；详情返回 Run requirements snapshot、candidate snapshot、matched capabilities、missing capabilities 和五维解释。所有查询先经过 project/run ownership loader，不能只按 run_id/candidate_id 直查。

- [ ] **Step 5: 审计和错误语义**

记录 `recruitment_match.run`，包含 project id、run id、requirements revision/hash、candidate count、weight version、skipped count，不写简历正文。固定错误至少包括：`REQUIREMENTS_NOT_CONFIRMED`、`CANDIDATES_NOT_READY`、`CANDIDATE_PROFILE_MISSING`、`MATCH_INPUT_CONFLICT`。

- [ ] **Step 6: 验证**

```bash
cd backend
uv run pytest -q tests/test_recruitment_matching.py tests/test_recruitment_match_api.py
uv run ruff check app/recruitment/matching.py app/recruitment/service.py app/recruitment/schemas.py app/recruitment/router.py tests/test_recruitment_matching.py tests/test_recruitment_match_api.py
uv run ruff format --check app/recruitment/matching.py app/recruitment/service.py app/recruitment/schemas.py app/recruitment/router.py tests/test_recruitment_matching.py tests/test_recruitment_match_api.py
```

## Task 9: 端到端链路、项目详情和 README

**Files:**

- Create: `backend/tests/test_recruitment_end_to_end.py`
- Modify: `backend/app/recruitment/service.py`
- Modify: `backend/app/recruitment/schemas.py`
- Modify: `backend/app/recruitment/router.py`
- Modify: `README.md`

- [ ] **Step 1: 写完整链路测试**

使用 fake JD client、fake resume analyzer 和 Celery task 函数，执行：

```text
HR login
-> create project
-> submit text JD
-> fake JD task
-> replace draft requirements
-> confirm requirements revision 1
-> upload two candidate resumes
-> fake candidate task
-> create match run
-> read ranking and candidate detail
-> read JD/candidate original file metadata/content
-> second HR sees 404/forbidden
-> Applicant sees 404/forbidden
-> Admin can inspect project and run
```

再验证：相同确认内容不增加 revision；相同匹配输入复用 Run；失败候选进入 skipped snapshot；跨项目 IDs 不泄露数据；Applicant Resume 原有推荐接口仍通过。

- [ ] **Step 2: 补项目详情最小聚合字段**

项目详情返回当前 JD parse 状态、requirements revision/confirmed summary、candidate counts、latest processing run、latest match run 摘要；不把所有候选和全文嵌套在 Project detail 中。候选和结果继续使用分页 endpoint。

- [ ] **Step 3: 更新 README**

补充内部演示运行方式：Compose 依赖、migration、worker、HR login、JD 上传、候选批量上传、poll ProcessingRun、确认 requirements、创建 match run 和读取结果。明确说明：爬虫暂未接入，当前入口是批量导入；Neo4j 不参与私有 JD 匹配；LLM 只提供候选抽取，最终分数由后端确定性规则产生。

- [ ] **Step 4: 验证**

```bash
cd backend
uv run pytest -q tests/test_recruitment_end_to_end.py
uv run ruff check app/recruitment/service.py app/recruitment/schemas.py app/recruitment/router.py tests/test_recruitment_end_to_end.py
uv run ruff format --check app/recruitment/service.py app/recruitment/schemas.py app/recruitment/router.py tests/test_recruitment_end_to_end.py
cd ..
git diff --check
```

## Task 10: 完成报告、全量质量门槛和交付

**Files:**

- Create: `docs/superpowers/reports/2026-08-07-hr-recruitment-completion-report.md`
- No unrelated source or formatting changes

- [ ] **Step 1: 执行全量检查**

Run from repository root:

```bash
docker compose run --rm migrate
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check \
  app/catalog/mapping.py app/matching/scoring.py app/recruitment \
  app/resumes/analysis.py app/resumes/tasks.py \
  app/processing/service.py app/files/service.py app/main.py \
  tests/test_capability_mapping.py tests/test_matching_scoring.py \
  tests/test_recruitment_*.py tests/test_resume_analysis.py
cd ..
git diff --check
git status --short
```

全仓 formatter 仍允许报告已有 28 个文件漂移，但本任务新增/修改路径必须通过 scoped formatter check；不得把全仓格式化噪音加入提交。

- [ ] **Step 2: 完成报告必须包含**

```text
实现范围和明确未实现范围
新增六表、0013 migration 和关键约束
新增 API 清单与同步/异步边界
Capability 唯一真相源和 Evidence/RAG/LLM 边界
五维 match_weights_v1 公式、快照和幂等键
权限、文件可见性、重试/取消语义
测试数量、pytest/ruff/diff check 结果
已知简化和下一阶段升级触发条件
```

- [ ] **Step 3: 只提交本批文件**

```bash
git status --short
git add docs/superpowers/plans/2026-08-07-hr-recruitment.md
git add docs/superpowers/reports/2026-08-07-hr-recruitment-completion-report.md
git add backend/app/catalog/mapping.py backend/app/matching/scoring.py
git add backend/app/recruitment backend/app/resumes/analysis.py backend/app/resumes/tasks.py
git add backend/app/processing/service.py backend/app/files/service.py backend/app/main.py
git add backend/app/api/router.py backend/app/worker.py backend/alembic/env.py
git add backend/alembic/versions/0013_create_recruitment_tables.py
git add backend/tests
git diff --cached --check
git commit -m "feat: add hr recruitment matching workflow"
git push
```

如果 `backend/tests` 下有与本任务无关的用户文件，改为逐文件 `git add`；不得吸收无关改动。成功 push 后在最终回复中报告 commit、branch 和验证结果。

## 实施交接

计划提交后进入 inline execution，按 Task 0 到 Task 10 顺序执行；当前约束不启动子代理，且用户已明确无需逐步确认。每个任务完成后更新 checkbox 和运行结果，遇到失败先修复根因再推进，不以跳过测试代替完成。
