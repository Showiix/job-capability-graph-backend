# Applicant Job Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 applicant 基于唯一 confirmed Resume Profile，对当前正式岗位目录执行同步、确定性、可解释的人岗匹配，保存完整不可变结果，并提供本人/Admin 可用的推荐历史、分页结果和单岗位差距明细 API。

**Architecture:** PostgreSQL 是匹配输入、版本水位、结果快照和审计记录的唯一真相源；Matching Service 锁定 Resume 后选择 confirmed Profile、current published Graph Version 及其 current published Catalog Version，批量读取标准岗位和技能，在 Python 内用 `Decimal` 完成 `match_weights_v1` 五维评分与稳定排序，并在单一事务中写入 Match Run、全部 Match Result 和 Audit Log。Neo4j、Celery、Redis、LLM、Algorithm Service、LangChain 和 LangGraph 均不进入本批调用链。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2 AsyncSession、PostgreSQL 16/JSONB/Numeric、Python 标准库 `Decimal`、Alembic、pytest、Ruff、Docker Compose。

---

## 0. 已锁定范围、文件责任和执行前提

本计划严格实现设计文档 [2026-08-07-applicant-job-recommendations-design.md](../specs/2026-08-07-applicant-job-recommendations-design.md)，只覆盖以下 Applicant Job Recommendation API：

```text
POST /api/v1/job-recommendations
GET  /api/v1/job-recommendations
GET  /api/v1/job-recommendations/{match_run_id}
GET  /api/v1/job-recommendations/{match_run_id}/job-roles/{job_role_id}
```

POST 请求只接受：

```json
{
  "resume_id": "resume-uuid"
}
```

系统自动锁定并保存以下输入水位：

```text
Resume 当前唯一 confirmed ResumeProfile
current published GraphVersion
GraphVersion.catalog_version_id 对应的 current published CatalogVersion
match_weights_v1
```

完整正式岗位集合固定来自：

```text
GraphVersion.catalog_version_id
→ CatalogVersionItem(item_type=job_role)
→ active JobRole
→ JobRoleCapability
→ active Capability
```

明确不实现：HR 外部候选人批量匹配、成长路径、学习资源、岗位收藏、推荐删除/重算按钮、异步任务、ProcessingRun、Celery Task、Redis Cache/Lock、Neo4j 查询或回退、LLM 语义匹配、Algorithm Service、向量检索、技能 Alias 二次匹配、经验/学历硬过滤、权重配置表、环境变量权重、Repository 层、Provider interface/factory、通用 Matching Engine、SSE/WebSocket。

固定公式版本：

```text
weight_version = match_weights_v1

required skill coverage = 55%
bonus skill coverage    = 10%
skill evidence quality  = 15%
experience              = 15%
education               = 5%

mention = 0.40
project = 0.70
work    = 1.00
```

文件责任固定如下：

```text
backend/app/matching/models.py
  MatchRun、MatchResult ORM 和数据库约束。

backend/app/matching/schemas.py
  POST 严格请求模型、Run/列表/明细响应模型及 Literal 类型。

backend/app/matching/scoring.py
  match_weights_v1 常量、纯 Decimal 五维评分、快照构造和稳定排序；
  不导入 SQLAlchemy、FastAPI、AsyncSession 或业务 Service。

backend/app/matching/service.py
  权限、Resume 行锁、confirmed Profile 和发布水位选择、批量目录读取、
  同步计算、自然幂等、原子持久化、并发唯一冲突恢复、历史查询和审计。

backend/app/matching/router.py
  FastAPI 路径、请求参数、CSRF 和统一 data envelope；不直接 commit。

backend/tests/matching_fixtures.py
  只保存 Matching 数据库/Service/API 测试共享的最小数据构造器；
  不变成生产 seed、通用 fixture framework 或演示数据生成器。
```

复用现有代码，不创建重复机制：

```text
Resume / ResumeProfile / ResumeSkill    backend/app/resumes/models.py
get_visible_resume                      backend/app/resumes/service.py
JobRole / Capability / CatalogVersion   backend/app/catalog/models.py
GraphVersion                            backend/app/graph/models.py
record_audit                            backend/app/audit/service.py
APIError / Identity / CSRF / DB         backend/app/core/*, backend/app/api/*
Base / CreatedAtMixin                   backend/app/infrastructure/database.py
```

当前恢复基线：

```text
branch: codex/applicant-matching
HEAD:   64d0deb docs: design applicant job recommendations
remote: origin/codex/applicant-matching 与 HEAD 一致
ruff:   All checks passed!
pytest: 当前本机 127.0.0.1:5432 拒绝连接；这是数据库 runtime 未启动，不是代码失败
docker: Docker CLI 29.6.1 存在，但当前 daemon/Compose 不可用
prior verified baseline: 362 passed，primary/test DB Alembic 0010 head
```

因此 Task 0 是实施硬前提。不得修改 `compose.yaml`、测试数据库 URL 或 fixture 来掩盖 runtime 问题，也不得执行 `docker compose down -v`。

## Task 0: 恢复 PostgreSQL/Compose，确认 0010 基线和干净工作区

**Files:**

- Verify only: `compose.yaml`
- Verify only: `backend/tests/conftest.py`
- Verify only: `backend/alembic/versions/0010_create_resume_profile_tables.py`
- No production code changes

- [ ] **Step 1: 确认计划起点、分支和远端水位**

Run:

```bash
git status --short --branch
git log -1 --oneline
git rev-parse HEAD
git rev-parse origin/codex/applicant-matching
git diff --check
```

Expected:

```text
current branch: codex/applicant-matching
HEAD: 64d0deb docs: design applicant job recommendations
local HEAD equals origin/codex/applicant-matching
```

除了本计划自身，不应存在业务代码改动。若出现其他未提交文件，先区分用户改动并保持原样，不得回退或吸收到后续提交。

- [ ] **Step 2: 恢复支持 Compose 的本机容器 runtime**

Run:

```bash
command -v docker
docker --version
docker info
docker compose version
command -v docker-compose
docker-compose --version
```

Expected before continuing: `docker info` 能连接 daemon，并且 `docker compose version` 或 `docker-compose --version` 至少一个成功。

若当前仍为 daemon 不可达或 `docker: unknown command: docker compose`，启动团队既有 Docker Desktop、OrbStack 或 Colima，并启用 Compose。该步骤只修复本机运行环境，不改仓库文件。下文统一写 `docker compose`；仅有独立 `docker-compose` 时逐条等价替换。

- [ ] **Step 3: 启动既有依赖并迁移 primary/test database 到 0010**

Run:

