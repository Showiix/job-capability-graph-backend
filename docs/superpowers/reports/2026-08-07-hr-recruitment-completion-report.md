# HR 私有 JD 招聘匹配后端完成报告

日期：2026-08-07
分支：`codex/hr-recruitment`
对应设计：`docs/superpowers/specs/2026-08-07-hr-recruitment-design.md`
对应计划：`docs/superpowers/plans/2026-08-07-hr-recruitment.md`

## 1. 完成结论

本阶段已完成适合比赛内部展示和团队真实试用的 HR 招聘后端闭环：

```text
HR 创建项目
-> 提交文本或 PDF/DOCX/TXT JD
-> Celery 异步解析 JD
-> HR 整体修订并确认岗位要求
-> 批量上传 PDF/DOCX 候选简历
-> Celery 按候选逐个解析并生成不可变 Profile
-> 后端同步执行五维确定性匹配
-> 保存不可变 Match Run/Result 快照
-> 查询排名、匹配技能、缺失技能和候选详情
```

该闭环复用了系统现有账号、Session/CSRF、StoredFile、ProcessingRun、Responses API、Capability Catalog 和 Applicant 匹配评分核心，没有引入第二套认证、任务、文件或评分框架。

## 2. 已实现范围

### 2.1 共享核心

- 抽取 `resolve_capability_labels()` 精确映射边界，Resume 和 Recruitment 共同使用 active Capability/active Alias。
- 抽取 `score_profile_against_requirements()` 五维评分核心，Applicant 正式岗位推荐和 HR 私有 JD 匹配共享同一公式。
- 保留 PostgreSQL Capability Catalog 为标准技能唯一真相源；私有 JD 和简历中出现的新名称只保存为 unmapped candidate，不自动创建 Capability。

### 2.2 JD 工作流

- HR/admin 创建和查询私有招聘项目。
- JD 支持直接文本以及 PDF、DOCX、TXT 文件，单文件上限 10 MB。
- 提交接口使用 `Idempotency-Key`，相同键和内容复用响应，不同内容返回冲突。
- JD 解析由 Celery/ProcessingRun 异步执行，使用 Responses API strict Structured Outputs。
- 服务端验证职责和技能 Evidence 必须能在原始 JD 正文中 exact match。
- 模型抽取结果只形成可编辑 draft，不会直接覆盖历史 confirmed snapshot。
- HR 可以整体替换岗位标题、职责、学历、经验、mapped requirements 和 unmapped skills。
- confirm 生成不可变 revision 和 SHA-256；相同确认内容不增加 revision。

### 2.3 候选人工作流

- 单批支持 1 到 20 份 PDF/DOCX，批次总大小上限 100 MB。
- 接收阶段原子化：任一文件格式、数量或大小不合法时，不留下半批数据库行或文件。
- 每个 Candidate 独立解析和提交，一个候选失败不会回滚其他成功候选。
- 复用 `analyze_resume_document()` 完成本地文本提取、PII 脱敏、Responses API 抽取和 Evidence exact-match。
- 保存一对一不可变 CandidateProfile，以及 mapped/unmapped CandidateSkill 和 Evidence offset。
- failed Run 可通过通用 ProcessingRun retry 创建新 Run；已经 ready 且存在 Profile 的 Candidate 会被跳过。
- 在候选之间检查 cancel 标志，支持取消未开始的剩余项。

### 2.4 匹配与查询

- 只有 requirements 已确认、且不存在 uploaded/processing Candidate 时才能匹配。
- failed Candidate 不阻断匹配，而是写入 `skipped_candidates` 快照。
- ready Candidate 必须存在 Profile，否则拒绝生成不可复现的结果。
- 匹配在同步数据库事务中完成，不调用 LLM、Algorithm Service、Redis、Celery 或 Neo4j。
- 使用 requirements SHA-256、全部候选状态/Profile 选择 SHA-256 和 weight version 形成自然幂等键。
- 相同输入复用历史 Match Run，不重复计算和写入排名。
- 保存完整 requirements、weight、candidate、matched/missing capability、dimension score 和 gap summary 快照。
- 提供项目详情聚合：JD 状态、确认摘要、候选状态数量、最近 Processing Run 和最近 Match Run；候选和排名继续使用分页 endpoint。

