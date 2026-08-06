# Market JD Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可实际使用的管理员市场 JD 数据中心：批量上传真实 TSV/CSV 文件，保留不可变原始行，按来源 Adapter 解析并标准化，输出质量分和警告，同时提供可审核的技能/岗位 Catalog 初始骨架。

**Architecture:** 继续使用 Batch A 的 FastAPI 模块化单体、PostgreSQL 事实库、Redis/Celery 异步处理和本地受控文件卷。Import 只写 PostgreSQL 的来源事实与标准化版本；本批不调用 LLM、不写 Neo4j，未来算法结果只能以候选记录进入审核流程。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 async、Alembic、PostgreSQL 16 + pgvector、Celery/Redis、本地文件存储、Pydantic、pytest、HTTPX、Ruff、uv。

---

## 1. 范围与不做事项

本批只实现一个内部 admin 可用的“集中处理中心”：

- 支持 `standard_v1`、`liepin_v1`、`zhilian_v1` 三个文件 Adapter。
- 支持真实样例的 12 列 TSV：`job_name`、`company_name`、`salary`、`work_area`、`city`、`education`、`work_year`、`issue_date`、`source`、`skill_requirements`、`tech_tags`、`job_url`。
- 通过 Batch A 的业务文件存储和 Processing Run 生命周期异步处理。
- Raw 行只追加、不更新；标准化结果按版本追加并标记当前版本。
- 可查询批次、行、质量警告、重新处理和归档。
- 提供 Catalog 的 domain、capability、job role 初始骨架导入及 published/current 查询。

明确跳过：爬虫实现和定时调度、LLM/Algorithm 调用、语义向量去重、Neo4j 写入、公开注册、前端页面、复杂多租户隔离。保留接口和字段扩展点，但本批不提前建空模块。

## 2. 文件变更地图

```text
backend/app/imports/models.py              # data_sources/import_batches/raw/normalized/warnings
backend/app/imports/schemas.py             # import 请求与响应模型
backend/app/imports/adapters.py            # 三个来源 Adapter 和标准行 DTO
backend/app/imports/normalization.py       # 日期、薪资、经验、城市、编码和质量分
backend/app/imports/service.py             # 批次创建、查询、重处理、归档
backend/app/imports/tasks.py               # Celery 行处理任务
backend/app/imports/router.py              # /api/v1/imports admin API
backend/app/infrastructure/file_storage.py # 增加受限流式写入
backend/app/catalog/models.py              # domains/capabilities/job_roles/version/import
backend/app/catalog/schemas.py             # Catalog 请求与响应
backend/app/catalog/service.py             # validate-only/apply 与查询
backend/app/catalog/router.py               # /api/v1/catalog API
backend/app/api/router.py                  # 挂载 imports/catalog routers
backend/alembic/versions/0005_market_imports.py
backend/alembic/versions/0006_catalog_skeleton.py
backend/tests/test_import_database_constraints.py
backend/tests/test_import_upload.py
backend/tests/test_import_adapters.py
backend/tests/test_import_normalization.py
backend/tests/test_import_tasks.py
backend/tests/test_import_api.py
backend/tests/test_catalog_import.py
backend/tests/test_catalog_database_constraints.py
backend/tests/fixtures/liepin_sample.tsv
backend/tests/fixtures/zhilian_sample.tsv
README.md                                  # Batch B 启动与验收命令
```

现有 `app.infrastructure.file_storage.FileStorage`、`app.processing.service`、`require_admin`、`get_db` 和统一错误处理中已有的能力必须复用，不创建第二套权限或任务状态实现。`FileStorage` 当前只有安全路径解析，本批只给它增加一个受字节上限约束的流式写入方法。

## 3. 数据契约

### 3.1 Adapter 输入与标准行

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StandardJobRow:
    row_number: int
    source_code: str
    external_id: str | None
    source_url: str | None
    job_name: str
    company_name: str | None
    salary_text: str | None
    work_area_text: str | None
    city_text: str | None
    education_text: str | None
    work_year_text: str | None
    issue_date_text: str | None
    raw_text: str | None
    source_tags: list[str]
    raw_payload: dict[str, str | None]
    parse_warnings: list[str]