```bash
docker compose config >/dev/null
docker compose up -d postgres redis neo4j
docker compose ps
docker compose run --rm migrate
docker compose exec -T postgres psql -U job_graph -d postgres \
  -tAc "SELECT datname FROM pg_database WHERE datname = 'job_graph_test'"
```

Expected:

```text
postgres healthy
redis healthy
neo4j healthy
primary database reaches revision 0010
job_graph_test exists
```

如果最后一条没有输出 `job_graph_test`，只创建缺失的测试数据库：

```bash
docker compose exec -T postgres createdb -U job_graph job_graph_test
```

然后迁移测试数据库：

```bash
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  migrate
```

禁止 drop 既有 primary database、测试数据库或 volume；禁止执行 `docker compose down -v`。

- [ ] **Step 4: 重新建立真实回归基线**

Run:

```bash
cd backend
uv run pytest -q
uv run ruff check .
uv run alembic current
cd ..
git diff --check
```

Expected:

```text
362 passed
All checks passed!
Alembic current = 0010
```

若 pytest 仍报告 `ConnectionRefusedError: 127.0.0.1:5432`，回到 Step 2/3 修复 runtime。若数据库或 schema 缺失，创建/迁移 `job_graph_test`；不得把测试改成 SQLite 或跳过 PostgreSQL 约束测试。

- [ ] **Step 5: 确认没有环境产物进入版本控制**

Run:

```bash
git status --short
```

Expected: 没有 `.env`、数据库 dump、容器 volume、真实简历、Session、API Key、pytest cache 或本机 runtime 文件进入 Git。Task 0 不创建 commit。

## Task 1: 为审核岗位定义增加可选 Match Policy，并验证发布透传

**Files:**

- Modify: `backend/app/reviews/schemas.py`
- Modify: `backend/tests/test_review_service.py`
- Modify: `backend/tests/test_graph_service.py`
- No migration

- [ ] **Step 1: 写 RoleDefinitionPayload Match Policy 的 RED 测试**

在 `backend/tests/test_review_service.py` 增加纯 Pydantic 边界测试，并让现有 revised payload 带上匹配策略：

```python
def test_role_definition_payload_accepts_optional_match_policy(review_context):
    payload = _revised_payload(
        review_context,
        match_policy={
            "minimum_education_level": "bachelor",
            "recommended_experience_months": 24,
        },
    )

    assert payload.model_dump(mode="json")["match_policy"] == {
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
    }


@pytest.mark.parametrize(
    ("match_policy", "error_fragment"),
    [
        ({"minimum_education_level": "unknown"}, "minimum_education_level"),
        ({"minimum_education_level": "other"}, "minimum_education_level"),
        ({"recommended_experience_months": -1}, "recommended_experience_months"),
        ({"recommended_experience_months": 601}, "recommended_experience_months"),
    ],
)
def test_role_definition_payload_rejects_invalid_match_policy(
    review_context,
    match_policy,
    error_fragment,
):
    with pytest.raises(ValidationError) as error:
        _revised_payload(review_context, match_policy=match_policy)

    assert error_fragment in str(error.value)
```

同时覆盖以下合法历史形状：

```python
assert _revised_payload(review_context).match_policy is None
assert _revised_payload(
    review_context,
    match_policy={"minimum_education_level": "master"},
).match_policy.recommended_experience_months is None
assert _revised_payload(
    review_context,
    match_policy={"recommended_experience_months": 0},
).match_policy.minimum_education_level is None
```

Run:

```bash
cd backend
uv run pytest tests/test_review_service.py -q
```

Expected: RED，`RoleDefinitionPayload` 当前不保存/校验 `match_policy`，测试失败。

- [ ] **Step 2: 用最小 Pydantic 结构实现 Match Policy**

在 `backend/app/reviews/schemas.py` 增加：

```python
class MatchPolicy(BaseModel):
    minimum_education_level: Literal[
        "high_school",
        "associate",
        "bachelor",
        "master",
        "doctor",
    ] | None = None
    recommended_experience_months: int | None = Field(
        default=None,
        ge=0,
        le=600,
    )


class RoleDefinitionPayload(BaseModel):
    # 保留既有字段
    match_policy: MatchPolicy | None = None
```

不增加数据库字段：策略继续保存在 `JobRole.definition_payload` JSONB 和 Graph Version snapshot 中。缺省策略不回填历史 JobRole。

- [ ] **Step 3: 写 Graph publication 透传 RED/GREEN 断言**

修改 `backend/tests/test_graph_service.py::_context` 的 `proposal.proposed_payload`，加入：

```python
"match_policy": {
    "minimum_education_level": "bachelor",
    "recommended_experience_months": 24,
},
```

在 draft 和 publish 成功测试分别断言：

```python
assert version.snapshot["definition"]["match_policy"] == {
    "minimum_education_level": "bachelor",
    "recommended_experience_months": 24,
}
assert role.definition_payload["match_policy"] == {
    "minimum_education_level": "bachelor",
    "recommended_experience_months": 24,
}
```

Run:

```bash
cd backend
uv run pytest tests/test_review_service.py tests/test_graph_service.py -q
uv run ruff check app/reviews/schemas.py tests/test_review_service.py tests/test_graph_service.py
```

Expected: GREEN；既有 payload 不带 `match_policy` 时继续合法，带策略时审核、Graph snapshot 和正式 JobRole 原样保存。

- [ ] **Step 4: 提交 Task 1**

Run:

```bash
git add backend/app/reviews/schemas.py \
  backend/tests/test_review_service.py \
  backend/tests/test_graph_service.py
git diff --cached --check
git commit -m "feat: add job role match policy"
```

## Task 2: 建立 MatchRun/MatchResult ORM、Alembic 0011 和数据库约束测试

**Files:**

- Create: `backend/app/matching/__init__.py`
- Create: `backend/app/matching/models.py`
- Create: `backend/alembic/versions/0011_create_match_tables.py`
- Create: `backend/tests/matching_fixtures.py`
- Create: `backend/tests/test_matching_database_constraints.py`
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: 创建最小 Matching 数据 fixture 构造器**

在 `backend/tests/matching_fixtures.py` 只实现后续测试真正复用的构造器：

```text
make_matching_user
make_matching_resume
make_confirmed_profile
make_matching_catalog
make_match_run
make_match_result
```

约束：

- 使用 `uuid4()` 隔离并行/重复运行；
- Resume 继续通过 `StoredFile`、`ProcessingRun`、`ResumeProfile` 的真实 FK 建立；
- published Graph Version 通过最小 `GraphChangeCandidate` 建立真实 FK；
- Catalog Version 同时建立 job_role 和 capability items；
- 默认生成两个 required Capability 和一个 bonus Capability；
- 不调用 Neo4j publisher，不创建 Celery task，不提交事务，只 `flush()`；
- helper 返回 dataclass 或 `SimpleNamespace`，不引入 fixture plugin 或生产 seed 框架。

