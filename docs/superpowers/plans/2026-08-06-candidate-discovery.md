# Candidate Skill Combination Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可运行、可解释、可追溯的候选技能组合发现闭环：管理员选择已处理的市场 JD 批次，系统把来源标签确定性映射到 active Capability，挖掘技能对共现候选，并向管理员和 HR 展示候选分数及支持 JD 证据。

**Architecture:** 延续 FastAPI 模块化单体、PostgreSQL 唯一事实源和 Celery/Redis Processing Run。第一版只实现标准库确定性基线：`source_tags -> canonical/alias exact mapping -> pair co-occurrence -> evidence-backed candidates`；不会调用 Algorithm Service、LLM 或 Neo4j，也不会把候选直接写成正式 Job Role。所有输入、映射、分数、证据和版本都落 PostgreSQL，未来语义聚类只需替换候选生成阶段。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 async、Alembic、PostgreSQL 16、Celery/Redis、Pydantic、pytest、Ruff、Python stdlib `unicodedata` / `itertools` / `collections`。

---

## 1. 范围与明确不做事项

本批实现：

- 已处理 `ImportBatch` 的多批次选择与校验。
- 当前 `NormalizedJobPosting` 与 `RawJobPosting.source_tags` 的技能映射快照。
- active Capability 标准名精确映射、active Alias 精确映射、未映射保留。
- 两两技能共现、支持 JD 数、公司数、来源数和质量证据。
- 确定性 support/diversity/coherence/evidence/overall 分数。
- Celery 异步执行、PostgreSQL 进度、取消和失败状态。
- admin 创建 Discovery Run；admin/hr 查询候选、详情和证据。
- 页面/API 文案始终称为“候选技能组合”，附带非市场趋势声明。

本批明确跳过：

- Algorithm Service `/cluster-skills`。
- Embedding、pgvector、语义聚类和向量索引。
- LLM 生成岗位名称、职责和应用场景。
- 与 Neo4j 岗位画像比较，因此 `novelty_score=0` 且标记 `not_evaluated`。
- HR feedback、Graph Change Candidate、人工审核和正式发布。
- 三技能及以上频繁项集；第一版只挖掘技能对。
- 任意算法参数透传；只暴露稳定白名单。

这些延期项不创建空 Service、空 Router 或占位表。等确定性基线在真实数据上有可用候选后再加。

## 2. 数据和算法契约

### 2.1 标签规范化与 Catalog 映射

标签规范化固定为：

```python
def normalize_skill_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return " ".join(normalized.split())
```

映射顺序：

1. `Capability.status == "active"` 的 `canonical_name` 精确匹配。
2. `CapabilityAlias.status == "active"` 的 `alias` 精确匹配。
3. 其余标签保存为 `unmapped`，不得创建 Capability。

映射结果写入 `job_analysis_profiles` 和 `job_skill_candidates`。同一 JD、同一 `extraction_version=source_tags_v1` 重复运行时复用已有 Profile，不重复插入。

### 2.2 候选生成

输入 JD 必须同时满足：

- 来自请求指定且状态为 `processed` 或 `partial` 的批次。
- `NormalizedJobPosting.is_current=true`。
- `NormalizedJobPosting.duplicate_of_id IS NULL`。
- `quality_score >= minimum_quality_score`。
- 至少映射到两个不同的 active Capability。

对每条合格 JD 的 Capability ID 排序去重后，用 `itertools.combinations(ids, 2)` 生成技能对。技能对支持 JD 数达到 `minimum_support_jobs`、来源数达到 `minimum_source_count` 才能形成 Candidate。

### 2.3 确定性分数

所有分数四舍五入到四位小数并限制在 `[0, 1]`：

```python
support_score = pair_job_count / eligible_job_count
source_diversity = pair_source_count / eligible_source_count
company_diversity = pair_company_count / pair_job_count
diversity_score = (source_diversity + company_diversity) / 2
coherence_score = pair_job_count / (
    skill_a_job_count + skill_b_job_count - pair_job_count
)
evidence_score = average(normalized_job.quality_score) / 100
novelty_score = 0
overall_candidate_score = (
    support_score * 0.35
    + diversity_score * 0.20
    + coherence_score * 0.25
    + evidence_score * 0.20
)
```

权重和公式版本保存在 `DiscoveryRun.parameters`：