```

每个 Adapter 只负责列名映射和来源差异；它不能修改原始字符串。缺失可选列写入 `None` 并生成 warning，缺少 `job_name` 或无法解码的行返回 rejected。

### 3.2 标准化规则

- 文本：去除 BOM、NUL、首尾空白和连续空格；保留原始值在 `raw_payload`。
- 日期：锚点由请求 `collected_at` 提供；`今日更新` 为锚点日期，`N天前更新` 减 N 天，`M月D日更新` 使用锚点年份并处理跨年未来日期；无法解析则 `published_at=NULL` 且 warning。
- 薪资：统一月薪元整数。`8-16k` -> 8000/16000，`1.5-3万` -> 15000/30000，`5000-10000元` 原值，`100-150元/天` 按 21.75 工作日折算并标记 `salary_period_converted`，`·15薪` 写 `salary_months=15`。
- 经验：`应届生/无经验` -> 0/0，`1-3年` -> 12/36，`3年以上` -> 36/NULL，无法解析只 warning。
- 学历：映射为 `unknown`、`below_high_school`、`high_school`、`associate`、`bachelor`、`master`、`doctorate`。
- 城市：优先 `work_area_text` 的城市；采集城市与岗位城市冲突时保留岗位城市并添加 `city_conflict`。
- 质量分从 100 起按规则扣分：缺岗位名 100 分并拒绝；缺公司/正文各扣 10；缺日期扣 5；乱码检测扣 20；冲突/转换各扣 5；分数限制在 0-100。

### 3.3 状态和错误码

批次状态仅允许 `uploaded`、`processing`、`processed`、`partial`、`failed`、`archived`；行状态为 `accepted`、`warning` 或 `rejected`。稳定错误码包括 `IMPORT_SCHEMA_NOT_RECOGNIZED`、`SOURCE_ADAPTER_MISMATCH`、`FILE_ENCODING_UNSUPPORTED`、`IMPORT_EMPTY`、`IMPORT_ROW_LIMIT_EXCEEDED`、`PROCESSING_ALREADY_RUNNING`。

---

## 4. 分步实现

### Task 1: 市场 JD 数据模型与 Migration 0005

**Files:**
- Create: `backend/tests/test_import_database_constraints.py`
- Create: `backend/app/imports/__init__.py`
- Create: `backend/app/imports/models.py`
- Create: `backend/alembic/versions/0005_market_imports.py`

- [ ] **Step 1: 写 RED 测试**

测试导入模块可导入五个模型，验证 `raw_job_postings(batch_id,row_number)` 唯一约束、`normalized_job_postings(raw_job_id,version_no)` 唯一约束、质量分范围和批次计数约束。测试导入 `app.imports.models` 后先应得到 `ModuleNotFoundError`。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_database_constraints.py -q
```

预期：失败且错误为 `ModuleNotFoundError: No module named 'app.imports'`。

- [ ] **Step 3: 实现最小模型和迁移**

沿用 `app.auth.models`、`app.files.models` 的 Declarative Base、UUID、时间戳和命名约束风格。创建 `data_sources`、`import_batches`、`raw_job_postings`、`normalized_job_postings`、`import_warnings` 五表及设计文档中列出的 FK、CHECK、索引和 partial unique index；`0005` 的 `down_revision` 固定为 `0004`。为 `data_sources` 提供 `standard/liepin/zhilian/zhilian_direct` seed，保证重复 upgrade 不重复插入。

- [ ] **Step 4: 运行 GREEN 和迁移检查**

```bash
cd backend
uv run pytest tests/test_import_database_constraints.py -q
uv run ruff check app/imports tests/test_import_database_constraints.py
uv run alembic upgrade head
uv run alembic check
```