## 3. 明确未实现范围

以下内容不属于本阶段完成范围，也未在报告中伪装成已实现：

- 招聘平台爬虫、爬虫管理页面和定时调度；当前市场数据入口仍是管理员批量导入。
- Algorithm Service 的语义抽取或语义匹配；当前 LLM 负责候选结构化抽取，最终映射与评分由后端确定性规则完成。
- 私有 JD/Candidate 写 Neo4j；Neo4j 只保存并展示审核发布后的公共岗位能力图谱。
- 独立向量 RAG pipeline；本阶段使用原文 Evidence、标准 Catalog 精确检索和人工确认形成数据锚定。
- OCR、扫描 PDF、多媒体作品集解析、视频解析和项目链接内容分析。
- Candidate Profile 的人工 Revision；第一版每个候选只保留一个不可变解析 Profile。
- 企业级租户、组织、部门、邀请、公开注册、外部候选门户和复杂 RBAC。
- 超大招聘项目的异步分布式匹配；当前同步事务适合比赛演示和内部中小批次。

## 4. 数据库与 Migration 0013

新增 Alembic revision：`0013_create_recruitment_tables`，下修订为 `0012_create_growth_paths`。

### 4.1 六张新增表

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `recruitment_projects` | 私有 JD、draft、confirmed requirements 和当前运行水位 | JD source/file 组合约束；revision/hash/snapshot 一致性；JSON object 约束 |
| `recruitment_candidates` | 项目候选人和解析状态 | `file_id` 唯一；状态枚举；项目级状态/名称索引 |
| `candidate_profiles` | 候选人不可变结构化画像 | 每个 Candidate 唯一 Profile；提取方式枚举；经验非负；JSON object 约束 |
| `candidate_skills` | 技能映射、Evidence 和标准 Capability 锚定 | profile+normalized name 唯一；mapped 状态与 capability/method 一致；Evidence offset、confidence、经验约束；mapped capability 部分唯一索引 |
| `recruitment_match_runs` | 一次确定性匹配的输入水位和统计快照 | project+requirements hash+candidate hash+weight version 唯一；计数一致；JSON object/array 约束 |
| `recruitment_match_results` | 候选排名和细粒度差距快照 | run+candidate、run+rank 唯一；分数 0..100；level 枚举；JSON object/array 约束 |

### 4.2 迁移和元数据

- `backend/alembic/env.py` 已注册 Recruitment ORM metadata。
- migration 同时创建外键、检查约束、唯一约束、常用查询索引和 downgrade 逆序删除逻辑。
- 系统版本接口的 Alembic revision 测试已从 `0012` 更新为 `0013`。
- `docker compose run --rm migrate` 已在真实 Compose PostgreSQL 上成功执行。

## 5. API 清单与执行边界

### 5.1 项目与 JD

- `POST /api/v1/recruitment-projects`
- `GET /api/v1/recruitment-projects`
- `GET /api/v1/recruitment-projects/{project_id}`
- `POST /api/v1/recruitment-projects/{project_id}/jd`
- `PUT /api/v1/recruitment-projects/{project_id}/requirements`
- `POST /api/v1/recruitment-projects/{project_id}/requirements/confirm`

### 5.2 候选人

- `POST /api/v1/recruitment-projects/{project_id}/candidates`
- `GET /api/v1/recruitment-projects/{project_id}/candidates`
- `GET /api/v1/recruitment-projects/{project_id}/candidates/{candidate_id}`

### 5.3 匹配