- [ ] **Step 2: 写 MatchRun/MatchResult 数据库约束 RED 测试**

在 `backend/tests/test_matching_database_constraints.py` 增加：

```text
test_valid_match_run_and_result_flush
test_match_run_natural_key_is_unique
test_match_run_counts_must_be_non_negative
test_match_run_level_counts_must_equal_result_count
test_match_run_weight_snapshot_must_be_object
test_match_result_job_role_is_unique_per_run
test_match_result_rank_is_unique_per_run
test_match_result_rank_must_be_positive
test_match_result_score_must_be_bounded
test_match_result_level_must_be_known
test_match_result_json_shapes_are_enforced
```

每个失败测试使用现有 PostgreSQL savepoint 模式隔离：

```python
await db_session.flush()
with pytest.raises(IntegrityError):
    await db_session.flush()
await db_session.rollback()
```

JSONB 形状至少分别打破一次：

```text
weight_snapshot = []
dimension_scores = []
matched_capabilities = {}
missing_capabilities = {}
gap_summary = []
job_role_snapshot = []
```

Run:

```bash
cd backend
uv run pytest tests/test_matching_database_constraints.py -q
```

Expected: RED，`app.matching.models` 和两张表尚不存在。

- [ ] **Step 3: 实现最小 ORM 模型**

在 `backend/app/matching/models.py` 定义：

```text
MatchRun
  id UUID primary key
  owner_user_id FK users.id not null
  resume_id FK resumes.id not null
  resume_profile_id FK resume_profiles.id not null
  graph_version_id FK graph_versions.id not null
  catalog_version_id FK catalog_versions.id not null
  weight_version String(40) not null
  weight_snapshot JSONB object not null
  result_count/high_count/medium_count/low_count Integer not null
  created_at from CreatedAtMixin

MatchResult
  match_run_id FK match_runs.id ON DELETE CASCADE, composite primary key
  job_role_id FK job_roles.id, composite primary key
  rank Integer not null
  total_score Numeric(6,2) not null
  match_level String(20) not null
  dimension_scores JSONB object not null
  matched_capabilities JSONB array not null
  missing_capabilities JSONB array not null
  gap_summary JSONB object not null
  job_role_snapshot JSONB object not null
  created_at from CreatedAtMixin
```

精确约束和索引：

```text
UNIQUE (resume_profile_id, graph_version_id, weight_version)
  named uq_match_runs_profile_graph_weight
CHECK result_count/high_count/medium_count/low_count >= 0
CHECK high_count + medium_count + low_count = result_count
CHECK jsonb_typeof(weight_snapshot) = 'object'
INDEX (owner_user_id, created_at DESC)
INDEX (resume_id, created_at DESC)

PRIMARY KEY (match_run_id, job_role_id)
UNIQUE (match_run_id, rank)
CHECK rank >= 1
CHECK total_score BETWEEN 0 AND 100
CHECK match_level IN ('high','medium','low')
CHECK each JSONB column has its specified object/array shape
```

不增加 ORM relationship、通用 base class、status、updated_at、completed_at、error、soft delete 或 version counter。

- [ ] **Step 4: 创建 Alembic 0011，并让 metadata 能发现模型**

在 `backend/alembic/env.py` 增加：

```python
import app.matching.models  # noqa: F401
```

创建 `backend/alembic/versions/0011_create_match_tables.py`：

```text
revision = "0011"
down_revision = "0010"

upgrade order:
  create match_runs
  create match_run indexes
  create match_results
  create match_result unique rank index/constraint

downgrade order:
  drop match_results
  drop match_runs
```

迁移必须显式包含所有 FK、CHECK、UNIQUE、JSONB、Numeric(6,2) 和 descending indexes；不依赖运行时 `create_all()`。

- [ ] **Step 5: 执行迁移和约束 GREEN 验证**

Run:

```bash
docker compose run --rm migrate
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test \
  migrate
cd backend
uv run pytest tests/test_matching_database_constraints.py -q
uv run ruff check app/matching/models.py tests/matching_fixtures.py \
  tests/test_matching_database_constraints.py alembic/versions/0011_create_match_tables.py
uv run alembic current
```

Expected: GREEN；primary/test database 都在 `0011`，所有有效和非法形状测试符合预期。

- [ ] **Step 6: 提交 Task 2**

Run:

```bash
git add backend/app/matching/__init__.py \
  backend/app/matching/models.py \
  backend/alembic/env.py \
  backend/alembic/versions/0011_create_match_tables.py \
  backend/tests/matching_fixtures.py \
  backend/tests/test_matching_database_constraints.py
git diff --cached --check
git commit -m "feat: persist applicant match runs"
```

## Task 3: 实现纯 Decimal 五维评分、快照和稳定排序

**Files:**

- Create: `backend/app/matching/scoring.py`
- Create: `backend/tests/test_matching_scoring.py`
- No database access

- [ ] **Step 1: 写固定权重、证据因子和快照 RED 测试**

在 `backend/tests/test_matching_scoring.py` 断言：

```python
assert WEIGHT_VERSION == "match_weights_v1"
assert WEIGHTS == {
    "required_skill_coverage": Decimal("0.55"),
    "bonus_skill_coverage": Decimal("0.10"),
    "skill_evidence_quality": Decimal("0.15"),
    "experience": Decimal("0.15"),
    "education": Decimal("0.05"),
}
assert EVIDENCE_FACTORS == {
    "mention": Decimal("0.40"),
    "project": Decimal("0.70"),
    "work": Decimal("1.00"),
}
assert weight_snapshot() == {
    "algorithm": "exact_capability_match_v1",
    "weights": {
        "required_skill_coverage": 0.55,
        "bonus_skill_coverage": 0.10,
        "skill_evidence_quality": 0.15,
        "experience": 0.15,
        "education": 0.05,
    },
    "evidence_factors": {
        "mention": 0.40,
        "project": 0.70,
        "work": 1.00,
    },
    "education_ranks": {
        "high_school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "doctor": 5,
    },
    "match_levels": {
        "high_minimum": 75.00,
        "medium_minimum": 50.00,
    },
    "rounding": "ROUND_HALF_UP_2DP",
}
```

实现时内部常量使用 `Decimal`；`weight_snapshot()` 只在写入 JSONB 边界把这些有限小数转换成 JSON number。浮点值不返回评分公式参与计算，测试同时断言持久化快照结构与设计文档一致。

Run:

```bash
cd backend
uv run pytest tests/test_matching_scoring.py -q
```

Expected: RED，scoring 模块尚不存在。

- [ ] **Step 2: 写技能覆盖和证据质量 RED 测试**

覆盖：

```text
required importance 加权覆盖率
bonus importance 加权覆盖率
没有 bonus → 100.00/not_required
matched required + bonus 才进入 evidence 分母
mention/project/work → 0.40/0.70/1.00
没有 matched capability → 0.00/no_matched_skill
required 列表为空或 total importance <= 0 → MatchCatalogInconsistent
存在 bonus 且 total importance <= 0 → MatchCatalogInconsistent
```

手算样例：

```text
required: Python 1.0 matched(work), PyTorch 1.0 matched(project), Kubernetes 0.5 missing
bonus:    Docker 0.5 matched(mention), MLOps 0.5 missing

required coverage = 2.0 / 2.5 * 100 = 80.00
bonus coverage    = 0.5 / 1.0 * 100 = 50.00
evidence quality  = (1.0*1.0 + 1.0*0.7 + 0.5*0.4) / 2.5 * 100 = 76.00
```

同时断言 `dimension_scores` 中 count、importance、status 和分数均完整。

- [ ] **Step 3: 写经验、学历、舍入和等级 RED 测试**

经验矩阵：

```text
recommended null/0 → 100.00/not_required
candidate null     → 0.00/unknown
candidate 0        → 0.00/unmet
18 / 24            → 75.00/partial
24 / 24            → 100.00/satisfied
36 / 24            → 100.00/satisfied
```

学历矩阵：

```text
minimum null                   → 100.00/not_required
candidate null/other/unknown   → 0.00/unknown
associate / bachelor           → 66.67/partial
bachelor / bachelor            → 100.00/satisfied
master / bachelor              → 100.00/satisfied
```

舍入和等级：

```python
assert quantize_score(Decimal("66.665")) == Decimal("66.67")
assert match_level(Decimal("49.99")) == "low"
assert match_level(Decimal("50.00")) == "medium"
assert match_level(Decimal("74.99")) == "medium"
assert match_level(Decimal("75.00")) == "high"
```

- [ ] **Step 4: 写完整总分、能力快照和 tie-break RED 测试**

完整样例继续使用 Step 2 数据，并设置：

```text
candidate experience = 18 months
recommended experience = 24 months
candidate education = associate
minimum education = bachelor

total =
  80.00 * 0.55
+ 50.00 * 0.10
+ 76.00 * 0.15
+ 75.00 * 0.15
+ (Decimal("200") / Decimal("3")) * 0.05
= 74.98 after final ROUND_HALF_UP
level = medium
```

断言：

- 总分使用未舍入维度值计算，最后统一两位小数；
- matched 能力按 requirement type、importance DESC、name.casefold、UUID 排序；
- missing 能力使用同一稳定顺序；
- matched snapshot 保留 ResumeSkill id、raw name、mapping method、evidence strength/factor/quote；
- missing snapshot 保留 capability type 和 Domain；
- gap summary 四个计数字段准确；
- 相同总分按 8 项已确认排序键稳定排序并从 1 连续赋 rank。

- [ ] **Step 5: 实现最小纯评分模块**

在 `backend/app/matching/scoring.py` 使用标准库 `dataclass`、`Decimal`、`ROUND_HALF_UP`、`UUID` 和类型别名实现：

```text
WEIGHT_VERSION
WEIGHTS
EVIDENCE_FACTORS
EDUCATION_RANKS
MATCH_LEVEL_THRESHOLDS
weight_snapshot()
quantize_score()
match_level()
score_job_role()
rank_scored_job_roles()
```

允许定义少量只为上述纯函数传参/返回所需的 dataclass：

```text
ProfileSkillInput
CapabilityRequirementInput
JobRoleMatchInput
ScoredJobRole
```

不定义 interface、abstract base class、strategy registry、plugin、provider 或可热更新权重。目录异常使用 scoring 模块自己的轻量异常 `MatchCatalogInconsistent`，由 Service 统一映射为 `APIError(503, "MATCH_CATALOG_INCONSISTENT", "岗位能力目录不一致")`，避免纯模块依赖 FastAPI/业务错误类型。

- [ ] **Step 6: 执行纯逻辑 GREEN 验证**

Run:

```bash
cd backend
uv run pytest tests/test_matching_scoring.py -q
uv run ruff check app/matching/scoring.py tests/test_matching_scoring.py
```

Expected: GREEN；测试无需连接 Neo4j、Redis、LLM、Algorithm Service，也不执行数据库查询。

- [ ] **Step 7: 提交 Task 3**

Run:

```bash
git add backend/app/matching/scoring.py backend/tests/test_matching_scoring.py
git diff --cached --check
git commit -m "feat: implement deterministic match scoring"
```

## Task 4: 批量加载当前正式目录和 confirmed Profile 匹配上下文

**Files:**

- Create: `backend/app/matching/service.py`
- Create: `backend/tests/test_matching_service.py`
- Modify: `backend/tests/matching_fixtures.py`

- [ ] **Step 1: 扩充 Matching fixture 为两个岗位、版本水位和映射技能**

在 `backend/tests/matching_fixtures.py` 增加一个 `build_matching_context(db_session, **overrides)`，默认返回：

```text
applicant owner
second applicant
admin
hr
active Domain
five active Capabilities
two active JobRoles
JobRole A: 2 required + 1 bonus + bachelor + 24 months
JobRole B: 2 required + no bonus + no education/experience policy
current published CatalogVersion + complete CatalogVersionItem
current published GraphVersion pointing to that CatalogVersion
ready Resume + one confirmed Profile
mapped ResumeSkills with work/project/mention evidence
```

fixture 只 `flush()`，测试决定何时调用 Service commit。它必须允许覆盖：

```text
resume owner
resume parse_status
profile status
profile education/experience
graph/catalog current status
job role/capability active status
catalog item membership
required/bonus importance
definition_payload.match_policy
```

- [ ] **Step 2: 写权限、Resume 行锁和 confirmed Profile 选择 RED 测试**

在 `backend/tests/test_matching_service.py` 增加：

```text
test_load_context_allows_owner_and_locks_resume
test_load_context_allows_admin_for_applicant_resume
test_load_context_rejects_hr_with_role_not_allowed
test_load_context_hides_other_applicant_resume
test_load_context_rejects_archived_resume
test_load_context_requires_confirmed_profile
test_load_context_ignores_candidate_draft_and_superseded_profiles
```

精确错误：