预期测试通过、Ruff 通过、当前 revision 为 `0005` 且 `alembic check` 报告没有新操作。

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports backend/alembic/versions/0005_market_imports.py backend/tests/test_import_database_constraints.py
git commit -m "feat: add market JD import schema"
```

### Task 2: 安全流式文件保存与创建批次幂等

**Files:**
- Create: `backend/tests/test_import_upload.py`
- Create: `backend/app/imports/schemas.py`
- Create: `backend/app/imports/service.py`
- Create: `backend/app/imports/router.py`
- Modify: `backend/app/infrastructure/file_storage.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: 写 RED 测试**

使用 `httpx.AsyncClient` 以 admin Session 上传小型 TSV，断言返回 202、创建一个 `import_batches` 和一个 `processing_runs`，文件名不影响 `storage_key`；重复 `Idempotency-Key` 且请求哈希相同返回同一资源；相同 key 不同文件返回 409；非 admin 返回 403；超过 `MAX_IMPORT_FILE_BYTES` 的文件返回 413 且不留下半文件。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_upload.py -q
```

预期：导入路由尚未挂载，返回 404 或 `ModuleNotFoundError`。

- [ ] **Step 3: 实现最小上传流程**

给现有 `FileStorage` 增加 `save_stream(stream, storage_key, max_bytes)`：写同目录临时文件、流式计算 SHA-256，超限或异常时删除临时文件，成功后原子 `replace`。第一版只允许 `.csv`、`.tsv`、`.txt`、`.json`，限制单文件字节数，拒绝空文件；XLSX 等真实需要出现后再增加解析依赖。先创建 `StoredFile(category="market_jd")`，再创建 `ImportBatch(status="uploaded")` 和 `ProcessingRun(run_type="import_market_jd")`。幂等逻辑直接使用 Batch A 的 `IdempotencyRecord` 模型在 Import service 中完成，不创建通用框架。最后投递 `app.import_market_jd`。请求字段为 `source_code`、`collected_at`、可选 `source_format`/`schema_version`。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend && uv run pytest tests/test_import_upload.py -q
```

预期全部通过，且重复请求不会保存第二份业务批次。

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports backend/app/infrastructure/file_storage.py backend/app/core/config.py backend/app/api/router.py backend/tests/test_import_upload.py
git commit -m "feat: add admin market JD upload"
```

### Task 3: Standard/Liepin/Zhilian Adapter

**Files:**
- Create: `backend/tests/test_import_adapters.py`
- Create: `backend/app/imports/adapters.py`
- Create: `backend/tests/fixtures/liepin_sample.tsv`（用户提供的 147 行真实样例）
- Create: `backend/tests/fixtures/zhilian_sample.tsv`（用户提供的 307 行真实样例）

- [ ] **Step 1: 写 RED 测试**

测试 `detect_adapter(headers, source_code)` 能识别共同 12 列；`LiepinV1Adapter` 将 `salary` 映射为 `salary_text`、`tech_tags` 解析为标签列表；`ZhilianV1Adapter` 接受 `zhilian_direct` 作为 source code 但返回标准 `zhilian` 适配器；缺 `job_name` 的行是 rejected；字段多于 12 列时保留未知列到 `raw_payload`。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_adapters.py -q
```

预期：`app.imports.adapters` 不存在导致失败。

- [ ] **Step 3: 实现适配器**

使用标准库 `csv.DictReader`，以 UTF-8-SIG、UTF-8、GB18030 顺序解码；不引入 pandas。定义 `BaseAdapter`, `StandardV1Adapter`, `LiepinV1Adapter`, `ZhilianV1Adapter` 和 `ADAPTERS` 映射。表头比较使用去 BOM、大小写不敏感和下划线标准化；来源不匹配抛出固定错误码。每行生成 `StandardJobRow`，不做价格/日期转换。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend && uv run pytest tests/test_import_adapters.py -q
uv run ruff check app/imports/adapters.py tests/test_import_adapters.py
```

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports/adapters.py backend/tests/test_import_adapters.py backend/tests/fixtures
git commit -m "feat: add market JD source adapters"
```

### Task 4: 确定性标准化、乱码和质量告警