```json
{
  "algorithm": "cooccurrence_pairs_v1",
  "score_weights": {
    "support": 0.35,
    "diversity": 0.20,
    "coherence": 0.25,
    "evidence": 0.20,
    "novelty": 0.0
  }
}
```

### 2.4 API 稳定参数

```json
{
  "batch_ids": ["uuid"],
  "minimum_support_jobs": 3,
  "minimum_source_count": 1,
  "minimum_quality_score": 60,
  "maximum_candidates": 50
}
```

约束：

- `batch_ids`：1 到 20 个、不重复。
- `minimum_support_jobs`：2 到 1000。
- `minimum_source_count`：1 到 10，且不能超过输入数据实际来源数。
- `minimum_quality_score`：0 到 100。
- `maximum_candidates`：1 到 100。

## 3. 文件变更地图

```text
backend/app/discovery/__init__.py                 # 模块标记
backend/app/discovery/models.py                   # 映射、Run、Candidate、Evidence 模型
backend/app/discovery/mining.py                   # 纯函数映射和共现挖掘
backend/app/discovery/schemas.py                  # 创建请求和响应契约
backend/app/discovery/service.py                  # 创建 Run、查询和权限边界
backend/app/discovery/tasks.py                    # Celery 发现任务
backend/app/discovery/router.py                   # /api/v1/discovery-* API
backend/app/api/dependencies.py                   # HR/Admin 只读依赖
backend/app/api/router.py                         # 挂载 Discovery Router
backend/app/worker.py                             # autodiscover app.discovery
backend/alembic/env.py                            # 注册 Discovery metadata
backend/alembic/versions/0007_create_discovery_tables.py
backend/tests/test_discovery_database_constraints.py
backend/tests/test_discovery_mining.py
backend/tests/test_discovery_tasks.py
backend/tests/test_discovery_api.py
README.md                                         # Batch C 使用与边界
```

---

## Task 1: JD 技能映射与 Discovery 数据模型、Migration 0007

**Files:**

- Create: `backend/tests/test_discovery_database_constraints.py`
- Create: `backend/app/discovery/__init__.py`
- Create: `backend/app/discovery/models.py`
- Create: `backend/alembic/versions/0007_create_discovery_tables.py`
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: 写数据库 RED 测试**

创建 `backend/tests/test_discovery_database_constraints.py`，先导入尚不存在的模型：

```python
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    JobAnalysisProfile,
    JobSkillCandidate,
    SkillCombinationCandidate,
)
```

覆盖这些约束：

- `test_profile_version_is_unique_per_job`：同一 `normalized_job_id + extraction_version` 插入第二行时 `flush()` 抛 `IntegrityError`。
- `test_mapped_skill_requires_capability`：`mapping_status=mapped` 且 `capability_id=NULL` 时失败；`unmapped` 且带 Capability 时也失败。
- `test_candidate_scores_stay_between_zero_and_one`：任一分数写入 `1.1` 时失败。
- `test_candidate_name_is_unique_per_run`：同一 Run 内两个相同 `normalized_name` 失败。
- `test_combination_skill_weight_is_bounded`：weight 或 frequency 超界失败。
- `test_evidence_weight_is_bounded`：evidence_weight 超界失败。

每个约束测试都先插入并 flush FK 依赖，再只把被测违规行放在 `pytest.raises(IntegrityError)` 内，避免把插入顺序错误误判为目标约束。

第一轮应在测试收集时得到 `ModuleNotFoundError: app.discovery`。

- [ ] **Step 2: 运行 RED**

```bash
cd backend
uv run pytest tests/test_discovery_database_constraints.py -q
```

预期：Discovery 模块不存在，测试失败。

- [ ] **Step 3: 实现最小模型**

`backend/app/discovery/models.py` 必须定义以下表：