- `POST /api/v1/recruitment-projects/{project_id}/match-runs`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results/{candidate_id}`

### 5.4 同步/异步边界

| 操作 | 模式 | 原因 |
| --- | --- | --- |
| JD/简历上传 | 同步接收，异步解析 | LLM 和文档解析不占用 API 请求；通过 ProcessingRun 轮询 |
| Requirements replace/confirm | 同步事务 | 人工操作需要立即得到 revision/hash |
| Candidate list/detail | 同步读取 | 数据已持久化，分页读取即可 |
| Match Run | 同步事务 | 当前内部批次规模可控，确定性评分无需外部服务 |
| Match result/history | 同步读取 | 读取不可变快照，不重新计算 |

## 6. Capability、Evidence、LLM 与幻觉防控边界

### 6.1 唯一真相源

- 标准技能唯一真相源是 PostgreSQL 中 status=`active` 的 Capability 和 Alias。
- JD/Resume 原始名称先规范化，再做 canonical exact 或 alias exact 映射。
- 模型不能创建标准技能；未命中名称保存为 unmapped，等待未来人工审核。
- confirm 时重新读取 active Catalog，失效或不存在的 Capability 会被拒绝。

### 6.2 Evidence 锚定

- JD 每条 responsibility/skill 和 Resume 每条 education/experience/project/skill 都要求原文 Evidence。
- Provider 返回后由服务端验证 quote 在脱敏正文中 exact match，并保存 start/end offset。
- 评分只读取已通过验证并持久化的 Profile/Skill，不直接读取模型自由文本。
- 每个 Match Run 保存输入哈希和完整展示快照，结果可追溯到具体 requirement、Capability、Candidate Profile 和 Evidence。

### 6.3 LLM 边界

- 使用 OpenAI-compatible Responses API endpoint，而不是 Chat Completions。
- 固定 strict JSON Schema、`stream=false`、`store=false`。
- JD/Resume 解析允许配置同一个 Responses provider；配置缺失时任务以稳定错误码失败，其他系统模块仍可启动。
- 不使用 LangChain/LangGraph；当前步骤是线性、短流程，直接函数和 ProcessingRun 状态机已经足够。
- LLM 不决定最终匹配分数，不直接写正式 Catalog，也不写 Neo4j。

## 7. `match_weights_v1` 五维公式

总分使用 `Decimal` 计算：

```text
total = required_skill_coverage * 0.55
      + bonus_skill_coverage    * 0.10
      + skill_evidence_quality  * 0.15
      + experience              * 0.15
      + education               * 0.05