```text
HR                              → 403 ROLE_NOT_ALLOWED
other applicant/nonexistent    → 404 RESOURCE_NOT_OWNED
archived                       → 409 RESUME_ARCHIVED
no confirmed profile           → 409 RESUME_PROFILE_NOT_CONFIRMED
```

Run:

```bash
cd backend
uv run pytest tests/test_matching_service.py -q
```

Expected: RED，Matching Service 尚未实现。

- [ ] **Step 3: 写发布水位和 Catalog 成员 RED 测试**

覆盖：

```text
current published GraphVersion 精确选择
GraphVersion 缺失 → 404 GRAPH_VERSION_NOT_PUBLISHED
GraphVersion.catalog_version_id 缺失/非 published/非 current
  → 503 MATCH_CATALOG_INCONSISTENT
只读取 current CatalogVersionItem 中 active JobRole
当前 Catalog 无正式岗位 → 409 MATCH_JOB_ROLE_NOT_AVAILABLE
只把 active、Domain active 且属于 Catalog 的 Capability 作为有效关系
inactive 或 Catalog 外 Capability relation 不参与评分
过滤无效关系后，正式 JobRole 无有效 required relation
  → 503 MATCH_CATALOG_INCONSISTENT
required importance 总和 <= 0
  → 503 MATCH_CATALOG_INCONSISTENT
存在 bonus 但 bonus importance 总和 <= 0
  → 503 MATCH_CATALOG_INCONSISTENT
```

测试明确证明 `GraphVersion.snapshot` 中即使只含单岗位，Service 仍从 CatalogVersionItem 返回两个正式岗位；不得把 snapshot 误用为完整集合。

- [ ] **Step 4: 写 Profile mapped skill 精确读取 RED 测试**

覆盖：

```text
mapping_status=mapped 且 capability_id 非空才进入输入
unmapped skill 不参与
其他 Profile 的 mapped skill 不参与
同一 capability_id 只出现一次（数据库唯一约束已有保障）
evidence_strength/mapping_method/raw_name/evidence_quote 原样进入 ProfileSkillInput
confirmed Profile 没有 mapped skill 时返回空映射，不报错
```

- [ ] **Step 5: 实现最小批量查询上下文**

在 `backend/app/matching/service.py` 实现：

```text
require_matching_reader(actor)
load_match_watermark(db, actor, resume_id)
load_scoring_inputs(db, watermark)
```

实现顺序：

1. `require_matching_reader` 只允许 `applicant`、`admin`；HR 立即 403；
2. 复用 `get_visible_resume(db, resume_id, actor, for_update=True)` 锁 Resume；
3. archived Resume 返回 409；
4. 单查询选择该 Resume 的 `status=confirmed` Profile；
5. 用一次 `GraphVersion JOIN CatalogVersion` 查询选择 current published GraphVersion 及其同 ID 水位 CatalogVersion；
6. 同一查询验证 CatalogVersion 也是 `status=published AND is_current=true`，Graph 存在但 join 不成立时单独判定为目录不一致；
7. `load_match_watermark` 返回 Resume、Profile、Graph 和 Catalog 水位，不读取全部岗位；
8. 仅在没有可复用 MatchRun 时调用 `load_scoring_inputs`；
9. 批量读取 Catalog 的 job_role/capability item id 集合；
10. 批量读取 JobRole + Domain；
11. 批量读取所有相关 JobRoleCapability + Capability + Capability Domain；
12. 批量读取 confirmed Profile mapped ResumeSkill；
13. 构造 scoring dataclass，不对每个岗位单独查询。

岗位 match policy 只解析 `definition_payload.get("match_policy")`：

```text
missing/null → minimum education and recommended months both None
valid object → use MatchPolicy validation
invalid existing JSON → 503 MATCH_CATALOG_INCONSISTENT
recommended_experience_months=0 → scoring treats as not_required
```

不重新验证整份历史 `RoleDefinitionPayload`，避免把旧岗位缺少当前非匹配字段误判为目录故障。

- [ ] **Step 6: 执行上下文加载 GREEN 验证**

Run:

```bash
cd backend
uv run pytest tests/test_matching_service.py -q -k "context or catalog or profile"
uv run ruff check app/matching/service.py tests/matching_fixtures.py \
  tests/test_matching_service.py
```

Expected: GREEN；SQL 日志/测试结构能确认是固定数量批量查询，没有 per-role N+1，也没有 Neo4j/Redis/LLM 调用。

- [ ] **Step 7: 提交 Task 4**

Run:

```bash
git add backend/app/matching/service.py \
  backend/tests/matching_fixtures.py \
  backend/tests/test_matching_service.py
git diff --cached --check
git commit -m "feat: load current matching catalog"
```

## Task 5: 实现同步计算、自然幂等、原子持久化和审计

**Files:**

- Modify: `backend/app/matching/service.py`
- Modify: `backend/tests/test_matching_service.py`

- [ ] **Step 1: 写新建 Match Run 的 RED 集成测试**

增加 `test_create_recommendations_persists_complete_atomic_run`，调用：

```python
result = await create_or_reuse_recommendations(
    db_session,
    actor=context.applicant,
    resume_id=context.resume.id,
    request_id="matching-create",
    ip_address="127.0.0.1",
)
```

断言：

```text
reused is False
MatchRun owner_user_id = Resume.owner_user_id，而不是执行 Admin id
resume/profile/graph/catalog/weight version 水位准确
weight_snapshot 完整
result_count = 当前 Catalog 全部岗位数
high_count + medium_count + low_count = result_count
数据库保存所有 MatchResult，不只 Top 20
rank 从 1 连续且与 scoring 稳定排序一致
每个 Result 保存 dimension/matched/missing/gap/job role snapshots
只新增一条 job_recommendation.run.create AuditLog
Audit metadata 包含所有输入水位和 result_count
```

Run:

```bash
cd backend
uv run pytest tests/test_matching_service.py -q -k "persists_complete_atomic_run"
```

Expected: RED，create function 尚不存在。

- [ ] **Step 2: 写合法低匹配和 Top 20 边界 RED 测试**

覆盖：

```text
confirmed Profile 没有 mapped capability 仍成功
required/bonus coverage 和 evidence 按设计为 0/0/0
experience/education 继续单独计算
创建 21 个正式岗位时保存 21 条结果
Service 的 POST 返回数据只组装 rank 1..20
无 bonus 岗位 bonus score=100/not_required
```

- [ ] **Step 3: 写自然幂等和版本变化 RED 测试**

覆盖：

```text
相同 resume_profile_id + graph_version_id + match_weights_v1
  → 同一个 MatchRun，reused=True，不重复 MatchResult
新 confirmed Profile
  → 新 MatchRun
新 current GraphVersion
  → 新 MatchRun
已有相同 Profile/Graph 但 weight_version=legacy_test_version 的历史 Run
  → 当前 match_weights_v1 创建新 MatchRun
```