```python
class JobAnalysisProfile(CreatedAtMixin, Base):
    id: UUID
    normalized_job_id: UUID
    extraction_version: str
    status: str
    structured_payload: dict
    validation_errors: list
    created_by_run_id: UUID

class JobSkillCandidate(CreatedAtMixin, Base):
    id: UUID
    analysis_profile_id: UUID
    capability_id: UUID | None
    raw_name: str
    normalized_name: str
    requirement_type: str
    importance: Decimal
    mapping_method: str
    mapping_status: str
    extraction_source: str
    confidence: Decimal

class DiscoveryRun(CreatedAtMixin, Base):
    id: UUID
    processing_run_id: UUID
    input_batch_ids: list[UUID]
    current_catalog_version_id: UUID | None
    algorithm_version: str
    extraction_version: str
    parameters: dict
    status: str
    summary: dict
    created_by_user_id: UUID
    completed_at: datetime | None

class SkillCombinationCandidate(CreatedAtMixin, Base):
    id: UUID
    discovery_run_id: UUID
    suggested_name: str
    normalized_name: str
    definition_payload: dict
    support_job_count: int
    source_count: int
    company_count: int
    support_score: Decimal
    diversity_score: Decimal
    coherence_score: Decimal
    novelty_score: Decimal
    evidence_score: Decimal
    overall_candidate_score: Decimal
    status: str

class CombinationSkill(Base):
    candidate_id: UUID
    capability_id: UUID
    skill_role: str
    weight: Decimal
    frequency: Decimal

class CombinationEvidence(Base):
    candidate_id: UUID
    normalized_job_id: UUID
    evidence_weight: Decimal
    representative: bool
```

关键数据库约束：

```text
UNIQUE job_analysis_profiles(normalized_job_id, extraction_version)
UNIQUE job_skill_candidates(analysis_profile_id, normalized_name)
UNIQUE discovery_runs(processing_run_id)
UNIQUE skill_combination_candidates(discovery_run_id, normalized_name)
CHECK 所有 score/weight/frequency/confidence/importance BETWEEN 0 AND 1
CHECK mapped 等价于 capability_id IS NOT NULL
CHECK status、mapping_method、mapping_status、skill_role 使用固定枚举
PRIMARY KEY combination_skills(candidate_id, capability_id)
PRIMARY KEY combination_evidence(candidate_id, normalized_job_id)
```

- [ ] **Step 4: 生成并验证 Migration 0007**

在 `backend/alembic/env.py` 导入 `app.discovery.models`，生成 Migration：

```bash
cd backend
env \
  APP_ENV=test APP_BASE_URL=http://test \
  DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test \
  REDIS_URL=redis://127.0.0.1:6379/0 \
  NEO4J_URI=bolt://127.0.0.1:7687 NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=job_graph_dev FILE_STORAGE_ROOT=/tmp/job-graph-tests \
  SESSION_SECRET=test-secret-at-least-32-characters \
  CORS_ORIGINS='["http://localhost:3000"]' \
  ALGORITHM_SERVICE_URL=http://127.0.0.1:8001 \
  uv run alembic revision --autogenerate \
    -m "create discovery tables" --rev-id 0007
uv run alembic upgrade head
uv run pytest tests/test_discovery_database_constraints.py -q
uv run alembic check
```

预期：数据库 revision 为 `0007`，约束测试通过，Alembic 无新增操作。

- [ ] **Step 5: 独立提交并推送**

```bash
git add backend/app/discovery backend/alembic/env.py \
  backend/alembic/versions/0007_create_discovery_tables.py \
  backend/tests/test_discovery_database_constraints.py
git commit -m "feat: add candidate discovery schema"
git push -u origin codex/candidate-discovery
```

---

## Task 2: 确定性技能映射与共现挖掘纯函数

**Files:**

- Create: `backend/tests/test_discovery_mining.py`
- Create: `backend/app/discovery/mining.py`

- [ ] **Step 1: 写纯函数 RED 测试**

测试以下公开接口：

```python
from app.discovery.mining import (
    CatalogEntry,
    JobSkillSet,
    build_catalog_index,
    map_skill_labels,
    mine_skill_pairs,
    normalize_skill_label,
)
```

覆盖：

- `test_normalize_skill_label_uses_nfkc_casefold_and_whitespace`：`"  ＰＹＴＨＯＮ  SDK "` 规范化为 `"python sdk"`。
- `test_canonical_name_wins_before_alias`：标准名和别名同时命中时返回 `canonical_exact`。
- `test_only_active_alias_is_mapped`：deprecated/ambiguous Alias 均不进入索引。
- `test_unmapped_label_is_preserved`：未知标签保留 raw/normalized name，Capability 为空。
- `test_duplicate_tags_map_to_one_capability_per_job`：大小写不同的重复 Python 只留下一个 Capability。
- `test_pair_mining_filters_support_and_source_thresholds`：支持数或来源数不足的技能对被过滤。
- `test_pair_scores_match_documented_formula`：用手算小样例精确比较五个分数。
- `test_pair_sort_is_deterministic_and_respects_maximum`：打乱输入后结果相同，并截断到 maximum_candidates。