**Files:**
- Create: `backend/tests/test_import_normalization.py`
- Create: `backend/app/imports/normalization.py`

- [ ] **Step 1: 写 RED 测试**

覆盖 `8-16k`、`25-40k·15薪`、`100-150元/天`、`1.5-3万` 四种薪资；`今日更新`、`90天前更新`、`7月28日更新` 三种日期；`应届生`、`1-3年`、`3年以上` 三种经验；采集城市与岗位城市冲突；包含替换字符 `�` 的乱码；缺正文和缺日期的质量扣分。断言标准化输出和 warning code 完全稳定。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_normalization.py -q
```

预期：标准化函数尚未定义，测试失败。

- [ ] **Step 3: 实现纯函数**

实现 `normalize_salary`, `normalize_date`, `normalize_experience`, `normalize_education`, `normalize_city`, `detect_garbled_text` 和 `normalize_row`。所有函数只接收字符串与 `date`，不访问数据库；返回 typed dataclass，便于任务重放。日期无法确定时不猜年份；月薪转换、冲突和缺失都记录固定 warning code。质量分计算集中在 `quality_score_for(row)`，结果 clamp 到 `[0,100]`。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend && uv run pytest tests/test_import_normalization.py -q
uv run ruff check app/imports/normalization.py tests/test_import_normalization.py
```

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports/normalization.py backend/tests/test_import_normalization.py
git commit -m "feat: normalize market JD fields"
```

### Task 5: Import Worker、partial、取消和恢复

**Files:**
- Create: `backend/tests/test_import_tasks.py`
- Create: `backend/app/imports/tasks.py`
- Modify: `backend/app/imports/service.py`
- Modify: `backend/app/worker.py`

- [ ] **Step 1: 写 RED 测试**

构造测试数据库中的 `uploaded` 批次和 3 行文件，直接调用任务的异步 service 入口。断言：处理成功后批次为 `processed`，Raw 行为 3，Normalized 当前版本为 3；一行缺岗位名时批次为 `partial` 且 `rejected_rows=1`；任务收到 `cancel_requested` 后停止继续写行并把批次标记为 `partial`；超过 `MAX_IMPORT_ROWS` 时以 `IMPORT_ROW_LIMIT_EXCEEDED` 失败；Worker 心跳更新 `processing_runs.heartbeat_at`，重复运行同一 batch/pipeline 不创建第二个当前版本。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_tasks.py -q
```

预期：任务函数和 Celery 注册尚不存在，测试失败。

- [ ] **Step 3: 实现最小任务闭环**

定义 `process_market_import(run_id)`：从 Run 找到 Batch 和 StoredFile，流式逐行读取；每行先写 `RawJobPosting`，再调用标准化纯函数写 `NormalizedJobPosting` 和 `ImportWarning`。用单事务 chunk（默认 100 行）提交，提交前检查 `cancel_requested` 和 `MAX_IMPORT_ROWS`。成功/部分失败时原子更新批次计数、summary 和 Run result；文件解码、Adapter、空数据或行数超限错误写入 Processing Error 并把 Run/Batch 标记为 failed。注册 `@celery_app.task(name="app.import_market_jd")`，任务异常不丢失 Run。

实现 `reprocess_batch` 时增加 `normalization_version`，同一 Raw 行 `version_no + 1`，旧版本 `is_current=false`；不更新 Raw 字段。

- [ ] **Step 4: 运行 GREEN 和回归**

```bash
cd backend
uv run pytest tests/test_import_tasks.py -q
uv run pytest -q
uv run ruff check .
```

预期新测试与 Batch A 全部通过。

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports/tasks.py backend/app/imports/service.py backend/app/worker.py backend/tests/test_import_tasks.py
git commit -m "feat: process market JD imports asynchronously"
```

### Task 6: Import 查询、重处理和归档 API

**Files:**
- Create: `backend/tests/test_import_api.py`
- Modify: `backend/app/imports/schemas.py`
- Modify: `backend/app/imports/service.py`
- Modify: `backend/app/imports/router.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: 写 RED 测试**

使用 admin 登录和已处理批次，覆盖以下契约：