Service 和 Router 都不暴露 weight version 参数；生产实现只读取代码常量 `WEIGHT_VERSION`。测试通过预置一个不同版本的历史 Run，证明自然键会区分版本，而不是给生产函数增加测试专用配置口。

- [ ] **Step 4: 写事务回滚和唯一竞争恢复 RED 测试**

原子性测试在结果写入阶段制造一个确定性异常，随后断言：

```text
MatchRun count unchanged
MatchResult count unchanged
job_recommendation.run.create AuditLog count unchanged
session 已 rollback，可继续查询
```

并发竞争不引入时间 sleep 或 Redis。用 PostgreSQL 唯一约束和两个独立 AsyncSession 发出相同自然键请求，断言最终：

```text
两次调用返回同一 MatchRun id
一个 reused=False，一个 reused=True
数据库只有一个 MatchRun
结果数量完整，不存在部分结果
```

如果测试环境的外层 transaction fixture 无法表达两个真实连接，则为该测试单独创建两个 `AsyncSession`，完成后只删除该测试创建的 UUID 精确资源；不得 truncate 全表或重建数据库。

- [ ] **Step 5: 实现创建/复用事务**

在 `backend/app/matching/service.py` 实现：

```text
create_or_reuse_recommendations(
    db,
    actor,
    resume_id,
    request_id,
    ip_address,
)
```

主流程固定为：

1. 加载并锁定 Resume/Profile/Graph/Catalog watermark；
2. 使用代码常量 `WEIGHT_VERSION` 按自然键查询已有 MatchRun；
3. 已存在：记录 `job_recommendation.run.reuse`，commit，返回 reused；
4. 不存在：批量加载 Profile skills 和当前 Catalog 全部岗位技能；
5. 纯函数评分全部岗位；
6. 稳定排序并统计等级；
7. `db.add(MatchRun)` 后 `flush()`，让唯一约束在写 Results 前仲裁；
8. `db.add_all(match_result_rows)`；
9. 记录 `job_recommendation.run.create`；
10. 单次 commit；
11. 任何非预期错误 rollback 后原样抛出；
12. 目录异常 rollback 后映射 `503 MATCH_CATALOG_INCONSISTENT`。

唯一竞争恢复只识别自然键约束名：

```text
uq_match_runs_profile_graph_weight
```

捕获该 `IntegrityError` 后：

1. rollback 失败事务；
2. 按相同自然键读取胜出的完整 Run；
3. 记录 reuse AuditLog 并 commit；
4. 返回 `reused=True`。

其他 FK、CHECK、JSONB 或 rank 唯一错误必须继续抛出，不能伪装成复用成功。由于 PostgreSQL 唯一检查会等待竞争事务结束，不增加 sleep、轮询、Redis lock 或 advisory lock。

- [ ] **Step 6: 实现不可变快照持久化**

每个 MatchResult 使用 scoring 输出和上下文构造：

```text
dimension_scores
matched_capabilities
missing_capabilities
gap_summary
job_role_snapshot
```

`job_role_snapshot` 必须来自匹配时读取的 JobRole/Domain/definition payload，不得在历史读取时回查当前 JobRole 覆盖它。Decimal 写入 Numeric 列；JSONB 内数值由安全 serializer 转成 JSON number，不用二进制浮点参与计算。

- [ ] **Step 7: 执行 Service GREEN 验证**

Run:

```bash
cd backend
uv run pytest tests/test_matching_scoring.py \
  tests/test_matching_database_constraints.py \
  tests/test_matching_service.py -q
uv run ruff check app/matching tests/test_matching_*.py tests/matching_fixtures.py
```

Expected: GREEN；全部持久化、复用、版本变化、竞争、审计和回滚测试通过。

- [ ] **Step 8: 提交 Task 5**

Run:

```bash
git add backend/app/matching/service.py backend/tests/test_matching_service.py
git diff --cached --check
git commit -m "feat: generate applicant job recommendations"
```

## Task 6: 定义响应 Schema，并实现 Run 历史、结果分页和单岗位明细查询

**Files:**

- Create: `backend/app/matching/schemas.py`
- Modify: `backend/app/matching/service.py`
- Modify: `backend/tests/test_matching_service.py`

- [ ] **Step 1: 写严格请求与响应 shape 的 RED 测试**

在 `backend/tests/test_matching_service.py` 或新增的纯 schema 测试区覆盖：

```text
JobRecommendationCreate 只接受 resume_id
未知字段触发 Pydantic extra_forbidden
MatchRun summary 包含 profile/graph/catalog version_no
列表结果不包含 matched_capabilities/missing_capabilities
单岗位明细包含完整 matched/missing 数组
Decimal 以 JSON number 输出两位业务值
```

请求模型最小定义：

```python
class JobRecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: UUID
```

- [ ] **Step 2: 写 Run 历史列表 RED 测试**

覆盖：

```text
Applicant 只看到 owner_user_id=actor.id 的 Run
Admin 看到全部 Run
HR → 403 ROLE_NOT_ALLOWED
resume_id 可选过滤仍遵守 owner 边界
created_at DESC, id DESC 稳定排序
page>=1, page_size 1..100
total 是过滤后的总数，不是当前页长度
```

所有权隐藏：其他 applicant 的 Run 不出现在列表；直接读取时返回 404。

- [ ] **Step 3: 写 Run 结果分页和单岗位明细 RED 测试**

覆盖：

```text
get_match_run_results 默认 rank ASC
page/page_size 正确切片
total = MatchRun.result_count
不存在/不可见 Run → 404 MATCH_RUN_NOT_FOUND
存在 Run 内不存在 JobRole → 404 MATCH_RESULT_NOT_FOUND
列表只返回 job role summary + dimensions + gap summary
detail 返回 job_role_snapshot + full matched/missing arrays
读取历史只使用 MatchResult snapshots
```

历史快照测试先创建 Run，再修改当前 JobRole name/description/definition，随后断言读取结果仍显示原快照。

- [ ] **Step 4: 实现最小 Pydantic 输出模型**

在 `backend/app/matching/schemas.py` 定义实际响应所需模型，不创建通用 pagination framework：

```text
JobRecommendationCreate
ResumeProfileVersionRef
PublishedVersionRef
MatchRunRead
JobRoleSnapshotRead
MatchResultListItem
MatchResultDetail
MatchResultPage
MatchRunPage
RecommendationCreateData
RecommendationRunData
RecommendationDetailData
```

使用 `Literal` 限制：