使用最小样例：3 个 JD 同时包含 Python/自动化测试，2 个包含 SQL；断言 Python + 自动化测试成为候选，低支持组合被过滤。

- [ ] **Step 2: 运行 RED**

```bash
cd backend
uv run pytest tests/test_discovery_mining.py -q
```

预期：`app.discovery.mining` 不存在，测试失败。

- [ ] **Step 3: 实现标准库纯函数**

数据结构固定为不可变 dataclass：

```python
@dataclass(frozen=True, slots=True)
class CatalogEntry:
    capability_id: UUID
    canonical_name: str
    aliases: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SkillMapping:
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    mapping_method: str
    mapping_status: str

@dataclass(frozen=True, slots=True)
class JobSkillSet:
    normalized_job_id: UUID
    source_code: str
    company_name: str | None
    quality_score: Decimal
    capability_ids: tuple[UUID, ...]
```

`mine_skill_pairs()` 返回包含技能 ID、支持 JD ID、计数和全部分数的 `PairCandidate`，不访问数据库、不读取环境变量、不调用网络。

- [ ] **Step 4: 运行 GREEN 和属性边界**

```bash
cd backend
uv run pytest tests/test_discovery_mining.py -q
uv run ruff check app/discovery/mining.py tests/test_discovery_mining.py
```

预期：全部通过；输入顺序改变不影响候选顺序和分数。

- [ ] **Step 5: 独立提交并推送**

```bash
git add backend/app/discovery/mining.py backend/tests/test_discovery_mining.py
git commit -m "feat: mine deterministic skill combinations"
git push origin codex/candidate-discovery
```

---

## Task 3: Discovery Worker 与 Processing Run 生命周期

**Files:**

- Create: `backend/tests/test_discovery_tasks.py`
- Create: `backend/app/discovery/tasks.py`
- Modify: `backend/app/worker.py`

- [ ] **Step 1: 写 Worker RED 测试**

测试用数据库 fixture 创建：

- 一个 admin。
- 两个 processed ImportBatch。
- 4 个 current Normalized Job。
- active Python、自动化测试、SQL Capability 和 active Alias。
- 对应 Raw `source_tags`。
- 一个 pending DiscoveryRun + ProcessingRun。

主路径断言：

```python
async def test_worker_materializes_mapping_and_candidates(
    db_session,
    discovery_context,
):
    processing_run = discovery_context.processing_run
    result = await process_discovery_run(db_session, processing_run.id)
    assert result["candidate_count"] == 1
    assert result["mapped_skill_count"] > 0
    assert result["unmapped_skill_count"] >= 1
```

其余测试：

- `test_worker_reuses_existing_analysis_profile`：执行第二个 Discovery Run 后 Profile 数不增加。
- `test_worker_records_candidate_evidence`：Candidate 的 Evidence JD 集合等于手工构造的支持集合。
- `test_worker_completes_with_zero_candidates`：阈值过高时两个 Run 都 completed，candidate_count 为 0。
- `test_worker_honors_cancel_request`：预先设置 cancel_requested 后状态变为 cancelled 且不写 Candidate。
- `test_worker_is_idempotent_after_completion`：重复调用同一已完成 ProcessingRun 返回原 summary，行数不变化。

- [ ] **Step 2: 运行 RED**

```bash
cd backend
uv run pytest tests/test_discovery_tasks.py -q
```

预期：`app.discovery.tasks` 不存在，测试失败。

- [ ] **Step 3: 实现任务阶段**

`process_discovery_run()` 固定阶段：

```text
loading -> mapping -> mining -> persisting -> completed
```

实现要求：

- Run 开始时设置 `status=running`、`attempt_count += 1`、heartbeat。
- 只查询指定批次、current、非 duplicate、满足质量阈值的 JD。
- Catalog Index 只包含 active Capability 和 active Alias。
- 逐 JD 写或复用 `source_tags_v1` Profile/Skill Candidate。
- 每 100 个 JD commit 一次并检查 `cancel_requested`。
- 候选及 Evidence 在同一事务写入。
- 重试前删除该 DiscoveryRun 已有候选，不删除 Analysis Profile。
- 完成时同步 DiscoveryRun 与 ProcessingRun 状态和 summary。
- 无候选是合法 `completed`，不是失败。
- 没有任何 active Capability 时失败为 `DISCOVERY_NO_ACTIVE_CAPABILITIES`。