```text
POST /api/v1/imports                         -> 202
GET  /api/v1/imports                         -> 200，按 created_at DESC
GET  /api/v1/imports/{id}                    -> counts、adapter、warning_summary
GET  /api/v1/imports/{id}/rows               -> raw/normalized 摘要，不含 raw_payload
GET  /api/v1/imports/{id}/rows?include=raw_payload,full_text -> admin 才返回详情
GET  /api/v1/imports/{id}/warnings           -> 按 code 聚合并列出行号
POST /api/v1/imports/{id}/reprocess          -> 202，创建新 Run
POST /api/v1/imports/{id}/archive            -> 200，状态 archived
```

断言普通 applicant/hr 返回 403；不存在批次返回统一 `RESOURCE_NOT_FOUND`；已有 running Run 的 reprocess 返回 409；重复归档是幂等 200。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_import_api.py -q
```

预期：路由未挂载或响应模型不存在导致失败。

- [ ] **Step 3: 实现 API**

所有路由使用 Batch A 的 `require_admin` 和 `get_db`。`GET /rows` 默认只返回 `row_number`、岗位名、公司、城市、quality_score、flags、normalized version；`include` 参数显式允许 admin 读取 raw payload/text。列表使用 `limit` 1-100、`offset` >=0，服务层只返回当前用户可见批次。响应统一包装为 `{"data": ...}`，异步创建响应包含 `resource_id`、`run_id`、`poll_url`。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend
uv run pytest tests/test_import_api.py -q
uv run pytest -q
uv run ruff check .
```

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/imports backend/app/api/router.py backend/tests/test_import_api.py
git commit -m "feat: add market JD import APIs"
```

### Task 7: Catalog 初始骨架模型与 Migration 0006

**Files:**
- Create: `backend/tests/test_catalog_database_constraints.py`
- Create: `backend/app/catalog/__init__.py`
- Create: `backend/app/catalog/models.py`
- Create: `backend/alembic/versions/0006_catalog_skeleton.py`

- [ ] **Step 1: 写 RED 测试**

断言 domain 的 parent 不能形成自引用；capability 在同一 domain 内 canonical name 唯一；alias 不能同时指向两个 capability；job role 默认 candidate；catalog version 只有一个 current published 版本；version item 必须引用 capability 或 job role 之一。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_catalog_database_constraints.py -q
```

预期：`app.catalog` 不存在导致失败。

- [ ] **Step 3: 实现模型与迁移**

创建 `domains`、`capabilities`、`capability_aliases`、`job_roles`、`job_role_aliases`、`catalog_versions`、`catalog_version_items`、`catalog_imports`、`catalog_import_rows`。只保存骨架主数据，不建正式图谱关系。状态枚举严格使用设计文档值：capability `candidate/active/deprecated`，job role `candidate/active/deprecated`，version `draft/validated/published/archived`。`0006` 下接 `0005`，迁移后 revision 为 `0006`。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend
uv run pytest tests/test_catalog_database_constraints.py -q
uv run alembic upgrade head
uv run alembic check
```

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/catalog backend/alembic/versions/0006_catalog_skeleton.py backend/tests/test_catalog_database_constraints.py
git commit -m "feat: add catalog skeleton schema"
```

### Task 8: Catalog validate-only/apply 导入