```text
match_level: high | medium | low
各 dimension status 使用设计文档允许值
```

JSONB 快照可用边界明确的嵌套 model；不定义跨模块通用 `ApiResponse[T]`，Router 继续复用项目统一的顶层 `data` envelope。

- [ ] **Step 5: 实现可见性和批量响应查询**

在 `backend/app/matching/service.py` 增加：

```text
list_match_runs(db, actor, page, page_size, resume_id=None)
get_visible_match_run(db, actor, match_run_id)
get_match_run_results(db, actor, match_run_id, page, page_size)
get_match_result_detail(db, actor, match_run_id, job_role_id)
```

实现要求：

- `require_matching_reader` 在查询前拒绝 HR；
- Applicant query 直接附加 `owner_user_id == actor.id`，不存在和越权统一 404；
- Admin 不附加 owner filter；
- Run summary 使用 join 一次取得 ResumeProfile、GraphVersion、CatalogVersion 的 version_no；
- 列表用独立 count + page query，不 per-row 回查版本；
- Result 页面按 `rank ASC`；
- 历史 JobRole 信息只读 `job_role_snapshot`；
- 普通 GET 不写 AuditLog、不 commit。

- [ ] **Step 6: 执行查询 GREEN 验证**

Run:

```bash
cd backend
uv run pytest tests/test_matching_service.py -q -k "list or results or detail or snapshot"
uv run ruff check app/matching/schemas.py app/matching/service.py \
  tests/test_matching_service.py
```

Expected: GREEN；权限、分页、排序、快照稳定性和响应 shape 均通过。

- [ ] **Step 7: 提交 Task 6**

Run:

```bash
git add backend/app/matching/schemas.py \
  backend/app/matching/service.py \
  backend/tests/test_matching_service.py
git diff --cached --check
git commit -m "feat: query applicant match history"
```

## Task 7: 接入 FastAPI Router、角色/CSRF 边界和 API 集成测试

**Files:**

- Create: `backend/app/matching/router.py`
- Create: `backend/tests/test_matching_api.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/tests/matching_fixtures.py`

- [ ] **Step 1: 写 POST API RED 测试**

使用真实 login/session/CSRF fixture 覆盖：

```text
Applicant owner POST → 200, reused=false, Top 20
相同 POST → 200, reused=true, same run id
Admin 为 applicant Resume POST → 200
other applicant Resume → 404 RESOURCE_NOT_OWNED
HR → 403 ROLE_NOT_ALLOWED
未登录 → 401 existing auth error
缺失/错误 X-CSRF-Token → 403 CSRF_VALIDATION_FAILED
未知 request field → 422 validation error
archived Resume → 409 RESUME_ARCHIVED
no confirmed Profile → 409 RESUME_PROFILE_NOT_CONFIRMED
no published Graph → 404 GRAPH_VERSION_NOT_PUBLISHED
```

POST 响应精确检查：

```text
data.reused
data.run
data.results.items
data.results.page = 1
data.results.page_size = 20
data.results.total = run.result_count
```

Run:

```bash
cd backend
uv run pytest tests/test_matching_api.py -q
```

Expected: RED，Router 尚未注册，返回 404。

- [ ] **Step 2: 写三个 GET API RED 测试**

覆盖：

```text
GET collection 默认 page=1/page_size=20
GET collection resume_id filter
GET run results 默认按 rank 且不含 full arrays
GET run results page_size=100 合法，101 返回 422
GET single job role detail 含 full arrays
Applicant 越权 Run/Result → 404
Admin 可读任意 Run/Result
HR 三个 GET 全部 → 403 ROLE_NOT_ALLOWED
GET 不要求 CSRF，但要求有效 Session
```

- [ ] **Step 3: 实现最小 Router**

在 `backend/app/matching/router.py` 定义：

```python
router = APIRouter(prefix="/job-recommendations", tags=["job-recommendations"])
```

四个 route：

```text
POST ""                              with DB, Identity, CSRF, Request
GET  ""                              with Query page/page_size/resume_id
GET  "/{match_run_id}"              with Query page/page_size
GET  "/{match_run_id}/job-roles/{job_role_id}"
```

Router 只做：

- 从 Identity 取 actor；
- 把 request id/ip 传给 POST Service；
- 调用 schema `model_dump(mode="json")`；
- 返回统一的顶层 `data` envelope；
- 不持有 SQLAlchemy query、不 commit、不捕获业务 APIError。

在 `backend/app/api/router.py` 增加一次 include：

```python
from app.matching.router import router as matching_router

api_router.include_router(matching_router)
```

- [ ] **Step 4: 验证错误不会泄漏内部实现**

API 测试对 `MATCH_CATALOG_INCONSISTENT` 响应断言只包含：

```text
error.code
error.message
error.request_id
```

响应不得包含 SQL、constraint name、table name、stack trace、Neo4j、Resume extracted text 或其他用户 UUID。

- [ ] **Step 5: 执行 API GREEN 和 Matching 全套验证**

Run:

```bash
cd backend
uv run pytest tests/test_matching_api.py -q
uv run pytest tests/test_matching_scoring.py \
  tests/test_matching_database_constraints.py \
  tests/test_matching_service.py \
  tests/test_matching_api.py -q
uv run ruff check app/matching app/api/router.py tests/test_matching_*.py \
  tests/matching_fixtures.py
```

Expected: GREEN；四个 endpoint、角色、所有权隐藏、CSRF、分页和明细形状全部通过。

- [ ] **Step 6: 提交 Task 7**

Run:

```bash
git add backend/app/matching/router.py \
  backend/app/api/router.py \
  backend/tests/matching_fixtures.py \
  backend/tests/test_matching_api.py
git diff --cached --check
git commit -m "feat: expose applicant recommendation api"
```

## Task 8: 更新 README，回放迁移，运行全量验证并推送实施分支

**Files:**

- Modify: `README.md`
- Verify: all files changed in Tasks 1-7
- No new feature code

- [ ] **Step 1: 更新 README 当前能力与 API 范围**

在开头能力列表增加：

```text
Applicant Job Recommendations：基于 confirmed Profile 和当前正式 Catalog，
使用固定五维规则生成可解释岗位排序、技能差距和不可变历史快照。
```

新增 `### Applicant Job Recommendations`，列出四个 endpoint，并写清：

```text
POST body 只含 resume_id
POST 需要 Session + CSRF
GET 只需要 Session
Applicant 只读本人；Admin 可运营排查；HR 不可访问
同步、确定性、保存全部岗位结果，POST 默认返回 Top 20
PostgreSQL 唯一真相源；不调用 Neo4j/LLM/Algorithm Service/Celery
match_weights_v1 五维权重和证据因子
```