注册 Celery Task：

```python
@celery_app.task(name="app.discover_skill_combinations")
def discover_skill_combinations(run_id: str) -> dict:
    return asyncio.run(_run(UUID(run_id)))
```

并把 `app.discovery` 加入 `celery_app.autodiscover_tasks()`。

- [ ] **Step 4: 运行 GREEN 和全量回归**

```bash
cd backend
uv run pytest tests/test_discovery_tasks.py -q
uv run pytest -q
uv run ruff check .
```

- [ ] **Step 5: 独立提交并推送**

```bash
git add backend/app/discovery/tasks.py backend/app/worker.py \
  backend/tests/test_discovery_tasks.py
git commit -m "feat: process candidate discovery runs"
git push origin codex/candidate-discovery
```

---

## Task 4: Discovery 创建、候选详情和证据 API

**Files:**

- Create: `backend/tests/test_discovery_api.py`
- Create: `backend/app/discovery/schemas.py`
- Create: `backend/app/discovery/service.py`
- Create: `backend/app/discovery/router.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: 写 API RED 测试**

覆盖：

- `test_admin_creates_discovery_run_and_enqueues`：返回 202、DiscoveryRun/ProcessingRun 均存在、任务名为 `app.discover_skill_combinations`。
- `test_create_rejects_missing_or_unprocessed_batch`：不存在返回 `DISCOVERY_BATCH_NOT_FOUND`，uploaded/failed 返回 `DISCOVERY_BATCH_NOT_READY`。
- `test_create_rejects_source_threshold_above_actual_sources`：阈值大于实际来源数返回 `DISCOVERY_SOURCE_THRESHOLD_INVALID`。
- `test_hr_cannot_create_run`：返回 403 `ROLE_NOT_ALLOWED`。
- `test_admin_and_hr_can_list_candidates`：两种角色都返回 200 和相同 Candidate ID。
- `test_applicant_cannot_view_candidates`：返回 403，不返回候选名称或分数。
- `test_candidate_detail_includes_disclaimer_and_skills`：详情有两个技能、全部分数、`not_evaluated` 和固定 disclaimer。
- `test_evidence_hides_raw_payload_and_returns_traceable_fields`：Evidence 有岗位、公司、来源、日期、质量分、URL，但没有 `raw_payload`、`raw_text`、`normalized_text`。

- [ ] **Step 2: 运行 RED**

```bash
cd backend
uv run pytest tests/test_discovery_api.py -q
```

预期：路由不存在，POST/GET 返回 404。

- [ ] **Step 3: 实现最小 Schema 和 Service**

`DiscoveryRunCreate`：

```python
class DiscoveryRunCreate(BaseModel):
    batch_ids: list[UUID] = Field(min_length=1, max_length=20)
    minimum_support_jobs: int = Field(default=3, ge=2, le=1000)
    minimum_source_count: int = Field(default=1, ge=1, le=10)
    minimum_quality_score: int = Field(default=60, ge=0, le=100)
    maximum_candidates: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def unique_batches(self):
        if len(self.batch_ids) != len(set(self.batch_ids)):
            raise ValueError("batch_ids must be unique")
        return self