**Files:**
- Create: `backend/tests/test_catalog_import.py`
- Create: `backend/app/catalog/schemas.py`
- Create: `backend/app/catalog/service.py`
- Create: `backend/app/catalog/router.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: 写 RED 测试**

上传最小 JSON/TSV 技能骨架，断言 `mode=validate_only` 只创建 `catalog_imports` 和错误行、不写 capability；`mode=apply` 先验证后写入 domain/capability/job_role 和一个 draft version；重复 canonical name、未知 domain、歧义 alias 行进入错误表且不影响其他有效行；非 admin 返回 403；普通 authenticated 用户只能查询 published version。

- [ ] **Step 2: 运行 RED**

```bash
cd backend && uv run pytest tests/test_catalog_import.py -q
```

预期：Catalog API 未实现，测试失败。

- [ ] **Step 3: 实现最小导入服务和 API**

接受字段 `file`、`import_type`（`capability` 或 `job_role`）、`schema_version`、`mode`。使用标准库 JSON/CSV 解析；以 chunk 事务写入有效行。`validate_only` 不改变正式目录；`apply` 创建 `CatalogVersion(status="draft")`，所有模型/LLM 来源一律 `candidate`，不直接激活。提供 `GET /api/v1/catalog/versions`、`/current`、`/domains`、`/capabilities`、`/job-roles`，默认只查 published/active，admin 可用 `include_drafts=true`。

- [ ] **Step 4: 运行 GREEN**

```bash
cd backend
uv run pytest tests/test_catalog_import.py -q
uv run pytest -q
uv run ruff check .
```

- [ ] **Step 5: 独立提交**

```bash
git add backend/app/catalog backend/app/api/router.py backend/tests/test_catalog_import.py
git commit -m "feat: add catalog skeleton import APIs"
```

### Task 9: 真实样例端到端验收与文档

**Files:**
- Modify: `backend/tests/test_import_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-06-market-jd-center.md`

- [ ] **Step 1: 固化样例和验收断言**

使用 Task 3 已固化的两份真实 TSV 测试完整导入：猎聘 147 行、智联 307 行；断言两批 accepted/rejected/warning 总数之和等于 147/307，`source` 分别保留 `liepin`、`zhilian`、`zhilian_direct`，空 city/tech_tags/issue_date/skill_requirements 只产生预期 warning，不丢行。

- [ ] **Step 2: 运行真实数据验收**

```bash
cd backend && uv run pytest tests/test_import_api.py -q -k sample
```

预期：两份样例均完成，批次状态为 `processed` 或 `partial`，没有未捕获异常。

- [ ] **Step 3: 更新 README**

补充 `docker compose run --rm migrate` 升级到 `0006`、创建 admin、上传样例的 curl 示例、查询 warnings/rows 的命令，以及本批明确不包含爬虫和算法服务的说明。

- [ ] **Step 4: 运行全量门禁**

```bash
docker compose config -q
docker compose run --rm api uv run ruff check .
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test api uv run pytest -q
docker compose run --rm migrate
docker compose exec postgres psql -U job_graph -d job_graph -c "select version_num from alembic_version;"
git diff --check
```

预期：Ruff、全量测试通过，数据库 revision 为 `0006`，diff 无空白错误。

- [ ] **Step 5: 独立提交**

```bash
git add backend/tests README.md docs/superpowers/plans/2026-08-06-market-jd-center.md
git commit -m "test: verify market JD center with real samples"
```

### Task 10: Batch B 收尾

- [ ] **Step 1: 检查工作区和提交范围**

```bash
git status --short --branch
git log --oneline --decorate -12
```

确认只包含 Batch B 文件，且每个 Task 都有独立提交。

- [ ] **Step 2: 执行最终质量门禁**

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run alembic check
```

- [ ] **Step 3: 进入 finishing-a-development-branch 流程**

使用 `superpowers:finishing-a-development-branch`，在功能分支完成最终测试后合并到 `main`、push，并保留 PostgreSQL/Neo4j/文件命名卷；不执行 `docker compose down -v`。

---

## 5. 计划自检

- 需求覆盖：批量导入、集中处理、来源适配、Raw/Normalized、质量告警、查询/重处理/归档、Catalog 初始骨架和真实数据验收均有对应 Task。
- 幻觉边界：本批没有 LLM 写库路径，Catalog 导入的模型来源一律 candidate，Neo4j 保持只读健康检查。
- 性能边界：使用流式读取和每 100 行提交，适合比赛演示与内部使用；3 万技能正式导入仍需后续压测和 COPY 优化。
- 数据边界：Raw 不更新、不删除；标准化只追加版本；归档只改变批次状态。
- 安全边界：管理员权限、文件扩展名/大小、路径约束、幂等请求和统一错误响应都在计划内。