给一个使用 placeholder 的 curl 示例，不写真实 Session、CSRF、Resume UUID 或简历内容。

从 README 的 Resume “当前非目标”中移除已完成的“人岗匹配/推荐、差距分析”，但继续保留成长路径、HR 批量匹配和 Resume 图谱写入为非目标。

- [ ] **Step 2: 运行目标测试、相关回归和全量 pytest**

Run:

```bash
cd backend
uv run pytest tests/test_review_service.py tests/test_graph_service.py -q
uv run pytest tests/test_matching_scoring.py \
  tests/test_matching_database_constraints.py \
  tests/test_matching_service.py \
  tests/test_matching_api.py -q
uv run pytest -q
uv run ruff check .
cd ..
git diff --check
```

Expected:

```text
all targeted tests pass
all existing and new backend tests pass
All checks passed!
git diff --check has no output
```

测试总数以当时 pytest 实际输出为准，不在 README 记录易漂移的固定数量。

- [ ] **Step 3: 在隔离测试数据库回放 Alembic 0011 downgrade/upgrade**

先确认命令只指向 `job_graph_test`：

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  uv run alembic current
DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  uv run alembic downgrade 0010
DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  uv run alembic current
```

Expected:

```text
0011 → 0010 → 0011
```

该回放会删除并重建测试数据库中的 Match 表，只允许对 `job_graph_test` 执行。不得对 primary `job_graph` downgrade，不得 drop database 或 volume。

- [ ] **Step 4: 验证 Compose 配置和 API 镜像构建**

Run:

```bash
docker compose config >/dev/null
docker compose run --rm migrate
docker compose build api
docker compose run --rm api uv run python -c \
  "from app.main import app; assert any(r.path == '/api/v1/job-recommendations' for r in app.routes)"
```

Expected: Compose config 有效，primary database 到 `0011`，API image 构建成功，容器内 Router 已注册。

- [ ] **Step 5: 审计实现边界和依赖变化**

Run:

```bash
rg -n "Celery|delay\(|Neo4j|neo4j|LLM|Responses|Algorithm|LangChain|LangGraph|redis" \
  backend/app/matching backend/tests/test_matching_*.py
git diff 64d0deb -- backend/pyproject.toml backend/uv.lock .env.example compose.yaml
git status --short
```

Expected:

- Matching 生产代码没有外部编排/模型/图数据库调用；测试可在断言说明中出现这些名称；
- `pyproject.toml`、`uv.lock`、`.env.example`、`compose.yaml` 没有变化；
- 工作区只包含本批 README 或尚未提交的预期文件。

- [ ] **Step 6: 提交文档收尾**

Run:

```bash
git add README.md
git diff --cached --check
git commit -m "docs: document applicant recommendations"
```

- [ ] **Step 7: 最终历史和工作区验证**

Run:

```bash
git status --short --branch
git log --oneline --decorate 64d0deb..HEAD
git diff 64d0deb..HEAD --stat
git diff --check 64d0deb..HEAD
```

Expected:

```text
working tree clean
only Tasks 1-8 scoped commits are present after 64d0deb
no whitespace errors
```

- [ ] **Step 8: 推送当前实施分支**

Run:

```bash
git push origin codex/applicant-matching
git rev-parse HEAD
git rev-parse origin/codex/applicant-matching
```

Expected: 两个 revision 相同；不创建 PR、不 merge、不修改其他分支。

## 9. 最终验收矩阵

实施者在完成 Task 8 前逐项核对：

- [ ] Applicant 能为自己的未归档 Resume 创建或复用推荐结果。
- [ ] Admin 能为任意 applicant Resume 创建/查看 Run，Run owner 仍是 Resume owner。
- [ ] HR 对四个 endpoint 全部得到 `403 ROLE_NOT_ALLOWED`。
- [ ] Applicant 越权 Resume、Run、Result 统一隐藏为 404。
- [ ] POST 强制 CSRF 且请求体拒绝未知字段；GET 不要求 CSRF。
- [ ] 只选择当前唯一 confirmed Profile；candidate/draft/superseded 不参与。
- [ ] 只使用 current published Graph Version 对应的 current published Catalog。
- [ ] 完整岗位集合来自 CatalogVersionItem，不来自单岗位 GraphVersion snapshot。
- [ ] Profile 和岗位技能只按相同 `capability_id` 精确匹配。
- [ ] ResumeSkill 的 LLM `confidence` 不参与任何覆盖率、证据质量或总分计算。
- [ ] `match_weights_v1` 权重、因子、学历等级、阈值和舍入规则不可变。
- [ ] 五维分数使用未舍入 Decimal 计算，总分/持久化分数 `ROUND_HALF_UP` 两位。
- [ ] required/bonus/evidence/experience/education 状态和边界符合设计。
- [ ] 没有 mapped skill 是合法低匹配场景，不返回系统错误。
- [ ] 目录无岗位返回 409；目录水位或岗位必备技能不一致返回 503。
- [ ] 稳定排序严格使用 8 项 tie-break，并连续写入 rank。
- [ ] 保存全部正式岗位结果；POST 只返回 Top 20。
- [ ] 相同 Profile + Graph + weight version 自然复用；版本变化创建新 Run。
- [ ] 并发相同请求最终只有一个完整 Run，不需要 Redis/advisory lock。
- [ ] MatchRun、全部 MatchResult 和 create AuditLog 原子提交；失败无残留。
- [ ] 历史读取使用 weight/job role/result snapshots，不被当前主数据修改污染。
- [ ] 列表、结果和明细分页/shape 符合 API 设计。
- [ ] 生产 Matching 调用链不包含 Celery、Redis、Neo4j、LLM 或 Algorithm Service。
- [ ] 不增加依赖、环境变量、Compose service、权重配置表或未请求抽象。
- [ ] Matching 目标测试、全量 pytest、Ruff、Alembic 回放和 API image build 全部通过。

## 10. 已知非验收项

以下内容仍属于后续独立批次，不得为了“看起来更完整”混入本计划：

```text
成长路径与学习资源推荐
HR CandidateRecord 批量匹配
LLM/Algorithm Service 语义补分
项目内容语义质量评分
学历院校层次、专业相关性和证书权重
岗位收藏、比较、导出或删除 Match Run
后台权重管理和在线 A/B 测试
Neo4j 推荐计算或降级回退
```

“人岗匹配准确率 ≥ 90%”不能由合成单元测试证明。该业务指标必须在本功能完成后，使用独立人工标注的 Resume-JobRole 样本集计算；本批只证明公式、数据边界、事务、权限和 API 行为正确，不伪造准确率结论。