```

创建接口：

```text
POST /api/v1/discovery-runs
role: admin + CSRF
response: 202 {resource_id, run_id, status, poll_url}
```

查询接口：

```text
GET /api/v1/discovery-runs
GET /api/v1/discovery-runs/{id}
GET /api/v1/discovery-candidates
GET /api/v1/discovery-candidates/{id}
GET /api/v1/discovery-candidates/{id}/evidence
role: admin or hr
```

稳定错误码：

```text
DISCOVERY_BATCH_NOT_FOUND
DISCOVERY_BATCH_NOT_READY
DISCOVERY_SOURCE_THRESHOLD_INVALID
DISCOVERY_NO_ACTIVE_CAPABILITIES
DISCOVERY_RUN_NOT_FOUND
DISCOVERY_CANDIDATE_NOT_FOUND
```

详情必须包含：

```json
{
  "label": "候选技能组合",
  "disclaimer": "该结果是候选技能组合，不代表已经确认的长期市场趋势",
  "novelty_status": "not_evaluated"
}
```

Evidence 只返回 normalized/raw 的必要摘要：岗位名、公司、来源、发布日期、采集时间、质量分、来源 URL；不返回 `raw_payload` 和完整正文。

- [ ] **Step 4: 运行 GREEN 和权限回归**

```bash
cd backend
uv run pytest tests/test_discovery_api.py -q
uv run pytest tests/test_auth.py tests/test_processing_runs.py -q
uv run pytest -q
uv run ruff check .
```

- [ ] **Step 5: 独立提交并推送**

```bash
git add backend/app/api backend/app/discovery backend/tests/test_discovery_api.py
git commit -m "feat: add candidate discovery APIs"
git push origin codex/candidate-discovery
```

---

## Task 5: 真实样例验收、README 与最终门禁

**Files:**

- Modify: `backend/tests/test_discovery_tasks.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-06-candidate-discovery.md`

- [ ] **Step 1: 增加真实智联样例验收**

复用 `backend/tests/fixtures/zhilian_sample.tsv` 完成导入，在测试内创建一组与真实 `tech_tags` 对应的 active Capability，例如：

```text
Python
Java
自动化测试
功能测试
性能测试
软件测试
测试开发
```

启动 Discovery Run，断言：

- 输入 307 行不会产生未捕获异常。
- 形成至少 1 个满足阈值的候选技能对。
- 每个 Candidate 至少有 2 个 Capability 和 `minimum_support_jobs` 条 Evidence。
- Evidence 能回溯到 Raw Job 的 `source_code`、`source_url` 和批次。
- 候选 `novelty_score == 0` 且 `novelty_status=not_evaluated`。
- 未映射标签只进入 `JobSkillCandidate(mapping_status=unmapped)`，不会创建 Capability。

- [ ] **Step 2: 更新 README**

增加：

- Batch C API 列表。
- Catalog 必须先导入 active Capability 的前置条件。
- 创建 Discovery Run 的 curl 示例。
- Processing Run polling 和候选查询示例。
- 确定性 pair baseline 的局限。
- 不含语义聚类、LLM 定义、HR feedback 和 Neo4j 发布的边界。

- [ ] **Step 3: 执行完整门禁**

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

预期：全量测试和 Ruff 通过，Alembic 无待生成操作，数据库 revision 为 `0007`。

- [ ] **Step 4: 独立提交并推送**

```bash
git add README.md backend/tests/test_discovery_tasks.py \
  docs/superpowers/plans/2026-08-06-candidate-discovery.md
git commit -m "test: verify discovery with real market data"
git push origin codex/candidate-discovery
```

---

## Task 6: Batch C 收尾

- [ ] **Step 1: 检查提交和工作区**

```bash
git status --short --branch
git log --oneline --decorate -12
git diff main...HEAD --stat
```

确认只有 Batch C 计划、0007 Migration、Discovery 模块、路由、测试和 README。

- [ ] **Step 2: 使用 finishing-a-development-branch**

执行 `superpowers:finishing-a-development-branch`：

1. 功能分支全量测试。
2. Fast-forward 合并到 `main`。
3. 合并后再次运行全量测试。
4. 推送 `origin/main`。
5. 删除 Superpowers worktree 和本地功能分支。
6. 保留 PostgreSQL、Neo4j 和文件 Volume，不运行 `docker compose down -v`。

---

## 4. 计划自检

- **范围闭环：** 选择批次、标签映射、候选生成、异步任务、候选查询和证据回溯都有明确任务。
- **唯一真相源：** 所有状态、候选、分数和证据只写 PostgreSQL；Neo4j 不接收候选。
- **幻觉边界：** 不调用 LLM；未知标签保存 unmapped，不自动创建标准技能。
- **算法边界：** 只实现可解释的 pair co-occurrence baseline，所有公式和权重版本化。
- **权限边界：** admin 创建；admin/hr 查看；applicant 不可访问。
- **数据边界：** 只使用 current、非 duplicate、达到质量阈值的 JD；Evidence 不泄漏完整 Raw Payload。
- **性能边界：** 适用于当前数百到数万 JD；只有真实测量表明组合枚举或数据库写入成为瓶颈时才引入批量 COPY、频繁项集或分布式计算。
- **后续接口：** Algorithm Service 语义聚类可以消费同一 JobAnalysisProfile；LLM 只能补充 Candidate definition；HR feedback 和 Graph Review 在后续独立批次实现。