```

维度规则：

- required/bonus coverage 按 requirement importance 加权；没有 bonus requirement 时 bonus 记为 `not_required=100`。
- Evidence factor：`mention=0.40`、`project=0.70`、`work=1.00`，再按 matched requirement importance 加权。
- experience：候选月数低于推荐值时按比例得分，达到或超过推荐值为 100；无要求时为 100。
- education：`high_school < associate < bachelor < master < doctor`，低于门槛时按 rank 比例得分，达到或超过门槛为 100。
- 总分和各维度统一 `ROUND_HALF_UP` 保留两位小数。
- 分级：`high >= 75`、`medium >= 50`、其余为 `low`。
- 同分排序依次比较总分、required coverage、Evidence、experience、bonus、education、候选显示名和 UUID，结果稳定可复现。

Match Run 固化 `weight_version=match_weights_v1` 和完整 weight snapshot；未来调整权重必须发布新 version，不能篡改历史结果。

## 8. 权限、文件、重试与取消

### 8.1 权限

- HR 只能访问自己创建的 Recruitment Project、Run、Candidate、Match 和文件。
- admin 可访问全部项目和运行，便于内部运营排查。
- 其他 HR 和 applicant 对私有项目资源获得脱敏 404。
- Candidate/Run ID 必须同时属于 URL 中的 project_id，跨项目 ID 返回 404。
- 所有写接口使用既有 Session + CSRF；上传接口额外要求 `Idempotency-Key`。
- CORS 已允许 `Idempotency-Key` Header。

### 8.2 文件

- JD/候选文件继续使用 StoredFile 和本地 FileStorage，不新增通用公开上传接口。
- owner HR 和 admin 可读取 metadata、preview、download；其他角色不可见。
- 文件访问继续写 FileAccessLog。
- 业务响应返回 file URL，不把原始二进制或完整简历正文嵌入项目详情。

### 8.3 ProcessingRun

- `owner_scope_type=recruitment_project` 通过项目 owner 继承可见性。
- retry 创建新 Run 并保留 `retry_of_run_id`，旧 Run 不会改回 pending。
- 候选批次部分失败使用 `CANDIDATE_BATCH_PARTIAL_FAILURE`，逐项 ProcessingError 不包含简历正文。
- retry 跳过已有 ready Profile，只接管失败/未就绪候选。
- cancel 在候选边界生效，已提交成功候选不回滚，剩余候选保持原状态。

## 9. 验证结果

### 9.1 自动化测试

```text
uv run pytest -q
567 passed in 35.77s
```

招聘相关和受影响共享模块的聚焦回归：

```text
129 passed in 5.36s
```

新增端到端测试覆盖：HR login、项目创建、文本 JD、fake JD task、requirements replace/confirm、两份候选简历、部分失败、Match Run、结果/详情、文件读取、相同输入复用、failed skipped snapshot、跨项目隔离、其他 HR/applicant 隔离和 admin 排查。

### 9.2 质量门禁

| 检查 | 结果 |
| --- | --- |
| `docker compose run --rm migrate` | 通过，PostgreSQL 升级到 0013 |
| `uv run ruff check .` | 通过 |
| 任务相关 32 个路径 `ruff format --check` | 通过 |
| `git diff --check` | 通过 |

未执行全仓 `ruff format` 写入，避免把仓库既有无关格式漂移混入本次提交。

## 10. 已知简化与升级触发条件

| 当前简化 | 当前理由 | 何时升级 |
| --- | --- | --- |
| 每批最多 20 份、候选按 UUID 顺序逐个解析 | 内部演示更容易追踪部分成功和失败 | 单项目出现数百份简历或 Worker 吞吐成为瓶颈时，改为 per-candidate task/chord |
| Match Run 同步数据库事务 | 当前评分是纯内存 Decimal 计算，候选规模小 | 匹配请求明显超过 API 超时预算或需要跨算法服务时，改为 ProcessingRun 异步任务 |
| CandidateProfile 一对一不可变 | HR 当前只需要排序和解释，不需要画像编辑器 | 解析误差影响真实决策且需要人工纠正时，复用 Applicant Profile revision 模型 |
| 只做 exact Catalog mapping | 可解释、稳定且符合唯一真相源原则 | 标准库覆盖率不足且人工审核数据积累后，增加 embedding/Algorithm candidate mapping，但仍需人工或阈值确认 |
| 无独立 RAG/向量检索 | JD/简历正文、Capability exact lookup 和 Evidence 已提供足够约束 | 需要生成更长岗位定义或学习资料，并且有经过审核的知识语料时，再增加可追溯 retrieval |
| 无爬虫和定时调度 | 数据源实现与本招聘闭环解耦 | 批量导入稳定后，新增 crawler tool 只产出 ImportBatch，不直接写 Recruitment Project |
| 不解析作品集/视频/链接 | PRD 中本来只要求中转查看 | 出现真实评估需求和明确安全边界时，再扩展附件表与受控读取 |

## 11. 交付状态

- Task 0-9 已实现并逐项验证。
- Task 10 的 migration、全量测试、Ruff 和 diff check 已通过。
- README 已加入内部演示运行顺序和边界说明。
- 本报告完成后只暂存本阶段文件，执行 scoped diff check、commit 和 push。
