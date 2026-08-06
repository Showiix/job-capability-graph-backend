# 岗位能力图谱系统数据库与 API 详细设计

_版本：v1.0 · 状态：已确认 · 日期：2026-08-06 · 依赖文档：《岗位能力图谱系统后端技术架构详细设计》_

---

## 📋 设计范围与结论

### 编写目的

本文档把产品需求转换为可以直接指导数据库 Migration、SQLAlchemy Model、Pydantic Schema、FastAPI Router、Celery Task 和前后端联调的业务契约。

数据库与 API 不分开设计。每项需求按以下顺序落地：

~~~mermaid
flowchart LR
    accTitle: Requirement To Contract Flow
    accDescr: Design flow that converts each product requirement into owned resources, durable data, APIs, background tasks, permissions, and acceptance checks

    requirement[📋 PRD requirement] --> action[👤 User action]
    action --> resource[🗂️ Business resource]
    resource --> lifecycle[🔄 Lifecycle and ownership]
    lifecycle --> database[(💾 Database contract)]
    lifecycle --> api[🌐 API contract]
    api --> task[⚙️ Background task]
    database --> acceptance[🧪 Acceptance check]
    task --> acceptance
~~~

本文档回答五个问题：

1. 系统需要保存哪些业务事实
2. 每项事实由谁创建、谁能读取、谁能修改
3. 每项资源有哪些状态，以及状态如何流转
4. 前端和内部服务需要调用哪些接口
5. 后台任务失败、重试、取消和重复调用时如何保持一致

### 设计基线

本设计沿用已确认的技术边界：

| 主题 | 设计结果 |
| --- | --- |
| 后端 | FastAPI 模块化单体[^1] |
| ORM 与迁移 | SQLAlchemy 2 + Alembic[^2][^3] |
| 业务数据库 | PostgreSQL[^4] |
| 向量检索 | PostgreSQL + pgvector[^5] |
| 正式图谱查询 | Neo4j[^6] |
| 后台任务 | Celery Worker + Redis[^7][^8] |
| 周期任务 | Celery Beat |
| 文件 | 本地 Docker Volume，PostgreSQL 保存元数据 |
| 算法 | 独立内部 Algorithm Service |
| LLM | OpenAI-compatible API |
| 登录 | 管理员创建账号，无公开注册 |
| 角色 | applicant、hr、admin |
| 智能模块权限 | 只生成候选，不能直接写正式知识 |
| 图谱发布 | 人工审核后由 admin 发布版本 |
| 进度通知 | HTTP 轮询，不使用 WebSocket 或 SSE |

### 当前实现边界

本设计覆盖：

- 内部账号、登录会话和三种角色
- 文件受控上传、预览和下载
- 市场 JD 批量导入、清洗、去重和抽取
- 标准技能库、岗位库和别名维护
- 候选技能组合发现和新岗位候选
- 知识变更审核和 Neo4j 版本发布
- applicant 简历解析、岗位匹配和成长路径
- HR 招聘项目、候选人、批量匹配和材料查看
- Algorithm Service 与 LLM 调用记录
- 后台任务、错误、重试、取消和审计

当前不设计实现：

- 公开注册、短信、邮件验证和找回密码
- 多租户、企业组织、部门和复杂协作权限
- 爬虫管理界面、爬虫编排和定时采集规则
- 在线课程购买、打卡、测验和学习进度
- 自动图谱发布
- WebSocket、SSE、Kafka、Kubernetes、MinIO 和 Elasticsearch
- 通用 Agent Runtime、LangGraph 和 Tool 自主调用

### 设计方法选择

可以采用三种常见路径：

| 路径 | 优点 | 风险 | 结论 |
| --- | --- | --- | --- |
| 先画数据库，再补接口 | 上手快 | 容易出现无法闭环的状态和权限 | 不采用 |
| 先列页面接口，再补表 | 贴近页面 | 数据历史、幂等和审计容易缺失 | 不采用 |
| PRD 驱动联合设计 | 资源、状态、权限、表和接口一致 | 前期文档量较大 | 采用 |

### 规范性术语

本文档使用以下强度词：

| 术语 | 含义 |
| --- | --- |
| 必须 | 第一版实现不可省略 |
| 应当 | 除非出现明确技术原因，否则按此实现 |
| 可以 | 可选行为，不影响核心闭环 |
| 不允许 | API、Service 或数据库必须阻止 |

## 🎯 PRD 需求追踪

### 角色闭环

#### applicant 闭环

~~~mermaid
flowchart LR
    accTitle: Applicant Product Loop
    accDescr: Applicant flow from resume upload through profile confirmation, job matching, skill gap review, and persisted growth plan generation

    upload[📥 Upload resume] --> parse[⚙️ Parse profile]
    parse --> confirm[👤 Confirm profile]
    confirm --> recommend[🔍 Match job roles]
    recommend --> detail[📊 Review match detail]
    detail --> gap[📋 Select skill gap]
    gap --> plan[🎓 Generate growth plan]
    plan --> history[📝 View saved plan]
~~~

对应资源：

| PRD 动作 | PostgreSQL 资源 | API | 异步任务 |
| --- | --- | --- | --- |
| 上传简历 | stored_files、resumes | POST /resumes | parse_resume |
| 预览原文件 | stored_files | GET /files/{id}/content | 无 |
| 查看解析进度 | processing_runs | GET /processing-runs/{id} | parse_resume |
| 确认画像 | resume_profiles 及明细表 | POST /resumes/{id}/profiles/{version}/confirm | 无 |
| 人工补充技能 | resume_skills、capability_submissions | POST /resumes/{id}/profiles/{version}/skills | 可选 catalog_review |
| 匹配岗位 | match_results | POST /matches/job-recommendations | match_job_roles |
| 查看技能差距 | match_skill_details | GET /matches/{id} | 无 |
| 生成成长路径 | growth_plans、growth_steps | POST /growth-plans | generate_growth_plan |

#### HR 闭环

~~~mermaid
flowchart LR
    accTitle: HR Recruitment Loop
    accDescr: HR flow from project creation and JD parsing through candidate import, batch matching, ranking, detail inspection, and candidate material review

    project[📋 Create project] --> jd[📥 Add JD]
    jd --> parse_jd[⚙️ Parse requirements]
    parse_jd --> candidates[👥 Import candidates]
    candidates --> parse_resumes[⚙️ Parse resumes]
    parse_resumes --> match[📊 Run matching]
    match --> ranking[🔍 View ranking]
    ranking --> detail[📝 View evidence]
    detail --> materials[📦 View materials]
~~~

对应资源：

| PRD 动作 | PostgreSQL 资源 | API | 异步任务 |
| --- | --- | --- | --- |
| 创建招聘项目 | recruitment_projects | POST /recruitment-projects | 无 |
| 输入或上传 JD | job_descriptions、stored_files | POST /recruitment-projects/{id}/job-descriptions | parse_recruitment_jd |
| 批量上传候选简历 | candidate_records、resumes、stored_files | POST /recruitment-projects/{id}/candidate-imports | import_candidates |
| 添加作品集和链接 | candidate_materials | POST /candidate-records/{id}/materials | 无 |
| 批量匹配 | match_results | POST /recruitment-projects/{id}/match-runs | match_recruitment_project |
| 查看排序 | match_results | GET /recruitment-projects/{id}/rankings | 无 |
| 查看匹配明细 | match_skill_details、match_condition_details | GET /matches/{id} | 无 |
| 查看新岗位发现候选 | discovery_candidates、business_feedback | GET /discovery-candidates | 无 |
| 业务采纳候选 | business_feedback | POST /discovery-candidates/{id}/feedback | 无 |

#### admin 闭环

~~~mermaid
flowchart LR
    accTitle: Admin Knowledge Loop
    accDescr: Administrator flow from market data import through processing, candidate discovery, catalog review, graph publication, and version verification

    import_data[📥 Import market JD] --> process[⚙️ Process batch]
    process --> catalog[🗂️ Map catalog]
    catalog --> discover[🔍 Discover combinations]
    discover --> review[👤 Review changes]
    review --> version[🏷️ Create graph version]
    version --> publish[📤 Publish Neo4j]
    publish --> verify[✅ Verify version]
~~~

对应资源：

| PRD 动作 | PostgreSQL 资源 | API | 异步任务 |
| --- | --- | --- | --- |
| 导入市场 JD | import_batches、raw_job_postings | POST /imports | import_market_jd |
| 清洗与去重 | normalized_job_postings、duplicate_clusters | POST /imports/{id}/process | process_jd_batch |
| 维护技能库 | capabilities、capability_aliases | /catalog/capabilities | 无 |
| 发现候选组合 | discovery_runs、skill_combination_candidates | POST /discovery-runs | discover_skill_combinations |
| 审核知识变更 | graph_change_candidates、review_decisions | /reviews | 无 |
| 发布正式图谱 | graph_versions、graph_publications | POST /graph-versions/{id}/publish | publish_graph_version |
| 管理内部账号 | users、auth_sessions | /admin/users | 无 |
| 管理失败任务 | processing_runs、processing_errors | /processing-runs | 目标任务 |

### 功能追踪矩阵

| PRD 功能 | 关键数据 | 对外 API 组 | 内部依赖 | 完成判定 |
| --- | --- | --- | --- | --- |
| 3D 全局图谱 | Neo4j 当前版本 | Graph API | Graph Query Service | 返回有限节点与边 |
| 岗位技能子图 | JobRole、Capability、关系 | Graph API | Neo4j | 返回目标岗位邻域 |
| 技术栈和职级切换 | domain、job_level | Graph API filter | Neo4j 索引 | 筛选结果稳定 |
| JD 批量导入 | Raw/Normalized JD | Import API | Adapter、Celery | 可追溯到原始行 |
| JD 技能提取 | job_analysis_profiles、job_skill_candidates | Processing/Catalog API | Algorithm、LLM | 候选带 Evidence |
| 简历解析 | resume_profiles 及明细 | Resume API | Parser、OCR、Algorithm、LLM | 每字段可定位证据 |
| 未识别技能补充 | resume_skills、capability_submissions | Resume/Catalog API | Review | 不直接进入正式库 |
| applicant 岗位匹配 | match_results | Matching API | Neo4j、Algorithm 可选召回 | 可解释分数和差距 |
| HR 候选排序 | match_results | Recruitment API | Celery | 同一权重版本排序 |
| 新岗位发现 | skill_combination_candidates | Discovery API | 聚类、共现、图谱差异、LLM | 输出候选而非趋势事实 |
| 人工审核 | review_decisions | Review API | PostgreSQL 事务 | 决策不可覆盖 |
| 图谱发布 | graph_versions、graph_publications | Graph Admin API | Neo4j | 读回验证后切换当前版本 |
| 成长路径 | growth_plans、growth_steps | Growth API | Neo4j、pgvector、LLM | 技能和链接均可验证 |
| 数据来源与置信度 | evidence、source、score | 所有详情 API | PostgreSQL | 输出可追溯 |

### 第一版接口边界结论

第一版需要的是稳定业务接口，不是为每张表自动生成 CRUD。

必须提供：

- 登录和内部账号管理
- 文件上传、受控预览和下载
- 市场 JD 导入与处理
- 任务状态、错误、重试和取消
- 标准技能与岗位查询、维护和提交审核
- 新岗位发现候选、HR 反馈和管理员审核
- 图谱版本、子图和差异查询
- applicant 简历、画像、匹配和成长路径
- HR 招聘项目、JD、候选人、材料、匹配和排序

不提供：

- 原始数据库表通用增删改查
- 普通用户物理删除历史记录
- 前端直接提交最终分数、审核人或发布版本号
- Algorithm Service、LLM 或 Neo4j 直接访问业务表

## 📚 公共数据与 API 契约

### 命名约定

| 对象 | 约定 | 示例 |
| --- | --- | --- |
| PostgreSQL 表 | 复数 snake_case | processing_runs |
| PostgreSQL 字段 | snake_case | created_by_user_id |
| REST 路径 | 复数 kebab-case | /recruitment-projects |
| JSON 字段 | snake_case | current_stage |
| Python 类型 | PascalCase | ProcessingRunResponse |
| 枚举值 | 小写 snake_case | waiting_review |
| 审计动作 | 领域.资源.动作 | graph.version.publish |
| 错误码 | 大写 snake_case | FILE_TYPE_NOT_ALLOWED |

### 主键与业务标识

- 所有业务表使用 UUID 主键
- UUID 由应用层生成，创建资源前即可作为日志和文件路径标识
- 用户不可修改 UUID
- 版本号、批次行号和序号使用整数，不替代主键
- 外部平台 ID 单独保存为 <code>external_id</code>
- 对外响应不暴露数据库自增序列

### 时间与日期

- PostgreSQL 事件时间统一使用 <code>timestamptz</code>
- 数据库存储 UTC，API 使用 ISO 8601 UTC，例如 <code>2026-08-05T08:10:00Z</code>
- 招聘发布日期只精确到天时使用 <code>date</code>
- 相对日期必须结合 <code>collected_at</code> 解析
- 无法确定的平台发布日期保存为空，并写入解析警告
- 所有创建型业务表必须有 <code>created_at</code>
- 可修改主数据必须有 <code>updated_at</code>

### 状态字段

业务状态使用 <code>varchar</code> 配合数据库 <code>CHECK</code>，不使用 PostgreSQL Native ENUM。原因是比赛期状态可能调整，Alembic 修改 Check Constraint 比修改原生枚举直接。

规则：

- API 不允许客户端任意写状态字符串
- 状态由明确动作接口推进
- 状态变化需要同事务校验当前状态
- 已发布、已拒绝和已完成记录不通过普通 PATCH 覆盖
- 历史结果通过新版本或新记录表达

### 通用审计字段

按表的职责选用：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| created_at | timestamptz | 创建时间 |
| created_by_user_id | UUID | 创建人，可空仅限系统任务 |
| updated_at | timestamptz | 最近修改时间 |
| updated_by_user_id | UUID | 最近修改人 |
| version_no | integer | 业务版本，不是乐观锁通用字段 |
| archived_at | timestamptz | 业务归档时间 |

不为所有表机械添加 <code>deleted_at</code>。需要保留历史的对象使用状态或归档；临时会话和未引用文件可以物理清理。

### JSONB 使用边界

JSONB 仅用于结构天然变化或需要保留原始载荷的数据：

- 第三方来源原始行
- Adapter 解析警告
- 模型原始结构化响应
- 审核前后快照
- 评分明细快照
- 日志附加元数据

以下内容必须结构化成列或明细表：

- 用户和角色
- 任务状态
- 标准技能 ID
- 简历技能
- 岗位技能要求
- 匹配维度和技能差距
- 审核决定
- 图谱版本和发布状态

### Evidence 契约

所有智能抽取候选必须有 Evidence。Evidence 最少包含：

| 字段 | 说明 |
| --- | --- |
| source_type | raw_job、normalized_job、resume、recruitment_jd |
| source_id | 来源业务记录 UUID |
| field_path | 来源字段，例如 normalized_text |
| quote | 原文片段 |
| start_offset | 可确定时记录字符起点 |
| end_offset | 可确定时记录字符终点 |
| page_no | PDF 可确定时记录页码 |
| extraction_method | rule、algorithm、llm、manual |
| confidence | 0 到 1，可空仅限人工录入 |

后端必须验证：

- <code>source_id</code> 存在且调用者有权访问
- quote 是对应文本真实子串，或 Offset 能准确截取同一内容
- <code>start_offset &lt; end_offset</code>
- confidence 在 0 到 1 之间
- 模型不能伪造数据库 ID

### API 版本与基础路径

- 对外业务 API 基础路径：<code>/api/v1</code>
- Algorithm Service 使用内部路径，不加主系统 <code>/api/v1</code>
- 第一版不使用 URL 中的细粒度 Schema 版本
- 破坏性变更才增加 <code>/api/v2</code>
- Prompt、算法、目录、图谱和匹配权重各自保存业务版本

### 认证与 Cookie

- 登录成功通过 <code>Set-Cookie</code> 设置不透明 Session Token
- Cookie 名建议为 <code>session</code>
- Cookie 使用 <code>HttpOnly=true</code>、<code>SameSite=Lax</code>
- HTTPS 环境使用 <code>Secure=true</code>
- 数据库只保存 Session Token 的哈希
- 状态修改请求必须携带 CSRF Header，例如 <code>X-CSRF-Token</code>
- API 响应不返回 Session Token 和密码哈希

### 请求追踪与幂等

每个请求支持 <code>X-Request-ID</code>。未提供时由 API 生成，并通过响应 Header 返回。

以下创建或启动接口支持 <code>Idempotency-Key</code>：

- 创建导入批次
- 启动批次处理
- 上传并解析简历
- 启动招聘项目匹配
- 创建 applicant 岗位推荐
- 创建成长路径
- 发布图谱版本

同一用户、同一接口和同一 Idempotency Key：

- 请求体哈希相同：返回已创建资源
- 请求体哈希不同：返回 <code>409 IDEMPOTENCY_KEY_REUSED</code>
- 默认保留 24 小时；图谱发布幂等记录永久保留

### 成功响应

单资源：

~~~json
{
  "data": {
    "id": "4b1087b8-14b1-4bb0-afca-35f601e04b34",
    "status": "active"
  }
}
~~~

分页列表：

~~~json
{
  "data": [
    {
      "id": "4b1087b8-14b1-4bb0-afca-35f601e04b34",
      "name": "Python"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 1,
    "total_pages": 1
  }
}
~~~

异步受理统一返回 HTTP 202：

~~~json
{
  "data": {
    "resource_id": "40c01892-fbce-4e41-a8b7-761a9f33fbd9",
    "run_id": "a05aec27-1ea1-48d7-a57b-66c6419c4a34",
    "status": "pending",
    "poll_url": "/api/v1/processing-runs/a05aec27-1ea1-48d7-a57b-66c6419c4a34"
  }
}
~~~

### 分页、筛选和排序

第一版使用页码分页，足以覆盖内部系统和当前数据量：

| 参数 | 默认值 | 限制 |
| --- | ---: | --- |
| page | 1 | 大于等于 1 |
| page_size | 20 | 1 到 100 |
| sort | 各接口定义 | 只允许白名单字段 |
| order | desc | asc 或 desc |

规则：

- API 不接受任意 SQL 字段名
- 每个列表接口明确筛选白名单
- 总数查询与列表查询使用同一权限范围
- 候选排序接口固定使用 <code>overall_score desc</code>、<code>skill_score desc</code>、<code>created_at asc</code>
- 导入原始行使用 <code>row_number asc</code>

### 错误响应

~~~json
{
  "error": {
    "code": "RESUME_NOT_READY",
    "message": "简历画像尚未完成解析",
    "request_id": "req_01J4VY57ABCD1234",
    "details": {
      "resume_id": "b7e8c612-358e-4e09-8256-e9012706ec7a",
      "current_status": "processing"
    }
  }
}
~~~

错误原则：

- message 面向用户，不暴露堆栈和连接字符串
- code 稳定，可供前端分支处理
- details 只包含安全的结构化上下文
- 所有 5xx 响应包含 Request ID
- 逐行和逐项错误通过 Processing Errors 查询，不塞入一个超大响应

### HTTP 状态码

| 状态码 | 使用场景 |
| ---: | --- |
| 200 | 查询、更新、同步动作成功 |
| 201 | 同步创建资源成功 |
| 202 | 后台任务已受理 |
| 204 | 登出或无响应体动作成功 |
| 400 | 参数组合非法 |
| 401 | 未登录或 Session 失效 |
| 403 | 角色或所有权不允许 |
| 404 | 资源不存在或调用者不可见 |
| 409 | 状态冲突、重复审核、幂等冲突 |
| 413 | 文件超过大小限制 |
| 415 | 文件类型不支持 |
| 422 | 字段校验失败 |
| 429 | 登录限流或外部依赖限流映射 |
| 500 | 未处理的内部错误 |
| 502 | Algorithm Service 或 LLM 返回无效响应 |
| 503 | 必需依赖不可用 |

### 通用错误码

| 错误码 | HTTP | 含义 |
| --- | ---: | --- |
| AUTH_REQUIRED | 401 | 需要登录 |
| INVALID_CREDENTIALS | 401 | 用户名或密码错误 |
| SESSION_EXPIRED | 401 | 会话过期 |
| CSRF_VALIDATION_FAILED | 403 | CSRF 校验失败 |
| ROLE_NOT_ALLOWED | 403 | 角色不允许 |
| RESOURCE_NOT_OWNED | 404 | 资源不在调用者权限范围 |
| RESOURCE_STATE_CONFLICT | 409 | 当前状态不允许动作 |
| IDEMPOTENCY_KEY_REUSED | 409 | 幂等键被不同请求复用 |
| FILE_TOO_LARGE | 413 | 文件过大 |
| FILE_TYPE_NOT_ALLOWED | 415 | 文件类型不允许 |
| VALIDATION_FAILED | 422 | 业务字段校验失败 |
| DEPENDENCY_UNAVAILABLE | 503 | 外部或内部依赖不可用 |
| INTERNAL_ERROR | 500 | 未预期错误 |

## 💾 PostgreSQL 总体设计

### Schema 与扩展

第一版使用一个业务 Schema：<code>public</code>。不按模块创建多个 PostgreSQL Schema，避免增加 Alembic、权限和查询复杂度。

需要启用：

~~~sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
~~~

用途：

| 扩展 | 用途 |
| --- | --- |
| vector | 保存 Embedding 并执行向量召回 |
| pg_trgm | 技能、别名、岗位名称和搜索文本的模糊检索 |

UUID 由应用生成，不依赖数据库 UUID 扩展。

### 领域分组

| 领域 | 核心表 |
| --- | --- |
| Identity | users、auth_sessions、login_attempts、audit_logs |
| Files | stored_files、file_access_logs |
| Task | processing_runs、processing_errors、idempotency_records |
| Import | data_sources、import_batches、raw_job_postings、normalized_job_postings、duplicate_clusters、duplicate_cluster_members |
| Catalog | catalog_versions、catalog_version_items、catalog_imports、domains、capabilities、capability_aliases、job_roles、job_role_aliases、learning_resources、capability_submissions |
| Extraction | job_analysis_profiles、job_skill_candidates、model_invocations、evidence_spans、embedding_records |
| Discovery | discovery_runs、skill_combination_candidates、combination_skills、combination_evidence、business_feedback |
| Review | graph_change_candidates、review_decisions |
| Graph | graph_versions、graph_version_items、graph_publications、graph_settings |
| Resume | resumes、resume_profiles、resume_educations、resume_experiences、resume_projects、resume_skills |
| Recruitment | recruitment_projects、job_descriptions、job_requirement_skills、candidate_records、candidate_materials、candidate_imports |
| Matching | match_weight_versions、match_runs、match_results、match_dimension_details、match_skill_details、match_condition_details |
| Growth | growth_plans、growth_steps、growth_step_resources |

### 跨领域关系概览

~~~mermaid
erDiagram
    accTitle: Core Business Relationship Map
    accDescr: High-level relationship map connecting users, imports, catalog facts, discovery and graph publication, resumes, recruitment projects, matches, and growth plans

    USERS ||--o{ PROCESSING_RUNS : "starts"
    USERS ||--o{ STORED_FILES : "uploads"
    IMPORT_BATCHES ||--o{ RAW_JOB_POSTINGS : "contains"
    RAW_JOB_POSTINGS ||--o| NORMALIZED_JOB_POSTINGS : "normalizes"
    NORMALIZED_JOB_POSTINGS ||--o{ JOB_ANALYSIS_PROFILES : "analyzed by"
    JOB_ANALYSIS_PROFILES ||--o{ JOB_SKILL_CANDIDATES : "extracts"
    CAPABILITIES ||--o{ JOB_SKILL_CANDIDATES : "maps"
    DISCOVERY_RUNS ||--o{ SKILL_COMBINATION_CANDIDATES : "produces"
    SKILL_COMBINATION_CANDIDATES ||--o{ GRAPH_CHANGE_CANDIDATES : "proposes"
    GRAPH_CHANGE_CANDIDATES ||--o{ REVIEW_DECISIONS : "reviewed by"
    GRAPH_VERSIONS ||--o{ GRAPH_VERSION_ITEMS : "includes"
    USERS o|--o{ RESUMES : "owns"
    RESUMES ||--o{ RESUME_PROFILES : "versions"
    RECRUITMENT_PROJECTS ||--o{ CANDIDATE_RECORDS : "contains"
    CANDIDATE_RECORDS o|--o{ RESUMES : "attaches"
    RESUME_PROFILES ||--o{ MATCH_RESULTS : "evaluated"
    JOB_DESCRIPTIONS ||--o{ MATCH_RESULTS : "targets"
    MATCH_RESULTS ||--o{ GROWTH_PLANS : "informs"
~~~

该图只表达主干。具体字段和约束以下文为准。

### 删除与保留策略

| 数据 | 删除策略 |
| --- | --- |
| 用户 | 停用，不物理删除 |
| Session | 到期后可批量物理删除 |
| 登录失败记录 | 保留 90 天后清理 |
| 审计日志 | 比赛期全部保留 |
| 原始 JD | 不删除，只允许批次归档 |
| 标准技能、岗位 | deprecated，不物理删除 |
| 抽取候选 | 保留，允许 invalid/rejected |
| 审核决定 | 追加写，不删除不覆盖 |
| 图谱版本 | 不删除 |
| 简历和附件 | owner 可请求归档；演示期由 admin 执行受控清理 |
| 匹配结果 | 不覆盖，保留历史版本 |
| Growth Plan | 可归档，不物理覆盖 |
| 未引用上传文件 | 定时清理 |

### 外键删除规则

默认使用 <code>ON DELETE RESTRICT</code>，防止业务历史被级联删除。

允许级联删除的范围仅限：

- auth_sessions 随临时测试用户物理清理
- 未开始处理的临时上传记录
- 尚未确认保存的临时明细草稿

正式业务实现中不通过删除用户触发级联删除。

### 索引原则

- 所有外键列根据查询路径建立 B-tree 索引
- 所有唯一业务键建立 Unique Constraint
- 列表接口的权限列与排序列建立复合索引
- 状态队列使用 Partial Index
- 名称检索使用 <code>GIN (... gin_trgm_ops)</code>
- JSONB 仅对实际筛选的路径建立表达式索引，不建立全字段 GIN
- pgvector 索引在数据量达到需要时建立，第一版允许精确搜索
- 不为低基数单列状态机械建立普通索引

## 🔐 Identity、Session 与审计表

### users

用途：保存三种内部账号。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK，应用生成 |
| username | varchar(64) | 否 | 登录名原值 |
| username_normalized | varchar(64) | 否 | trim + lowercase，UNIQUE |
| password_hash | varchar(255) | 否 | Argon2id 编码字符串 |
| display_name | varchar(100) | 否 | 页面和审计显示名 |
| role | varchar(20) | 否 | CHECK applicant/hr/admin |
| is_active | boolean | 否 | 默认 true |
| password_changed_at | timestamptz | 否 | 创建或重置时更新 |
| last_login_at | timestamptz | 是 | 最近成功登录 |
| created_by_user_id | uuid | 是 | FK users；首个 admin 可为空 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (username_normalized)
CHECK (role IN ('applicant', 'hr', 'admin'))
CHECK (length(username_normalized) BETWEEN 3 AND 64)
~~~

索引：

- Unique：username_normalized
- Partial：<code>(role, created_at DESC) WHERE is_active = true</code>

规则：

- 不保存邮箱作为登录必需字段
- admin 可以创建账号、重置密码、停用账号和修改角色
- 不允许用户把自己的 role 改为 admin
- 最后一个有效 admin 不允许被停用或降级
- 停用账号必须同事务撤销全部 Session

### auth_sessions

用途：服务器端 Session。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| user_id | uuid | 否 | FK users |
| token_hash | char(64) | 否 | SHA-256，UNIQUE |
| csrf_token_hash | char(64) | 否 | CSRF Token 哈希 |
| expires_at | timestamptz | 否 | 绝对到期时间 |
| revoked_at | timestamptz | 是 | 登出、停用或重置密码 |
| last_seen_at | timestamptz | 否 | 默认 now()，节流更新 |
| ip_address | inet | 是 | 安全审计 |
| user_agent | varchar(500) | 是 | 截断保存 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

- Unique：token_hash
- Check：expires_at > created_at
- 有效条件：revoked_at IS NULL AND expires_at > now()

索引：

- <code>(user_id, expires_at DESC)</code>
- Partial：<code>(expires_at) WHERE revoked_at IS NULL</code>

### login_attempts

用途：支持登录限流和安全审计，不记录密码。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| username_normalized | varchar(64) | 否 | 尝试的用户名 |
| user_id | uuid | 是 | 成功匹配到账号时填写 |
| success | boolean | 否 | 登录结果 |
| failure_code | varchar(50) | 是 | invalid_credentials、inactive 等 |
| ip_address | inet | 是 | 来源地址 |
| request_id | varchar(64) | 否 | 请求追踪 |
| created_at | timestamptz | 否 | 默认 now() |

索引：

- <code>(username_normalized, created_at DESC)</code>
- <code>(ip_address, created_at DESC)</code>

限流建议：同一用户名或 IP 在 10 分钟内连续失败 10 次，返回 429。第一版可以在 PostgreSQL 查询实现，不增加独立限流组件。

### audit_logs

用途：追加记录关键操作。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| actor_user_id | uuid | 是 | 系统动作可空 |
| action | varchar(100) | 否 | 稳定动作代码 |
| resource_type | varchar(80) | 否 | 资源类型 |
| resource_id | uuid | 是 | 目标 ID |
| outcome | varchar(20) | 否 | success、denied、failed |
| request_id | varchar(64) | 是 | HTTP 或任务 Request ID |
| processing_run_id | uuid | 是 | 后台任务来源 |
| ip_address | inet | 是 | HTTP 操作来源 |
| metadata | jsonb | 否 | 默认空对象，不能含完整敏感正文 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (outcome IN ('success', 'denied', 'failed'))
~~~

索引：

- <code>(actor_user_id, created_at DESC)</code>
- <code>(resource_type, resource_id, created_at DESC)</code>
- <code>(action, created_at DESC)</code>

应用不提供 UPDATE 和 DELETE Audit Log 的 Repository 方法。

## 📦 文件、任务与幂等表

### stored_files

用途：保存文件元数据，实际内容在本地 Volume。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK，同时作为 Storage Key 的一部分 |
| uploaded_by_user_id | uuid | 否 | FK users |
| original_name | varchar(255) | 否 | 仅展示，不用于文件路径 |
| storage_key | varchar(255) | 否 | UNIQUE，相对受控根目录 |
| media_type | varchar(150) | 否 | 服务端检测结果 |
| extension | varchar(20) | 否 | 规范化小写扩展名 |
| size_bytes | bigint | 否 | 大于 0 |
| sha256 | char(64) | 否 | 文件内容哈希 |
| category | varchar(50) | 否 | market_jd、catalog、resume、jd、portfolio、other |
| scan_status | varchar(30) | 否 | pending、clean、rejected、not_required |
| status | varchar(30) | 否 | uploaded、attached、archived、deleted |
| expires_at | timestamptz | 是 | 临时未绑定文件过期时间 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (storage_key)
CHECK (size_bytes > 0)
CHECK (category IN ('market_jd', 'catalog', 'resume', 'jd', 'portfolio', 'other'))
CHECK (scan_status IN ('pending', 'clean', 'rejected', 'not_required'))
CHECK (status IN ('uploaded', 'attached', 'archived', 'deleted'))
~~~

索引：

- <code>(uploaded_by_user_id, created_at DESC)</code>
- <code>(sha256, size_bytes)</code>
- Partial：<code>(expires_at) WHERE status = 'uploaded' AND expires_at IS NOT NULL</code>

文件限制建议：

| 类别 | 格式 | 单文件大小 |
| --- | --- | ---: |
| 市场 JD | csv、xlsx、json、txt | 50 MB |
| Catalog 骨架 | csv、xlsx、json | 50 MB |
| 简历 | pdf、docx | 20 MB |
| 招聘 JD | pdf、docx、txt | 20 MB |
| 作品集附件 | pdf、docx、pptx、zip、常见图片、mp4、webm | 100 MB |

### file_access_logs

用途：记录敏感简历、作品集和原始文件的下载或预览。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| file_id | uuid | 否 | FK stored_files |
| user_id | uuid | 否 | FK users |
| action | varchar(20) | 否 | preview、download |
| request_id | varchar(64) | 否 | 请求 ID |
| created_at | timestamptz | 否 | 默认 now() |

### processing_runs

用途：所有长任务的正式状态源。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| run_type | varchar(60) | 否 | 任务类型 |
| subject_type | varchar(50) | 否 | 目标资源类型 |
| subject_id | uuid | 否 | 目标资源 ID |
| retry_of_run_id | uuid | 是 | FK processing_runs，重试来源 |
| created_by_user_id | uuid | 否 | FK users |
| owner_scope_type | varchar(30) | 否 | user、recruitment_project、admin_global |
| owner_scope_id | uuid | 是 | user/project 范围 ID |
| status | varchar(30) | 否 | 正式状态 |
| current_stage | varchar(60) | 是 | 当前阶段 |
| pipeline_version | varchar(80) | 否 | 处理管线版本 |
| celery_task_id | varchar(100) | 是 | 诊断字段 |
| total_count | integer | 否 | 默认 0 |
| processed_count | integer | 否 | 默认 0 |
| success_count | integer | 否 | 默认 0 |
| failed_count | integer | 否 | 默认 0 |
| progress_percent | numeric(5,2) | 否 | 默认 0 |
| cancel_requested | boolean | 否 | 默认 false |
| attempt_count | integer | 否 | 默认 0 |
| max_attempts | integer | 否 | 默认 1 |
| input_snapshot | jsonb | 否 | 去敏后的任务输入 |
| result_summary | jsonb | 否 | 默认空对象 |
| error_code | varchar(80) | 是 | 最终错误码 |
| error_message | text | 是 | 安全错误描述 |
| enqueued_at | timestamptz | 是 | 投递时间 |
| started_at | timestamptz | 是 | 首次开始时间 |
| heartbeat_at | timestamptz | 是 | Worker 心跳 |
| completed_at | timestamptz | 是 | 终态时间 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

状态：

~~~text
pending
enqueue_failed
running
waiting_review
cancel_requested
completed
failed
cancelled
~~~

约束：

~~~sql
CHECK (owner_scope_type IN ('user', 'recruitment_project', 'admin_global'))
CHECK (
  (owner_scope_type = 'admin_global' AND owner_scope_id IS NULL)
  OR
  (owner_scope_type IN ('user', 'recruitment_project') AND owner_scope_id IS NOT NULL)
)
CHECK (total_count >= 0)
CHECK (processed_count >= 0 AND processed_count <= total_count)
CHECK (success_count >= 0 AND failed_count >= 0)
CHECK (progress_percent BETWEEN 0 AND 100)
CHECK (attempt_count >= 0 AND max_attempts >= 1)
~~~

索引：

- <code>(created_by_user_id, created_at DESC)</code>
- <code>(owner_scope_type, owner_scope_id, created_at DESC)</code>
- <code>(subject_type, subject_id, created_at DESC)</code>
- Partial：<code>(created_at) WHERE status IN ('pending', 'enqueue_failed')</code>
- Partial：<code>(heartbeat_at) WHERE status = 'running'</code>

### processing_errors

用途：保存批处理中的逐项错误。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| run_id | uuid | 否 | FK processing_runs |
| stage | varchar(60) | 否 | 失败阶段 |
| item_type | varchar(50) | 是 | row、resume、candidate 等 |
| item_id | uuid | 是 | 业务 ID |
| item_key | varchar(200) | 是 | 行号或外部键 |
| error_code | varchar(80) | 否 | 稳定代码 |
| message | text | 否 | 安全描述 |
| retryable | boolean | 否 | 是否可重试 |
| details | jsonb | 否 | 默认空对象 |
| occurred_at | timestamptz | 否 | 默认 now() |

索引：

- <code>(run_id, occurred_at)</code>
- <code>(run_id, stage, retryable)</code>

### idempotency_records

用途：实现创建和任务启动接口幂等。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| user_id | uuid | 否 | FK users |
| endpoint_key | varchar(120) | 否 | 稳定接口标识，不使用原始 URL 参数 |
| idempotency_key | varchar(128) | 否 | 客户端 Header |
| request_hash | char(64) | 否 | 规范化请求哈希 |
| response_status | integer | 是 | 完成后的 HTTP 状态 |
| response_body | jsonb | 是 | 完成后的安全响应 |
| resource_type | varchar(50) | 是 | 创建资源类型 |
| resource_id | uuid | 是 | 创建资源 ID |
| state | varchar(20) | 否 | processing、completed、failed |
| expires_at | timestamptz | 是 | 普通记录过期时间 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (user_id, endpoint_key, idempotency_key)
CHECK (state IN ('processing', 'completed', 'failed'))
~~~

## 📥 市场 JD 导入与标准化表

### data_sources

用途：定义数据来源和 Adapter。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| code | varchar(50) | 否 | UNIQUE，例如 liepin |
| display_name | varchar(100) | 否 | 展示名称 |
| adapter_code | varchar(80) | 否 | liepin_v1、zhilian_v1 |
| adapter_version | varchar(40) | 否 | 具体实现版本 |
| source_type | varchar(30) | 否 | file_import、crawler、manual |
| is_enabled | boolean | 否 | 默认 true |
| config | jsonb | 否 | 非敏感 Adapter 配置 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

第一版 Seed：

| code | adapter_code | source_type |
| --- | --- | --- |
| standard | standard_v1 | file_import |
| liepin | liepin_v1 | file_import |
| zhilian | zhilian_v1 | file_import |
| zhilian_direct | zhilian_v1 | file_import |

### import_batches

用途：一次市场 JD 文件导入批次。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| source_id | uuid | 否 | FK data_sources |
| file_id | uuid | 否 | FK stored_files |
| uploaded_by_user_id | uuid | 否 | FK users，必须 admin |
| detected_adapter_code | varchar(80) | 是 | 后台识别后写入 |
| adapter_version | varchar(40) | 是 | 后台识别后写入 |
| schema_version | varchar(40) | 是 | 标准输入 Schema 版本 |
| collected_at | timestamptz | 否 | 数据采集或导入锚点 |
| status | varchar(30) | 否 | uploaded、processing、processed、partial、failed、archived |
| total_rows | integer | 否 | 默认 0 |
| accepted_rows | integer | 否 | 默认 0 |
| rejected_rows | integer | 否 | 默认 0 |
| warning_rows | integer | 否 | 默认 0 |
| batch_summary | jsonb | 否 | 字段缺失与警告汇总 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (status IN ('uploaded', 'processing', 'processed', 'partial', 'failed', 'archived'))
CHECK (total_rows >= 0 AND accepted_rows >= 0 AND rejected_rows >= 0 AND warning_rows >= 0)
CHECK (accepted_rows + rejected_rows <= total_rows)
~~~

索引：

- <code>(created_at DESC)</code>
- <code>(source_id, collected_at DESC)</code>
- <code>(status, created_at DESC)</code>

### raw_job_postings

用途：按行保存不可变的来源事实。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| batch_id | uuid | 否 | FK import_batches |
| row_number | integer | 否 | 文件中的一基行号 |
| source_code | varchar(50) | 否 | 冗余保存来源，便于追踪 |
| external_id | varchar(150) | 是 | 来源平台稳定 ID |
| source_url | text | 是 | 来源详情页 |
| job_name | text | 否 | 原始岗位名 |
| company_name | text | 是 | 原始公司名 |
| salary_text | text | 是 | 原始薪资 |
| work_area_text | text | 是 | 原始地区 |
| city_text | text | 是 | 原始城市 |
| education_text | text | 是 | 原始学历 |
| work_year_text | text | 是 | 原始经验 |
| issue_date_text | text | 是 | 原始发布日期 |
| raw_text | text | 是 | 原始 JD 正文；来源确实缺失时可空 |
| source_tags | jsonb | 否 | 默认空数组 |
| raw_payload | jsonb | 否 | 完整原始行 |
| source_encoding | varchar(30) | 是 | 检测到的编码 |
| parse_warnings | jsonb | 否 | 默认空数组 |
| content_hash | char(64) | 是 | 有正文时生成 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (batch_id, row_number)
CHECK (row_number >= 1)
CHECK (length(trim(job_name)) > 0)
~~~

索引：

- <code>(batch_id, row_number)</code>
- <code>(source_code, external_id)</code>
- <code>(content_hash)</code> WHERE content_hash IS NOT NULL
- <code>(source_url)</code> WHERE source_url IS NOT NULL

不可变规则：

- Repository 不提供 UPDATE 原始字段的方法
- 发现 Adapter 错误时创建新的标准化版本，不改 Raw JD
- 只有批次归档，不删除单行
- <code>raw_payload</code> 保留导入时的原值，不存后续算法输出

### normalized_job_postings

用途：保存可版本化的规范化结果。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| raw_job_id | uuid | 否 | FK raw_job_postings |
| version_no | integer | 否 | 同一 Raw JD 单调递增 |
| normalization_version | varchar(80) | 否 | 规则和 Adapter 版本 |
| normalized_title | varchar(300) | 否 | 清洗岗位名 |
| company_name | varchar(300) | 是 | 清洗公司名 |
| city_code | varchar(30) | 是 | 标准行政区代码或项目代码 |
| city_name | varchar(100) | 是 | 规范城市名 |
| work_area | varchar(200) | 是 | 详细地区 |
| salary_min_monthly | integer | 是 | 月薪最小值 |
| salary_max_monthly | integer | 是 | 月薪最大值 |
| salary_months | numeric(4,1) | 是 | 例如 13 薪 |
| education_level | varchar(30) | 是 | 规范学历 |
| experience_min_months | integer | 是 | 最低经验 |
| experience_max_months | integer | 是 | 最高经验 |
| published_at | date | 是 | 解析后的发布日期 |
| normalized_text | text | 是 | 清洗后的正文 |
| quality_score | numeric(5,2) | 否 | 0 到 100 |
| quality_flags | jsonb | 否 | 默认空数组 |
| duplicate_of_id | uuid | 是 | FK normalized_job_postings 代表记录 |
| is_current | boolean | 否 | 同一 Raw JD 仅一个 true |
| created_by_run_id | uuid | 是 | FK processing_runs，模型解析版本必填 |
| created_by_user_id | uuid | 是 | FK users，人工修订版本必填 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (raw_job_id, version_no)
CHECK (version_no >= 1)
CHECK (quality_score BETWEEN 0 AND 100)
CHECK (salary_min_monthly IS NULL OR salary_min_monthly >= 0)
CHECK (salary_max_monthly IS NULL OR salary_max_monthly >= salary_min_monthly)
CHECK (experience_min_months IS NULL OR experience_min_months >= 0)
CHECK (experience_max_months IS NULL OR experience_max_months >= experience_min_months)
~~~

索引：

- Unique Partial：<code>(raw_job_id) WHERE is_current = true</code>
- <code>(published_at DESC)</code>
- <code>(city_code, published_at DESC)</code>
- <code>(quality_score DESC)</code>
- <code>(duplicate_of_id)</code>
- Trigram：normalized_title

学历枚举：

~~~text
unknown
below_high_school
high_school
associate
bachelor
master
doctorate
~~~

### duplicate_clusters

用途：保存相似 JD 去重簇，避免复制 JD 重复放大支持度。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| algorithm | varchar(50) | 否 | exact_hash、semantic_cluster |
| algorithm_version | varchar(80) | 否 | 版本 |
| representative_job_id | uuid | 否 | FK normalized_job_postings |
| cluster_size | integer | 否 | 大于等于 1 |
| similarity_threshold | numeric(5,4) | 是 | 语义簇阈值 |
| created_by_run_id | uuid | 否 | FK processing_runs |
| created_at | timestamptz | 否 | 默认 now() |

### duplicate_cluster_members

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| cluster_id | uuid | 否 | FK duplicate_clusters |
| job_id | uuid | 否 | FK normalized_job_postings |
| similarity | numeric(5,4) | 否 | 0 到 1 |
| is_representative | boolean | 否 | 代表记录标志 |

约束：

~~~sql
PRIMARY KEY (cluster_id, job_id)
UNIQUE (job_id)
CHECK (similarity BETWEEN 0 AND 1)
~~~

每个 Cluster 只能有一个代表记录，通过事务校验和 Partial Unique Index 实现。

### JD 质量分

质量分由确定性规则计算，不由 LLM 自报。建议第一版权重：

| 项目 | 分值 |
| --- | ---: |
| 有完整正文 | 35 |
| 有岗位名称 | 10 |
| 有公司名称 | 10 |
| 有地区 | 10 |
| 有发布日期或采集时间 | 10 |
| 有学历或经验 | 10 |
| 编码正常 | 10 |
| 有来源 URL 或外部 ID | 5 |

严重乱码、正文过短、城市冲突、发布日期不确定等写入 <code>quality_flags</code>。质量分影响候选支持度，但不自动删除数据。

## 🗂️ 标准技能、岗位与学习资料表

### catalog_versions

用途：记录标准技能和岗位目录的正式版本。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| version_no | integer | 否 | UNIQUE，单调递增 |
| status | varchar(20) | 否 | draft、published |
| base_version_id | uuid | 是 | FK catalog_versions，首版可空 |
| change_summary | text | 否 | 版本摘要 |
| created_by_user_id | uuid | 否 | FK users |
| published_at | timestamptz | 是 | 发布时间 |
| created_at | timestamptz | 否 | 默认 now() |

不涉及 Neo4j 拓扑的管理员目录修改，可以在同一 PostgreSQL 事务创建 Catalog Version、Version Item、更新 Active 主数据并发布版本。涉及新图节点或正式关系的变更使用 Draft Catalog Version，并与 Graph Version 一起发布。比赛期不实现复杂分支合并。

### catalog_version_items

用途：保存每个目录版本中的主数据变更，保证标准技能和岗位名称变化可追溯。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| entity_type | varchar(30) | 否 | domain、capability、capability_alias、job_role、job_role_alias |
| entity_id | uuid | 否 | 被修改实体 ID |
| operation | varchar(20) | 否 | create、update、deprecate、reject |
| before_payload | jsonb | 是 | 创建操作可空 |
| after_payload | jsonb | 否 | 变更后快照 |
| sequence_no | integer | 否 | 版本内稳定顺序 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (catalog_version_id, sequence_no)
CHECK (entity_type IN ('domain', 'capability', 'capability_alias', 'job_role', 'job_role_alias'))
CHECK (operation IN ('create', 'update', 'deprecate', 'reject'))
CHECK (sequence_no >= 1)
~~~

### catalog_imports

用途：批量导入初始技能库、别名和岗位骨架，不与市场 JD Import 混用。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| file_id | uuid | 否 | FK stored_files |
| import_type | varchar(30) | 否 | capability、capability_alias、job_role、job_role_alias |
| schema_version | varchar(40) | 否 | 标准模板版本 |
| mode | varchar(20) | 否 | validate_only、apply |
| status | varchar(30) | 否 | pending、processing、validated、applied、partial、failed |
| processing_run_id | uuid | 否 | FK processing_runs |
| catalog_version_id | uuid | 是 | apply 成功后创建的版本 |
| total_rows | integer | 否 | 默认 0 |
| accepted_rows | integer | 否 | 默认 0 |
| rejected_rows | integer | 否 | 默认 0 |
| summary | jsonb | 否 | 默认空对象 |
| created_by_user_id | uuid | 否 | FK users，必须 admin |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (import_type IN ('capability', 'capability_alias', 'job_role', 'job_role_alias'))
CHECK (mode IN ('validate_only', 'apply'))
CHECK (status IN ('pending', 'processing', 'validated', 'applied', 'partial', 'failed'))
CHECK (total_rows >= 0 AND accepted_rows >= 0 AND rejected_rows >= 0)
~~~

apply 模式先完整验证模板、名称冲突、Domain 和外部 ID，再在一个 Catalog Version 下分 Chunk 写入。单行错误允许 partial，但错误行不得写入主数据；Catalog Version Item 保存每个实际变更的快照。

### domains

用途：技术领域树，例如 AI、大数据、物联网。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| parent_id | uuid | 是 | 自关联 FK |
| code | varchar(80) | 否 | UNIQUE |
| name | varchar(100) | 否 | 领域名 |
| description | text | 是 | 说明 |
| sort_order | integer | 否 | 默认 0 |
| status | varchar(20) | 否 | active、deprecated |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：parent_id 不能等于 id。循环关系由 Service 在事务内检查。

### capabilities

用途：标准技能唯一身份源。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| domain_id | uuid | 否 | FK domains |
| canonical_name | varchar(200) | 否 | 标准名称 |
| normalized_name | varchar(200) | 否 | 规范化比较值 |
| description | text | 是 | 审核后的技能描述 |
| skill_type | varchar(30) | 否 | technical、tool、method、domain_knowledge、soft_skill |
| status | varchar(20) | 否 | candidate、active、deprecated、rejected |
| source_type | varchar(30) | 否 | seed、public_standard、jd_discovery、manual |
| source_name | varchar(150) | 是 | 来源词表或说明 |
| source_version | varchar(80) | 是 | 外部来源版本 |
| external_id | varchar(150) | 是 | 外部词表 ID |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| replacement_capability_id | uuid | 是 | deprecated 后替代技能 |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (domain_id, normalized_name)
CHECK (skill_type IN ('technical', 'tool', 'method', 'domain_knowledge', 'soft_skill'))
CHECK (status IN ('candidate', 'active', 'deprecated', 'rejected'))
CHECK (source_type IN ('seed', 'public_standard', 'jd_discovery', 'manual'))
CHECK (replacement_capability_id IS NULL OR replacement_capability_id <> id)
~~~

索引：

- <code>(domain_id, status, canonical_name)</code>
- Trigram：canonical_name、normalized_name
- <code>(source_name, external_id)</code> WHERE external_id IS NOT NULL

业务规则：

- 只有 active Capability 可用于新的正式映射和图谱关系
- candidate 可以出现在审核页面，不可用于正式匹配计分
- deprecated 保留历史引用，新的匹配应映射到 replacement
- rejected 不允许重新激活，需创建新 Candidate 并保留关联说明
- 修改 canonical_name 必须同时保留旧名为 Alias

### capability_aliases

用途：保存技能别名和歧义。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| capability_id | uuid | 否 | FK capabilities |
| alias | varchar(200) | 否 | 原始别名 |
| normalized_alias | varchar(200) | 否 | 规范化值 |
| language | varchar(20) | 否 | 默认 zh-CN |
| status | varchar(20) | 否 | candidate、active、rejected、deprecated |
| source_type | varchar(30) | 否 | seed、jd、resume、manual |
| evidence_count | integer | 否 | 默认 0 |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (capability_id, normalized_alias, language)
CHECK (status IN ('candidate', 'active', 'rejected', 'deprecated'))
CHECK (source_type IN ('seed', 'jd', 'resume', 'manual'))
CHECK (evidence_count >= 0)
~~~

同一 <code>normalized_alias</code> 可以指向多个 Capability。自动映射前若查询到多个 active 指向，必须标记 ambiguous，不允许自动选择。

### job_roles

用途：标准岗位实体。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| domain_id | uuid | 否 | FK domains |
| canonical_name | varchar(200) | 否 | 标准岗位名 |
| normalized_name | varchar(200) | 否 | 规范化值 |
| description | text | 是 | 岗位定义 |
| core_responsibilities | jsonb | 否 | 审核后的职责数组 |
| typical_scenarios | jsonb | 否 | 行业场景数组 |
| status | varchar(20) | 否 | candidate、active、deprecated、rejected |
| source_type | varchar(30) | 否 | seed、discovery、manual |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| replacement_job_role_id | uuid | 是 | 替代岗位 |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束与索引与 capabilities 同类：

- Unique：<code>(domain_id, normalized_name)</code>
- Trigram：canonical_name、normalized_name
- status Check
- replacement 不能指向自己

### job_role_aliases

用途：映射招聘网站原始岗位名和标准岗位名。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| job_role_id | uuid | 否 | FK job_roles |
| alias | varchar(200) | 否 | 原始别名 |
| normalized_alias | varchar(200) | 否 | 规范化值 |
| language | varchar(20) | 否 | 默认 zh-CN |
| status | varchar(20) | 否 | candidate、active、rejected、deprecated |
| source_type | varchar(30) | 否 | seed、jd、discovery、manual |
| evidence_count | integer | 否 | 默认 0 |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (job_role_id, normalized_alias, language)
CHECK (status IN ('candidate', 'active', 'rejected', 'deprecated'))
CHECK (source_type IN ('seed', 'jd', 'discovery', 'manual'))
CHECK (evidence_count >= 0)
~~~

同一 normalized_alias 指向多个 Active Job Role 时视为歧义，岗位映射只能返回候选列表，不自动选择。

### learning_resources

用途：成长路径可引用的审核资料。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| capability_id | uuid | 否 | FK capabilities |
| title | varchar(300) | 否 | 资料标题 |
| url | text | 否 | 原始链接 |
| canonical_url_hash | char(64) | 否 | 去追踪参数后 URL 哈希 |
| resource_type | varchar(30) | 否 | documentation、course、book、tutorial、project |
| provider | varchar(150) | 是 | 来源平台 |
| language | varchar(20) | 否 | 默认 zh-CN |
| level | varchar(20) | 否 | beginner、intermediate、advanced |
| summary | text | 是 | 审核摘要 |
| review_status | varchar(20) | 否 | pending、approved、rejected、archived |
| reviewed_by_user_id | uuid | 是 | FK users |
| reviewed_at | timestamptz | 是 | 审核时间 |
| content_checked_at | timestamptz | 是 | 最近可用性检查 |
| is_available | boolean | 否 | 默认 true |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (capability_id, canonical_url_hash)
CHECK (resource_type IN ('documentation', 'course', 'book', 'tutorial', 'project'))
CHECK (level IN ('beginner', 'intermediate', 'advanced'))
CHECK (review_status IN ('pending', 'approved', 'rejected', 'archived'))
~~~

Growth Plan 只能引用 approved 且 is_available=true 的资料。

### capability_submissions

用途：接收 applicant、HR、模型或管理员提出的未知技能，不直接写正式 Catalog。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| submitted_by_user_id | uuid | 是 | 系统产生可空 |
| source_type | varchar(30) | 否 | resume、jd、discovery、manual |
| source_id | uuid | 否 | 来源业务记录 |
| raw_name | varchar(200) | 否 | 用户或模型原文 |
| normalized_name | varchar(200) | 否 | 规范化值 |
| suggested_domain_id | uuid | 是 | FK domains |
| suggested_capability_id | uuid | 是 | 可能映射目标 |
| status | varchar(30) | 否 | pending、mapped、created、rejected |
| resolution_note | text | 是 | 审核说明 |
| resolved_by_user_id | uuid | 是 | FK users |
| resolved_at | timestamptz | 是 | 完成时间 |
| created_at | timestamptz | 否 | 默认 now() |

相同来源和规范化名称不重复提交：

~~~sql
UNIQUE (source_type, source_id, normalized_name)
~~~

## 🧠 抽取、证据与模型调用表

### job_analysis_profiles

用途：保存一次 JD 结构化分析版本。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| normalized_job_id | uuid | 否 | FK normalized_job_postings |
| version_no | integer | 否 | 同一 JD 递增 |
| extraction_version | varchar(80) | 否 | 合并管线版本 |
| algorithm_model_version | varchar(80) | 是 | 算法版本 |
| llm_model | varchar(100) | 是 | LLM 模型 |
| prompt_version | varchar(80) | 是 | Prompt 版本 |
| suggested_job_role_id | uuid | 是 | FK job_roles，候选映射 |
| raw_job_family | varchar(200) | 是 | 模型岗位类别 |
| responsibilities | jsonb | 否 | 结构化职责候选 |
| education_requirement | jsonb | 是 | required/preferred 和等级 |
| experience_requirement | jsonb | 是 | required/preferred 和月数 |
| structured_payload | jsonb | 否 | 合并后的完整结构 |
| status | varchar(20) | 否 | candidate、validated、invalid |
| validation_errors | jsonb | 否 | 默认空数组 |
| created_by_run_id | uuid | 否 | FK processing_runs |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (normalized_job_id, version_no)
UNIQUE (normalized_job_id, extraction_version)
CHECK (status IN ('candidate', 'validated', 'invalid'))
~~~

同一输入、同一 Extraction Version 重复处理直接读取已有结果。强制重跑必须使用新的 Extraction Version 或显式创建新版本。

### job_skill_candidates

用途：保存 JD 中每个技能要求候选。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| analysis_profile_id | uuid | 否 | FK job_analysis_profiles |
| capability_id | uuid | 是 | FK capabilities，未映射时为空 |
| raw_name | varchar(200) | 否 | 原文技能名 |
| normalized_name | varchar(200) | 否 | 规范化值 |
| requirement_type | varchar(20) | 否 | required、preferred |
| importance | numeric(5,4) | 否 | 0 到 1 |
| required_level | varchar(20) | 是 | beginner/intermediate/advanced |
| mapping_method | varchar(30) | 否 | 精确、语义、人工或未映射 |
| mapping_status | varchar(20) | 否 | mapped、ambiguous、unmapped、invalid |
| extraction_source | varchar(20) | 否 | algorithm、llm、merged、manual |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (requirement_type IN ('required', 'preferred'))
CHECK (importance BETWEEN 0 AND 1)
CHECK (required_level IS NULL OR required_level IN ('beginner', 'intermediate', 'advanced'))
CHECK (mapping_method IN ('canonical_exact', 'alias_exact', 'normalized_exact', 'semantic_candidate', 'manual', 'unmapped'))
CHECK (mapping_status IN ('mapped', 'ambiguous', 'unmapped', 'invalid'))
CHECK (extraction_source IN ('algorithm', 'llm', 'merged', 'manual'))
CHECK (confidence BETWEEN 0 AND 1)
CHECK ((mapping_status = 'mapped') = (capability_id IS NOT NULL))
~~~

索引：

- <code>(analysis_profile_id, requirement_type)</code>
- <code>(capability_id)</code> WHERE capability_id IS NOT NULL
- <code>(mapping_status, created_at DESC)</code>

### evidence_spans

用途：统一保存 JD、简历、岗位和审核候选的证据片段。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| subject_type | varchar(50) | 否 | job_skill_candidate、resume_skill 等 |
| subject_id | uuid | 否 | 被证据支持的记录 ID |
| source_type | varchar(40) | 否 | raw_job、normalized_job、resume、recruitment_jd |
| source_id | uuid | 否 | 来源 ID |
| field_path | varchar(200) | 否 | 来源字段路径 |
| quote | text | 否 | 原文片段 |
| start_offset | integer | 是 | 字符起点 |
| end_offset | integer | 是 | 字符终点 |
| page_no | integer | 是 | 一基页码 |
| extraction_method | varchar(20) | 否 | rule、algorithm、llm、manual |
| confidence | numeric(5,4) | 是 | 人工证据可空 |
| verified | boolean | 否 | 默认 false |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (length(quote) > 0)
CHECK ((start_offset IS NULL AND end_offset IS NULL) OR (start_offset >= 0 AND end_offset > start_offset))
CHECK (page_no IS NULL OR page_no >= 1)
CHECK (extraction_method IN ('rule', 'algorithm', 'llm', 'manual'))
CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
~~~

由于 subject/source 是跨领域多态引用，数据库无法直接使用普通 FK。Service 必须在同一事务验证目标存在；后台一致性测试定期扫描孤儿引用。

### model_invocations

用途：记录 Algorithm Service、LLM 和 Embedding 调用。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| processing_run_id | uuid | 是 | FK processing_runs |
| provider_type | varchar(20) | 否 | algorithm、llm、embedding、ocr |
| operation | varchar(60) | 否 | analyze_jd、parse_resume 等 |
| provider_name | varchar(100) | 否 | 服务名 |
| model_name | varchar(100) | 是 | 模型名称 |
| model_version | varchar(100) | 是 | 模型版本 |
| prompt_version | varchar(80) | 是 | LLM Prompt 版本 |
| input_hash | char(64) | 否 | 去敏规范化输入哈希 |
| request_metadata | jsonb | 否 | 不含完整敏感正文 |
| response_payload | jsonb | 是 | 结构化原始输出；简历内容按权限保护 |
| status | varchar(20) | 否 | success、failed、invalid |
| duration_ms | integer | 是 | 大于等于 0 |
| token_input | integer | 是 | LLM 输入 Token |
| token_output | integer | 是 | LLM 输出 Token |
| error_code | varchar(80) | 是 | 稳定错误码 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

- status Check
- duration/token 非负
- <code>(provider_type, operation, input_hash, model_name, model_version, prompt_version)</code> 建普通索引用于复用查询

### embedding_records

用途：统一保存 pgvector 对象向量。

第一版确定一个 Embedding Model 后，Migration 将 <code>embedding</code> 定义为固定维度，例如 <code>vector(1024)</code>。不支持同表混用不同维度。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| source_type | varchar(40) | 否 | jd_chunk、capability、job_role、learning_resource |
| source_id | uuid | 否 | 来源业务 ID |
| chunk_no | integer | 否 | 默认 0 |
| content | text | 否 | 实际向量文本 |
| content_hash | char(64) | 否 | 内容哈希 |
| embedding_model | varchar(100) | 否 | 模型 |
| embedding_version | varchar(80) | 否 | 处理版本 |
| embedding | vector(1024) | 否 | 示例维度，实施前按模型确认 |
| metadata | jsonb | 否 | 过滤字段快照 |
| is_current | boolean | 否 | 默认 true |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (source_type, source_id, chunk_no, content_hash, embedding_model, embedding_version)
~~~

索引：

- Unique Partial：<code>(source_type, source_id, chunk_no) WHERE is_current = true</code>
- <code>(source_type, source_id)</code>
- 数据达到数万向量并确认召回性能后增加 HNSW；之前使用精确余弦检索

## 🔍 候选组合发现与业务反馈表

### discovery_runs

用途：一次候选技能组合发现实验。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| processing_run_id | uuid | 否 | FK processing_runs，UNIQUE |
| input_batch_ids | uuid[] | 否 | 输入批次 |
| current_graph_version_id | uuid | 是 | 对比的图谱版本 |
| algorithm_version | varchar(80) | 否 | 发现算法版本 |
| embedding_version | varchar(80) | 否 | 向量版本 |
| parameters | jsonb | 否 | 阈值和窗口快照 |
| status | varchar(20) | 否 | running、completed、failed |
| created_by_user_id | uuid | 否 | FK users，必须 admin |
| created_at | timestamptz | 否 | 默认 now() |

input_batch_ids 第一版使用 UUID Array 是为了保持文档和实现简洁；Service 必须逐项验证批次存在且已完成。若未来需要大量跨批次分析，再拆关联表。

### skill_combination_candidates

用途：保存技能共现和聚类产生的候选组合。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| discovery_run_id | uuid | 否 | FK discovery_runs |
| suggested_name | varchar(200) | 否 | LLM/算法建议名称 |
| normalized_name | varchar(200) | 否 | 规范化名称 |
| suggested_job_role_id | uuid | 是 | 已有岗位候选映射 |
| definition_payload | jsonb | 否 | 职责、技能和场景候选 |
| support_job_count | integer | 否 | 去重后的支持 JD 数 |
| source_count | integer | 否 | 独立来源数 |
| company_count | integer | 否 | 独立公司数 |
| support_score | numeric(5,4) | 否 | 支持度 |
| diversity_score | numeric(5,4) | 否 | 来源多样性 |
| coherence_score | numeric(5,4) | 否 | 聚类一致性 |
| novelty_score | numeric(5,4) | 否 | 相对图谱差异 |
| evidence_score | numeric(5,4) | 否 | 证据质量 |
| overall_candidate_score | numeric(5,4) | 否 | 候选排序分，不是市场趋势事实 |
| status | varchar(30) | 否 | candidate、feedback_collected、proposed_for_review、rejected |
| created_at | timestamptz | 否 | 默认 now() |

所有分数范围 0 到 1，计数非负。Unique：<code>(discovery_run_id, normalized_name)</code>。

第一版页面文案必须称为“候选技能组合”或“新岗位发现候选”，不能称为“已确认市场趋势”。

### combination_skills

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| candidate_id | uuid | 否 | FK skill_combination_candidates |
| capability_id | uuid | 否 | FK capabilities，必须 active |
| skill_role | varchar(20) | 否 | core、bonus |
| weight | numeric(5,4) | 否 | 0 到 1 |
| frequency | numeric(5,4) | 否 | 组合内出现率 |

主键：<code>(candidate_id, capability_id)</code>。

### combination_evidence

用途：候选组合与支持 JD 的关联。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| candidate_id | uuid | 否 | FK skill_combination_candidates |
| normalized_job_id | uuid | 否 | FK normalized_job_postings |
| duplicate_cluster_id | uuid | 是 | FK duplicate_clusters |
| evidence_weight | numeric(5,4) | 否 | 去重和质量调整后权重 |
| representative | boolean | 否 | 是否代表样本 |

主键：<code>(candidate_id, normalized_job_id)</code>。

### business_feedback

用途：HR 对新岗位发现候选的业务反馈。它不是全局知识审核。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| candidate_id | uuid | 否 | FK skill_combination_candidates |
| hr_user_id | uuid | 否 | FK users，role=hr |
| recruitment_project_id | uuid | 是 | 可选业务上下文 |
| decision | varchar(20) | 否 | adopt、revise、dismiss |
| revised_payload | jsonb | 是 | revise 时必填 |
| comment | text | 是 | 反馈 |
| supersedes_feedback_id | uuid | 是 | FK business_feedback，替代旧反馈 |
| is_current | boolean | 否 | 默认 true |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (decision IN ('adopt', 'revise', 'dismiss'))
CHECK ((decision = 'revise') = (revised_payload IS NOT NULL))
~~~

当前反馈唯一性使用两个 Partial Unique Index，分别覆盖 recruitment_project_id 非空和为空的情况：

~~~text
(candidate_id, hr_user_id, recruitment_project_id) WHERE is_current = true AND recruitment_project_id IS NOT NULL
(candidate_id, hr_user_id) WHERE is_current = true AND recruitment_project_id IS NULL
~~~

HR 修改反馈时创建新行、旧行 <code>is_current=false</code>，并设置 supersedes_feedback_id。Feedback 可以作为管理员审核证据，但不能改变 Capability、Job Role 或 Neo4j。

## ✅ 知识审核与图谱发布表

### graph_change_candidates

用途：把新技能、新岗位或关系变化表达成可审核操作。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| source_type | varchar(30) | 否 | submission、discovery、manual、job_update |
| source_id | uuid | 否 | 来源资源 |
| depends_on_candidate_id | uuid | 是 | FK graph_change_candidates，创建节点依赖 |
| change_type | varchar(50) | 否 | 创建或修改操作 |
| subject_type | varchar(30) | 否 | capability、job_role |
| subject_id | uuid | 是 | 创建操作可空 |
| object_type | varchar(30) | 是 | capability、domain |
| object_id | uuid | 是 | 关系对象 |
| proposed_properties | jsonb | 否 | 提议内容 |
| evidence_summary | jsonb | 否 | 来源统计和 Evidence ID |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| review_status | varchar(30) | 否 | pending、needs_revision、approved、rejected、published |
| revision_no | integer | 否 | 默认 1 |
| created_by_user_id | uuid | 是 | 系统产生可空 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

change_type 第一版：

~~~text
create_capability
create_capability_alias
create_job_role
create_job_role_alias
add_required_capability
add_bonus_capability
remove_capability_relation
update_relation_properties
add_prerequisite_relation
add_related_relation
~~~

约束：

- confidence 0 到 1
- revision_no 大于等于 1
- create 类型在 Candidate 创建时预分配 subject_id；关系变更必须有 subject_id/object_id
- approved 后 proposed_properties 不可修改
- published 后只读

创建类型 Candidate 建立时即预分配稳定 PostgreSQL UUID，但此时不创建正式 Catalog 行。依赖新节点的关系 Candidate 使用同一个 subject_id，并设置 depends_on_candidate_id。approve 只锁定候选内容和稳定 ID，不激活 Catalog 实体；依赖候选只有在上游 create Candidate 已 approved 后才能批准。Graph Version 按依赖拓扑排序，因此 Neo4j 始终先创建节点、再创建关系。

### review_decisions

用途：追加保存每次审核动作。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| candidate_id | uuid | 否 | FK graph_change_candidates |
| reviewer_user_id | uuid | 否 | FK users，必须 admin |
| decision | varchar(20) | 否 | approve、reject、revise |
| from_status | varchar(30) | 否 | 动作前状态 |
| to_status | varchar(30) | 否 | 动作后状态 |
| before_payload | jsonb | 否 | 决定前快照 |
| after_payload | jsonb | 否 | 决定后快照 |
| comment | text | 是 | 意见 |
| created_at | timestamptz | 否 | 默认 now() |

Review Decision 不更新、不删除。动作接口在一个事务中：锁 Candidate、验证状态、追加 Decision、更新 Candidate 状态和 Revision。

### graph_versions

用途：一次正式 Neo4j 发布版本。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| version_no | integer | 否 | UNIQUE，单调递增 |
| status | varchar(20) | 否 | draft、publishing、published、failed、abandoned |
| base_version_id | uuid | 是 | FK graph_versions，首版可空 |
| catalog_version_id | uuid | 否 | FK catalog_versions |
| change_summary | text | 否 | 发布摘要 |
| created_by_user_id | uuid | 否 | FK users |
| approved_by_user_id | uuid | 否 | FK users |
| published_at | timestamptz | 是 | 发布成功时间 |
| created_at | timestamptz | 否 | 默认 now() |

约束：

- version_no Unique 且大于等于 1
- published 时 published_at 非空
- 同一时刻只能有一个 publishing 版本，通过 Partial Unique Index on constant expression 实现

### graph_version_items

用途：固定版本包含的已审核变更。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| graph_version_id | uuid | 否 | FK graph_versions |
| candidate_id | uuid | 否 | FK graph_change_candidates |
| sequence_no | integer | 否 | 稳定应用顺序 |
| candidate_snapshot | jsonb | 否 | 发布时不可变快照 |

约束：

~~~sql
PRIMARY KEY (graph_version_id, candidate_id)
UNIQUE (graph_version_id, sequence_no)
UNIQUE (candidate_id)
~~~

一个 Candidate 最多进入一个正式 Graph Version。

### graph_publications

用途：记录发布尝试和幂等状态。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| graph_version_id | uuid | 否 | FK graph_versions |
| processing_run_id | uuid | 否 | FK processing_runs |
| idempotency_key | varchar(150) | 否 | UNIQUE |
| claim_token | uuid | 是 | Worker 尝试围栏令牌 |
| status | varchar(30) | 否 | pending、processing、retry_wait、succeeded、failed |
| attempt_count | integer | 否 | Worker 真正开始时增加 |
| expected_nodes | integer | 否 | 预期节点数 |
| expected_relationships | integer | 否 | 预期关系数 |
| verified_nodes | integer | 是 | 读回节点数 |
| verified_relationships | integer | 是 | 读回关系数 |
| last_error | text | 是 | 安全错误 |
| retry_at | timestamptz | 是 | 下次重试 |
| started_at | timestamptz | 是 | 当前尝试开始 |
| completed_at | timestamptz | 是 | 成功或永久失败 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

关键规则：

- <code>begin_attempt</code> 原子增加 attempt_count 并生成新的 claim_token
- 后续成功、重试和失败更新必须匹配 claim_token
- Neo4j 写入使用稳定节点 ID、稳定关系键和 <code>MERGE</code>
- PostgreSQL 仅在 Neo4j 读回验证成功后标记版本 published
- Worker 在 Neo4j 提交后崩溃，重试通过稳定键确认已写事实，不重复创建

### graph_settings

用途：保存当前公开图谱版本指针。

第一版只有一行：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| key | varchar(50) | PK，固定 current_graph_version |
| graph_version_id | uuid | FK graph_versions |
| updated_at | timestamptz | 切换时间 |

版本发布事务最后更新此指针。API 默认查询该版本，也允许显式查询历史版本。

## 👤 简历与画像表

### resumes

用途：表示一份 applicant 简历或 HR 外部候选简历。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| owner_user_id | uuid | 是 | applicant 所有者 |
| candidate_record_id | uuid | 是 | HR 外部候选人 |
| file_id | uuid | 否 | FK stored_files |
| display_name | varchar(200) | 否 | 页面展示名 |
| source_language | varchar(20) | 否 | 默认 zh-CN |
| parse_status | varchar(30) | 否 | uploaded、processing、ready、partial、failed、archived |
| active_profile_id | uuid | 是 | FK resume_profiles，循环 FK 可延后添加 |
| latest_run_id | uuid | 是 | FK processing_runs |
| created_by_user_id | uuid | 否 | 上传用户 |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |
| archived_at | timestamptz | 是 | 归档时间 |

核心约束：

~~~sql
CHECK ((owner_user_id IS NOT NULL) <> (candidate_record_id IS NOT NULL))
CHECK (parse_status IN ('uploaded', 'processing', 'ready', 'partial', 'failed', 'archived'))
~~~

含义：

- applicant 简历只设置 owner_user_id
- HR 外部候选简历只设置 candidate_record_id
- 不允许两者都空或同时非空
- 不自动把外部候选人与 applicant 账号合并

索引：

- <code>(owner_user_id, created_at DESC)</code> WHERE owner_user_id IS NOT NULL
- <code>(candidate_record_id, created_at DESC)</code> WHERE candidate_record_id IS NOT NULL
- <code>(parse_status, updated_at DESC)</code>

### resume_profiles

用途：保存一次完整简历画像版本。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| resume_id | uuid | 否 | FK resumes |
| base_profile_id | uuid | 是 | FK resume_profiles，人工修订来源 |
| version_no | integer | 否 | 单调递增 |
| extraction_version | varchar(80) | 否 | 解析管线版本 |
| profile_source | varchar(20) | 否 | extracted、manual_revision |
| extracted_text | text | 否 | 从文件提取的正文，受权限保护 |
| text_extraction_method | varchar(20) | 否 | pdf_text、docx、ocr |
| highest_education_level | varchar(30) | 是 | 汇总学历 |
| total_experience_months | integer | 是 | 汇总经验 |
| summary | text | 是 | 可选结构化摘要 |
| structured_payload | jsonb | 否 | 合并后的完整画像快照 |
| status | varchar(30) | 否 | draft、candidate、confirmed、superseded、invalid |
| confirmed_by_user_id | uuid | 是 | applicant、HR 或 admin |
| confirmed_at | timestamptz | 是 | 确认时间 |
| created_by_run_id | uuid | 否 | FK processing_runs |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
UNIQUE (resume_id, version_no)
CHECK (version_no >= 1)
CHECK (profile_source IN ('extracted', 'manual_revision'))
CHECK (text_extraction_method IN ('pdf_text', 'docx', 'ocr'))
CHECK (status IN ('draft', 'candidate', 'confirmed', 'superseded', 'invalid'))
CHECK (total_experience_months IS NULL OR total_experience_months >= 0)
CHECK ((status IN ('confirmed', 'superseded')) = (confirmed_at IS NOT NULL))
CHECK (
  (profile_source = 'extracted' AND created_by_run_id IS NOT NULL AND base_profile_id IS NULL)
  OR
  (profile_source = 'manual_revision' AND created_by_user_id IS NOT NULL AND base_profile_id IS NOT NULL)
)
~~~

模型解析版本使用 Partial Unique Index：

~~~text
(resume_id, extraction_version) WHERE profile_source = 'extracted'
~~~

人工修订必须设置 <code>profile_source=manual_revision</code> 和 base_profile_id，因此可以继承相同 extraction_version 而不与模型解析版本冲突。

确认规则：

- 一份 Resume 同时最多一个 confirmed Profile
- 自动解析结果首先是 candidate；用户第一次修正时复制为新的 manual_revision draft 版本
- 新 Profile 确认时，旧 confirmed 改为 superseded
- applicant 可确认自己的 Profile
- HR 可确认所属项目候选人的 Profile
- draft/candidate 可以被确认；confirmed、superseded 和 invalid 不可原地修改
- 确认不修改原始抽取版本，而是对 Candidate Version 进行允许范围内修正后再确认

### resume_educations

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| profile_id | uuid | 否 | FK resume_profiles |
| sequence_no | integer | 否 | 显示顺序 |
| school_name | varchar(300) | 是 | 学校 |
| major | varchar(300) | 是 | 专业 |
| education_level | varchar(30) | 否 | 规范学历 |
| start_date | date | 是 | 开始日期 |
| end_date | date | 是 | 结束日期 |
| is_current | boolean | 否 | 默认 false |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| source | varchar(20) | 否 | algorithm、llm、merged、manual |
| created_at | timestamptz | 否 | 默认 now() |

Unique：<code>(profile_id, sequence_no)</code>。日期允许只识别到月份时用当月第一天并在 structured_payload 保留精度字段。

### resume_experiences

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| profile_id | uuid | 否 | FK resume_profiles |
| sequence_no | integer | 否 | 显示顺序 |
| company_name | varchar(300) | 是 | 公司 |
| job_title | varchar(300) | 是 | 职位 |
| description | text | 是 | 经历描述 |
| start_date | date | 是 | 开始时间 |
| end_date | date | 是 | 结束时间 |
| is_current | boolean | 否 | 默认 false |
| duration_months | integer | 是 | 确定性计算 |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| source | varchar(20) | 否 | algorithm、llm、merged、manual |
| created_at | timestamptz | 否 | 默认 now() |

约束：duration 非负；end_date 不早于 start_date；Unique <code>(profile_id, sequence_no)</code>。

### resume_projects

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| profile_id | uuid | 否 | FK resume_profiles |
| sequence_no | integer | 否 | 显示顺序 |
| name | varchar(300) | 否 | 项目名 |
| role | varchar(200) | 是 | 项目角色 |
| description | text | 否 | 项目描述 |
| start_date | date | 是 | 开始日期 |
| end_date | date | 是 | 结束日期 |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| source | varchar(20) | 否 | algorithm、llm、merged、manual |
| created_at | timestamptz | 否 | 默认 now() |

### resume_skills

用途：简历技能候选与正式技能映射。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| profile_id | uuid | 否 | FK resume_profiles |
| capability_id | uuid | 是 | FK capabilities，未映射可空 |
| raw_name | varchar(200) | 否 | 简历或用户原文 |
| normalized_name | varchar(200) | 否 | 规范化名称 |
| proficiency | varchar(20) | 是 | beginner、intermediate、advanced |
| experience_months | integer | 是 | 技能经验 |
| evidence_strength | varchar(20) | 否 | mention、project、work |
| mapping_method | varchar(30) | 否 | 精确、语义、人工、未映射 |
| mapping_status | varchar(20) | 否 | mapped、ambiguous、unmapped、invalid |
| source | varchar(20) | 否 | algorithm、llm、merged、manual |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| user_confirmed | boolean | 否 | 默认 false |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (proficiency IS NULL OR proficiency IN ('beginner', 'intermediate', 'advanced'))
CHECK (experience_months IS NULL OR experience_months >= 0)
CHECK (evidence_strength IN ('mention', 'project', 'work'))
CHECK (mapping_status IN ('mapped', 'ambiguous', 'unmapped', 'invalid'))
CHECK ((mapping_status = 'mapped') = (capability_id IS NOT NULL))
CHECK (confidence BETWEEN 0 AND 1)
~~~

Unique 建议：<code>(profile_id, normalized_name)</code>。同一技能出现于多个项目或经历时，通过多个 Evidence Span 表达，不重复创建技能行。

人工补充规则：

- 从 Catalog 选择已有技能：创建 mapped + manual + user_confirmed
- 自由输入未知技能：创建 unmapped Resume Skill，同时创建 capability_submission
- applicant 不能自己创建 Capability ID
- 修改已确认画像时创建新 Profile Version，不覆盖旧版本

## 👥 HR 招聘项目与候选人表

### recruitment_projects

用途：HR 的招聘工作空间和所有权根。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| owner_hr_id | uuid | 否 | FK users，必须 hr 或 admin |
| title | varchar(200) | 否 | 项目名称 |
| description | text | 是 | 说明 |
| status | varchar(20) | 否 | draft、active、closed、archived |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |
| closed_at | timestamptz | 是 | 关闭时间 |

第一版不实现多人协作表。一个项目只有一个 owner_hr_id；admin 可全局访问。

索引：<code>(owner_hr_id, status, updated_at DESC)</code>。

### job_descriptions

用途：HR 项目内的目标 JD，可以输入文本或上传文件。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| project_id | uuid | 否 | FK recruitment_projects |
| logical_jd_id | uuid | 否 | 同一逻辑 JD 的稳定 ID |
| file_id | uuid | 是 | FK stored_files，文本输入可空 |
| title | varchar(300) | 否 | HR 输入岗位名 |
| raw_text | text | 是 | 文本输入必填；文件上传在 Worker 提取后写入 |
| normalized_text | text | 是 | 规范化文本 |
| target_job_role_id | uuid | 是 | FK job_roles |
| version_no | integer | 否 | 项目内同一逻辑 JD 版本 |
| parse_status | varchar(30) | 否 | draft、processing、ready、confirmed、superseded、partial、failed、archived |
| education_requirement | jsonb | 是 | required/preferred |
| experience_requirement | jsonb | 是 | required/preferred |
| structured_payload | jsonb | 否 | 默认空对象 |
| extraction_version | varchar(80) | 是 | 解析版本 |
| latest_run_id | uuid | 是 | FK processing_runs |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束与索引：

~~~sql
UNIQUE (logical_jd_id, version_no)
CHECK (version_no >= 1)
CHECK (parse_status IN ('draft', 'processing', 'ready', 'confirmed', 'superseded', 'partial', 'failed', 'archived'))
CHECK (parse_status IN ('processing', 'failed') OR raw_text IS NOT NULL)
~~~

- Unique Partial：<code>(logical_jd_id) WHERE parse_status = 'confirmed'</code>
- <code>(project_id, updated_at DESC)</code>

项目第一版允许多个逻辑 JD；匹配 Run 必须明确一个 confirmed target_job_description_id。修改或重新解析创建新的 Job Description Version，不覆盖旧版本；新版本确认后，旧 confirmed 版本变为 superseded。

### job_requirement_skills

用途：HR JD 已确认的技能要求，是招聘匹配的直接输入。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| job_description_id | uuid | 否 | FK job_descriptions |
| capability_id | uuid | 是 | FK capabilities，未映射可空 |
| raw_name | varchar(200) | 否 | JD 原文 |
| requirement_type | varchar(20) | 否 | required、preferred |
| required_level | varchar(20) | 是 | 技能等级 |
| importance | numeric(5,4) | 否 | 0 到 1 |
| mapping_status | varchar(20) | 否 | mapped、ambiguous、unmapped、invalid |
| confidence | numeric(5,4) | 否 | 0 到 1 |
| hr_confirmed | boolean | 否 | 默认 false |
| created_at | timestamptz | 否 | 默认 now() |

只有 mapped 的要求参与技能计分；unmapped 要求必须在 UI 中明确提示 HR，不能静默忽略。

### candidate_records

用途：HR 项目中的外部候选人，不是登录账号。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| project_id | uuid | 否 | FK recruitment_projects |
| active_resume_id | uuid | 是 | FK resumes，循环 FK 在 Resume Migration 后添加 |
| display_name | varchar(200) | 否 | 候选人显示名 |
| email | varchar(320) | 是 | 可选联系信息 |
| phone | varchar(50) | 是 | 可选联系信息 |
| status | varchar(30) | 否 | imported、processing、ready、partial、failed、archived |
| external_reference | varchar(150) | 是 | HR 自有编号 |
| notes | text | 是 | HR 备注 |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

索引：

- <code>(project_id, status, created_at DESC)</code>
- <code>(project_id, external_reference)</code> WHERE external_reference IS NOT NULL

上传第一份可用简历后设置 active_resume_id；上传新简历默认切换到新 Resume，HR 可以显式切回旧版本。Match Run 只使用 active_resume_id 对应的 active_profile_id。

### candidate_materials

用途：作品集、项目链接、视频链接和附件，仅做中转展示。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| candidate_record_id | uuid | 否 | FK candidate_records |
| material_type | varchar(20) | 否 | file、url |
| file_id | uuid | 是 | FK stored_files |
| url | text | 是 | 外部链接 |
| title | varchar(300) | 否 | 展示标题 |
| description | text | 是 | HR 或候选说明 |
| sort_order | integer | 否 | 默认 0 |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK (material_type IN ('file', 'url'))
CHECK (
  (material_type = 'file' AND file_id IS NOT NULL AND url IS NULL)
  OR
  (material_type = 'url' AND file_id IS NULL AND url IS NOT NULL)
)
~~~

系统不抓取、不解析外部链接内容。页面打开外链时应使用安全的新窗口属性。

### candidate_imports

用途：记录一次 HR 批量候选人导入。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| project_id | uuid | 否 | FK recruitment_projects |
| uploaded_by_user_id | uuid | 否 | FK users |
| processing_run_id | uuid | 否 | FK processing_runs |
| total_files | integer | 否 | 文件数 |
| created_candidates | integer | 否 | 创建候选数 |
| failed_files | integer | 否 | 失败数 |
| status | varchar(20) | 否 | pending、processing、completed、partial、failed |
| created_at | timestamptz | 否 | 默认 now() |

一个简历文件默认创建一个 Candidate Record。若批量上传同时提供 Manifest CSV，可从 Manifest 读取姓名和外部编号；第一版不要求实现 ZIP 内复杂目录推断。

## 📊 匹配与评分表

### match_weight_versions

用途：版本化保存确定性评分参数。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| code | varchar(80) | 否 | UNIQUE，例如 match_weights_v1 |
| status | varchar(20) | 否 | draft、active、retired |
| required_skill_weight | numeric(5,4) | 否 | 默认 0.60 |
| preferred_skill_weight | numeric(5,4) | 否 | 默认 0.10 |
| project_evidence_weight | numeric(5,4) | 否 | 默认 0.15 |
| experience_weight | numeric(5,4) | 否 | 默认 0.10 |
| education_weight | numeric(5,4) | 否 | 默认 0.05 |
| level_factors | jsonb | 否 | 满足、接近、不足系数 |
| partial_match_factor | numeric(5,4) | 否 | 默认 0.50 |
| configuration | jsonb | 否 | 其他稳定参数 |
| created_by_user_id | uuid | 否 | FK users |
| activated_at | timestamptz | 是 | 激活时间 |
| created_at | timestamptz | 否 | 默认 now() |

约束：五个维度权重之和必须等于 1，所有系数范围 0 到 1。第一版同时只有一个 active 版本。

### match_runs

用途：一次 applicant 推荐或 HR 批量匹配任务。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| processing_run_id | uuid | 否 | FK processing_runs，UNIQUE |
| run_type | varchar(30) | 否 | applicant_recommendation、recruitment_project |
| applicant_user_id | uuid | 是 | applicant 模式 |
| recruitment_project_id | uuid | 是 | HR 模式 |
| target_job_description_id | uuid | 是 | HR 模式目标 JD |
| resume_profile_id | uuid | 是 | applicant 单份画像 |
| graph_version_id | uuid | 否 | 固定图谱版本 |
| weight_version_id | uuid | 否 | 固定评分版本 |
| candidate_limit | integer | 是 | applicant 召回数 |
| status | varchar(20) | 否 | pending、running、completed、partial、failed |
| created_by_user_id | uuid | 否 | FK users |
| created_at | timestamptz | 否 | 默认 now() |

模式约束：

~~~sql
CHECK (
  (run_type = 'applicant_recommendation'
   AND applicant_user_id IS NOT NULL
   AND resume_profile_id IS NOT NULL
   AND recruitment_project_id IS NULL
   AND target_job_description_id IS NULL)
  OR
  (run_type = 'recruitment_project'
   AND applicant_user_id IS NULL
   AND resume_profile_id IS NULL
   AND recruitment_project_id IS NOT NULL
   AND target_job_description_id IS NOT NULL)
)
~~~

### match_results

用途：不可变的单个简历与单个目标之间的匹配结果。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| match_run_id | uuid | 否 | FK match_runs |
| resume_profile_id | uuid | 否 | FK resume_profiles |
| target_type | varchar(20) | 否 | job_role、job_description |
| target_job_role_id | uuid | 是 | applicant 推荐目标 |
| target_job_description_id | uuid | 是 | HR 目标 JD |
| graph_version_id | uuid | 否 | FK graph_versions |
| weight_version_id | uuid | 否 | FK match_weight_versions |
| skill_score | numeric(5,2) | 否 | 0 到 100 |
| overall_score | numeric(5,2) | 否 | 0 到 100 |
| hard_requirement_status | varchar(20) | 否 | met、not_met、unknown |
| matched_skill_count | integer | 否 | 非负 |
| missing_skill_count | integer | 否 | 非负 |
| summary | jsonb | 否 | 结果快照 |
| rank_no | integer | 是 | HR 或 applicant 列表内排名 |
| created_at | timestamptz | 否 | 默认 now() |

目标约束：

~~~sql
CHECK (
  (target_type = 'job_role' AND target_job_role_id IS NOT NULL AND target_job_description_id IS NULL)
  OR
  (target_type = 'job_description' AND target_job_role_id IS NULL AND target_job_description_id IS NOT NULL)
)
CHECK (skill_score BETWEEN 0 AND 100)
CHECK (overall_score BETWEEN 0 AND 100)
CHECK (hard_requirement_status IN ('met', 'not_met', 'unknown'))
~~~

Unique：

~~~text
(match_run_id, resume_profile_id, target_type, target_job_role_id)
(match_run_id, resume_profile_id, target_type, target_job_description_id)
~~~

使用两个 Partial Unique Index 实现。

### match_dimension_details

用途：保存五个维度的原始分、权重和贡献。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| match_result_id | uuid | 否 | FK match_results |
| dimension | varchar(30) | 否 | required_skills、preferred_skills、project_evidence、experience、education |
| raw_score | numeric(5,2) | 否 | 0 到 100 |
| weight | numeric(5,4) | 否 | 0 到 1 |
| weighted_contribution | numeric(7,4) | 否 | raw_score × weight |
| explanation | jsonb | 否 | 计算明细 |

主键：<code>(match_result_id, dimension)</code>。

### match_skill_details

用途：逐技能解释匹配、部分匹配和缺失。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| match_result_id | uuid | 否 | FK match_results |
| capability_id | uuid | 否 | FK capabilities |
| requirement_type | varchar(20) | 否 | required、preferred |
| match_status | varchar(20) | 否 | matched、partial、missing |
| requirement_weight | numeric(5,4) | 否 | 重要度 |
| coverage_factor | numeric(5,4) | 否 | 1、0.5、0 |
| level_factor | numeric(5,4) | 否 | 等级因子 |
| contribution | numeric(7,4) | 否 | 对技能分贡献 |
| resume_skill_id | uuid | 是 | FK resume_skills |
| related_capability_id | uuid | 是 | partial 时实际具备技能 |
| graph_relation_type | varchar(30) | 是 | RELATED_TO 等 |
| resume_evidence_ids | uuid[] | 否 | Evidence IDs |
| job_evidence_ids | uuid[] | 否 | Evidence IDs |

约束：

- matched 必须有 resume_skill_id
- missing 不得有 resume_skill_id
- partial 必须有 resume_skill_id、related_capability_id 和审核通过的图谱关系
- Embedding 相似不能直接产生 partial 分数

### match_condition_details

用途：解释学历和经验等硬条件或优先条件。

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| match_result_id | uuid | 否 | FK match_results |
| condition_type | varchar(30) | 否 | education、experience |
| requirement_mode | varchar(20) | 否 | required、preferred |
| required_value | jsonb | 否 | 岗位要求快照 |
| actual_value | jsonb | 否 | 简历值快照 |
| status | varchar(20) | 否 | met、not_met、unknown |
| raw_score | numeric(5,2) | 是 | preferred 时可计分 |
| explanation | text | 否 | 可读说明 |

不满足 required 条件不删除候选，也不强制把 Overall Score 设为 0；通过 hard_requirement_status 和问题列表独立展示。

### 确定性评分公式

必备技能分：

~~~text
required_skill_score =
100 × SUM(importance × coverage_factor × level_factor)
      / SUM(importance)
~~~

加分技能分使用相同公式。若岗位没有 preferred 技能，该维度从总权重中按比例归一，不因空集合给满分或零分。

项目证据分：

| Evidence Strength | 因子 |
| --- | ---: |
| mention | 0.40 |
| project | 0.80 |
| work | 1.00 |

综合分：

~~~text
overall_score =
required_skill_score × w_required
+ preferred_skill_score × w_preferred
+ project_evidence_score × w_project
+ experience_score × w_experience
+ education_score × w_education
~~~

所有中间量存入 Match Dimension Detail。最终分由 FastAPI Domain Service 计算，Algorithm Service 和 LLM 不允许返回最终百分比作为正式值。

排名规则：

~~~text
overall_score DESC
skill_score DESC
hard_requirement_status: met > unknown > not_met
created_at ASC
~~~

### 高分区分策略

第一版通过以下证据区分技能覆盖相似的候选人：

- 项目或工作经历中是否真实使用技能
- 技能熟练度是否达到要求
- 相关经验月数
- 学历和经验的 required/preferred 状态
- 必备技能与加分技能分开计分

不引入学校排名、公司声誉和主观人格评分。

## 🎓 成长路径表

### growth_plans

用途：保存一份可重复查看的成长计划。

| 字段 | 类型 | 空值 | 约束与说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| owner_user_id | uuid | 是 | applicant 所有者 |
| recruitment_project_id | uuid | 是 | HR 候选场景 |
| resume_profile_id | uuid | 否 | FK resume_profiles |
| match_result_id | uuid | 是 | FK match_results |
| target_job_role_id | uuid | 否 | FK job_roles |
| focus_capability_id | uuid | 是 | FK capabilities，仅针对某个缺失技能时填写 |
| graph_version_id | uuid | 否 | FK graph_versions |
| prompt_version | varchar(80) | 否 | 生成 Prompt |
| status | varchar(30) | 否 | pending、generating、ready、partial、failed、archived |
| summary | text | 是 | 计划摘要 |
| created_by_user_id | uuid | 否 | FK users |
| processing_run_id | uuid | 否 | FK processing_runs |
| created_at | timestamptz | 否 | 默认 now() |
| updated_at | timestamptz | 否 | 默认 now() |

约束：

~~~sql
CHECK ((owner_user_id IS NOT NULL) <> (recruitment_project_id IS NOT NULL))
CHECK (status IN ('pending', 'generating', 'ready', 'partial', 'failed', 'archived'))
~~~

HR 场景必须验证 Resume Profile 对应的 Candidate Record 属于同一 Recruitment Project。

<code>focus_capability_id</code> 为空时为目标岗位完整成长路径；非空时必须是该 Match Result 中 missing 或 partial 的技能，只生成该技能及其必要前置路径。

### growth_steps

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| id | uuid | 否 | PK |
| growth_plan_id | uuid | 否 | FK growth_plans |
| sequence_no | integer | 否 | 从 1 开始 |
| capability_id | uuid | 否 | FK capabilities |
| stage | varchar(30) | 否 | foundation、core、advanced |
| reason | text | 否 | 为什么先学此技能 |
| current_status | varchar(20) | 否 | missing、partial |
| target_level | varchar(20) | 是 | 目标等级 |
| task_description | text | 否 | 阶段练习任务 |
| prerequisite_capability_ids | uuid[] | 否 | 生成时图谱快照 |

约束：

~~~sql
UNIQUE (growth_plan_id, sequence_no)
UNIQUE (growth_plan_id, capability_id)
CHECK (sequence_no >= 1)
CHECK (stage IN ('foundation', 'core', 'advanced'))
CHECK (current_status IN ('missing', 'partial'))
~~~

### growth_step_resources

| 字段 | 类型 | 空值 | 说明 |
| --- | --- | :---: | --- |
| growth_step_id | uuid | 否 | FK growth_steps |
| learning_resource_id | uuid | 否 | FK learning_resources |
| rank_no | integer | 否 | 推荐顺序 |
| retrieval_score | numeric(5,4) | 否 | RAG 召回分 |
| reason | text | 是 | 推荐原因 |

主键：<code>(growth_step_id, learning_resource_id)</code>。Unique：<code>(growth_step_id, rank_no)</code>。

生成规则：

1. 从 Match Result 读取 missing/partial 技能
2. 查询固定 Graph Version 的 PREREQUISITE_OF
3. 去除用户已具备且等级足够的技能
4. 对剩余子图做有向无环排序；发现环时记录警告并使用管理员设定的 tie-break
5. 从 approved Learning Resource 中检索资料
6. LLM 只生成阶段说明和练习任务，不生成新技能 ID 或外部链接
7. 后端校验 Skill ID、顺序和 Resource ID 后保存

## 🔗 Neo4j 查询模型

### 数据边界

Neo4j 只保存已经通过 admin 审核并成功发布的正式知识，不保存：

- 用户、Session 和密码
- 简历和候选人个人信息
- 原始或清洗 JD 全文
- Processing Run 和错误
- HR Business Feedback
- 未审核 Candidate
- LLM 或 Algorithm 原始响应

PostgreSQL 的 Graph Version、Version Item、Review Decision 和 Publication 是发布账本。Neo4j 可以从该账本重建。

### 节点

#### Domain

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| id | string | PostgreSQL UUID |
| code | string | 稳定代码 |
| name | string | 名称 |
| status | string | active/deprecated |
| catalog_version | integer | 目录版本 |

#### Capability

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| id | string | PostgreSQL Capability UUID |
| canonical_name | string | 标准名称 |
| normalized_name | string | 规范化名称 |
| skill_type | string | 技能类型 |
| status | string | active/deprecated |
| catalog_version | integer | 目录版本 |

#### JobRole

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| id | string | PostgreSQL Job Role UUID |
| canonical_name | string | 标准岗位名 |
| normalized_name | string | 规范化名称 |
| description | string | 审核后的岗位定义 |
| status | string | active/deprecated |
| catalog_version | integer | 目录版本 |

### 关系

| 关系 | 起点 | 终点 | 关键业务属性 |
| --- | --- | --- | --- |
| BELONGS_TO | Capability/JobRole | Domain | valid_from_version、valid_to_version |
| REQUIRES | JobRole | Capability | job_level、importance、required_level、confidence、evidence_count、source_count、valid_from_version、valid_to_version |
| BONUS | JobRole | Capability | job_level、importance、confidence、evidence_count、source_count、valid_from_version、valid_to_version |
| PREREQUISITE_OF | Capability | Capability | strength、confidence、valid_from_version、valid_to_version |
| RELATED_TO | Capability | Capability | relation_kind、strength、confidence、valid_from_version、valid_to_version |

每条关系额外保存：

| 属性 | 说明 |
| --- | --- |
| relation_key | 稳定唯一键，用于 MERGE 和重试 |
| source_candidate_id | PostgreSQL Graph Change Candidate ID |
| published_at | 首次发布时间 |

relation_key 构造：

~~~text
sha256(
  relationship_type
  + source_node_id
  + target_node_id
  + job_level_or_relation_kind
)
~~~

### 版本有效条件

查询版本 V 时：

~~~text
valid_from_version <= V
AND
(valid_to_version IS NULL OR V < valid_to_version)
~~~

新增关系：

~~~text
valid_from_version = new_version
valid_to_version = null
~~~

关闭旧关系：

~~~text
valid_to_version = new_version
~~~

不删除旧关系，保证历史版本可查询。

节点的名称、描述和状态属于 Catalog Version 属性，不仅是当前 Neo4j 节点属性。查询历史 Graph Version 时，Graph Query Service 使用该 Graph Version 固定的 catalog_version_id，从 PostgreSQL <code>catalog_version_items</code> 还原当时的节点展示快照；Neo4j 负责版本化拓扑和关系属性。这样后续修改 Capability 或 Job Role 名称不会篡改旧图谱版本的展示结果。

### 约束和索引

启动 Migration 时创建：

~~~cypher
CREATE CONSTRAINT domain_id_unique IF NOT EXISTS
FOR (n:Domain) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT capability_id_unique IF NOT EXISTS
FOR (n:Capability) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT job_role_id_unique IF NOT EXISTS
FOR (n:JobRole) REQUIRE n.id IS UNIQUE;

CREATE INDEX domain_code_index IF NOT EXISTS
FOR (n:Domain) ON (n.code);

CREATE INDEX capability_name_index IF NOT EXISTS
FOR (n:Capability) ON (n.normalized_name);

CREATE INDEX job_role_name_index IF NOT EXISTS
FOR (n:JobRole) ON (n.normalized_name);
~~~

关系唯一性由发布 Service 的 relation_key 和读回校验控制。若部署的 Neo4j 版本支持 Relationship Property Uniqueness Constraint，应为每种正式关系的 relation_key 建唯一约束；否则使用事务内匹配和发布验证。

### 全局图查询

输入：

- graph_version
- domain_id，可选
- job_level，可选
- max_job_roles
- max_capabilities

返回：

~~~json
{
  "graph_version": 3,
  "nodes": [
    {
      "id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
      "type": "job_role",
      "name": "AI 应用开发工程师",
      "domain_id": "41902ab1-aae4-459d-a22f-fbf683a19021"
    }
  ],
  "edges": [
    {
      "id": "relation-key",
      "type": "requires",
      "source": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
      "target": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
      "properties": {
        "job_level": "junior",
        "importance": 0.8
      }
    }
  ],
  "truncated": false
}
~~~

全局图必须限制节点数量，第一版默认最多 50 个岗位、200 个技能。返回 truncated=true 时，前端提示通过领域或职级缩小范围。

### 岗位子图查询

岗位匹配明细使用两跳以内子图：

1. 目标 Job Role
2. REQUIRES 和 BONUS Capability
3. 每个缺失 Capability 的直接 PREREQUISITE_OF
4. 需要解释 Partial Match 时返回 RELATED_TO

不在一个请求中递归返回完整技能图谱。

### 成长路径查询

Growth Path Service 查询目标缺失技能的前置子图，并传入用户已具备技能集合。

限制：

- 最大深度 4
- 最大节点 100
- 只使用目标 Graph Version 有效关系
- 仅使用 active Capability
- 检测循环并返回 cycle_warning

### 发布事务

发布步骤：

~~~mermaid
sequenceDiagram
    accTitle: Versioned Graph Publication
    accDescr: Publication sequence that fences a worker attempt, writes idempotent Neo4j facts, verifies them, and only then switches the PostgreSQL current graph version

    participant worker as ⚙️ Celery worker
    participant postgres as 💾 PostgreSQL
    participant neo4j as 💾 Neo4j

    worker->>postgres: Claim publication and token
    postgres-->>worker: Candidate snapshots
    worker->>neo4j: MERGE nodes and relations
    neo4j-->>worker: Commit transaction
    worker->>neo4j: Read back expected facts
    neo4j-->>worker: Verified counts and properties
    worker->>postgres: Ack with claim token
    postgres->>postgres: Apply catalog version items
    postgres->>postgres: Publish catalog and graph
    postgres->>postgres: Switch current graph pointer
~~~

最终 PostgreSQL Ack 事务执行：

1. 校验 claim_token
2. 应用 Draft Catalog Version Item，创建或修改主数据
3. 将 Draft Catalog Version 标记 published
4. 将 Graph Version 标记 published
5. 将 Graph Change Candidate 标记 published
6. 切换 Current Graph Pointer；Current Catalog Version 取最高 Published Version

Neo4j 写入失败时 Current Graph Pointer 不变，Draft Catalog Version 也不发布。Neo4j 写入成功但 PostgreSQL Ack 前 Worker 崩溃时，新关系由于 valid_from_version 尚未成为 Current Graph Version，Draft Catalog 也未激活，因此不会对默认查询可见。

发布失败时 Graph Version 保持 failed，并记录 Publication 错误。admin 可以对同一 failed Version 再次调用 publish；接口将状态切回 publishing 并创建新的 Publication Attempt，继续使用相同版本号、Candidate Snapshot 和稳定 Neo4j 关系键，不创建新的 Graph Version。

abandoned 只允许 failed -> abandoned，必须记录原因并审计；该版本号不再发布，下一版本以最近 published Version 为 base，但仍使用新的单调 version_no。历史查询不会把 abandoned 版本视为有效图谱。

## 🌐 REST API 总览

### Router 划分

| Router | 前缀 | 主要调用者 |
| --- | --- | --- |
| auth | /api/v1/auth | 三种角色 |
| admin_users | /api/v1/admin/users | admin |
| files | /api/v1/files | 有所有权的用户 |
| processing | /api/v1/processing-runs | 任务 owner、admin |
| imports | /api/v1/imports | admin |
| catalog | /api/v1/catalog | authenticated，写操作 admin |
| submissions | /api/v1/capability-submissions | 提交者、admin |
| discovery | /api/v1/discovery-runs、/discovery-candidates | admin、hr 受限读取 |
| reviews | /api/v1/reviews | admin |
| graph | /api/v1/graph、/graph-versions | authenticated，发布 admin |
| resumes | /api/v1/resumes | applicant、hr、admin，按所有权 |
| applicant_matches | /api/v1/job-recommendations、/matches | applicant、admin |
| recruitment | /api/v1/recruitment-projects | hr、admin |
| candidates | /api/v1/candidate-records | 项目 owner、admin |
| growth | /api/v1/growth-plans | owner、admin |
| system | /health、/api/v1/admin/system | 运维、admin |

### 接口分类与实施原则

| 分类 | 核心闭环 | 实施优先级 |
| --- | --- | --- |
| Auth 与账号 | 登录、当前用户、管理员创建账号 | Batch A |
| 文件与任务 | 受控读取、任务状态、错误、取消和重试 | Batch A |
| 市场 JD 与 Catalog | 导入、处理、技能和岗位主数据 | Batch B |
| Discovery、Review 与 Graph | 候选发现、审核、发布和图查询 | Batch C |
| Applicant | 简历、画像、推荐、差距和成长路径 | Batch D |
| Recruitment | 项目、JD、候选、材料、匹配和排名 | Batch E |
| System | 健康、依赖和版本诊断 | Batch A |

不使用路由数量衡量完成度。接口按下文完整列出，但实施时只交付当前 Batch 的闭环；多数查询和状态动作复用统一 Service、Schema 和权限依赖。

### 权限依赖

FastAPI 使用以下依赖表达权限，不在 Router 中重复编写：

~~~text
get_current_user()
require_role(*roles)
require_admin()
load_owned_resume(resume_id)
load_owned_project(project_id)
load_owned_candidate(candidate_id)
load_visible_processing_run(run_id)
load_visible_file(file_id)
load_visible_growth_plan(plan_id)
~~~

加载函数使用“权限范围内查询”。普通用户访问无权资源统一返回 404，减少资源枚举风险；明确角色禁止的全局动作返回 403。

### 写接口并发控制

更新接口支持 <code>If-Match</code>，值为资源 <code>updated_at</code> 或轻量整数 Revision。第一版对以下多人或异步冲突高的资源强制要求：

- Graph Change Candidate 审核
- Graph Version 发布
- Capability 和 Job Role 修改
- Resume Profile 确认
- Recruitment Project 和 JD 修改

版本不匹配返回：

~~~json
{
  "error": {
    "code": "STALE_RESOURCE_VERSION",
    "message": "资源已被其他操作更新，请刷新后重试",
    "request_id": "req_01J4VY57ABCD1234",
    "details": {
      "current_version": 4
    }
  }
}
~~~

### 批量接口约定

批量接口不保证全有或全无：

- 上传层验证失败：整个请求拒绝
- 单项业务处理失败：任务继续，记录 Processing Error
- 响应通过 Run Summary 返回成功和失败数
- 支持下载错误 CSV
- 不把数百项错误直接放在任务轮询响应中

### API 文档分组

OpenAPI Tags：

~~~text
Auth
Admin Users
Files
Processing
Imports
Catalog Domains
Catalog Capabilities
Catalog Job Roles
Learning Resources
Capability Submissions
Discovery
Reviews
Graph
Resumes
Applicant Matching
Recruitment Projects
Candidates
Recruitment Matching
Growth Plans
System
~~~

## 🔑 Auth、账号、文件与任务 API

### Auth 接口清单

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/auth/login | anonymous | 200 | 用户名密码登录 |
| POST | /api/v1/auth/logout | authenticated | 204 | 撤销当前 Session |
| POST | /api/v1/auth/logout-all | authenticated | 204 | 撤销本人全部 Session |
| GET | /api/v1/auth/me | authenticated | 200 | 当前用户和 CSRF 信息 |

#### POST /auth/login

请求：

~~~json
{
  "username": "hr_demo",
  "password": "user-entered-password"
}
~~~

成功响应：

~~~json
{
  "data": {
    "id": "7f5a8da8-8b23-4d14-8253-7450c347cc54",
    "username": "hr_demo",
    "display_name": "演示 HR",
    "role": "hr",
    "csrf_token": "one-time-readable-csrf-token"
  }
}
~~~

Header：

~~~text
Set-Cookie: session=<opaque>; HttpOnly; SameSite=Lax; Path=/
X-Request-ID: req_...
~~~

错误：

| 错误码 | HTTP | 条件 |
| --- | ---: | --- |
| INVALID_CREDENTIALS | 401 | 用户名或密码错误，响应不区分 |
| ACCOUNT_INACTIVE | 403 | 账号停用 |
| LOGIN_RATE_LIMITED | 429 | 失败次数超过限制 |

登录成功后更新 last_login_at 并写 Audit Log；失败写 Login Attempt，不写明文密码。

### Admin User 接口清单

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/admin/users | 201 | 创建内部账号 |
| GET | /api/v1/admin/users | 200 | 用户列表 |
| GET | /api/v1/admin/users/{user_id} | 200 | 用户详情 |
| PATCH | /api/v1/admin/users/{user_id} | 200 | 修改显示名、角色或状态 |
| POST | /api/v1/admin/users/{user_id}/reset-password | 200 | 重置密码并撤销 Session |

创建请求：

~~~json
{
  "username": "applicant_demo",
  "display_name": "演示应聘者",
  "role": "applicant",
  "initial_password": "temporary-password"
}
~~~

创建响应不返回密码：

~~~json
{
  "data": {
    "id": "113298ee-2cac-4c31-9528-cb254257f9a3",
    "username": "applicant_demo",
    "display_name": "演示应聘者",
    "role": "applicant",
    "is_active": true,
    "created_at": "2026-08-05T09:00:00Z"
  }
}
~~~

列表筛选：<code>role</code>、<code>is_active</code>、<code>q</code>。排序白名单：created_at、username、last_login_at。

### Files 接口清单

文件通常通过 Resume、Import、Recruitment 或 Candidate Material 业务接口上传。Files Router 只负责受控读取，不提供脱离业务上下文的普通上传和归档接口；文件归档必须由所属业务资源动作触发。

| 方法 | 路径 | 成功 | 权限 | 用途 |
| --- | --- | ---: | --- | --- |
| GET | /api/v1/files/{file_id} | 200 | visible owner/admin | 元数据 |
| GET | /api/v1/files/{file_id}/content | 200/206 | visible owner/admin | 预览或 Range 读取 |
| GET | /api/v1/files/{file_id}/download | 200 | visible owner/admin | 附件下载 |

元数据响应：

~~~json
{
  "data": {
    "id": "ffba9df5-75a4-4839-ac44-b3c4336bccb8",
    "original_name": "候选人简历.pdf",
    "media_type": "application/pdf",
    "size_bytes": 248001,
    "category": "resume",
    "status": "attached",
    "preview_supported": true,
    "created_at": "2026-08-05T09:10:00Z"
  }
}
~~~

文件读取前按业务绑定对象检查所有权，不能只检查 <code>uploaded_by_user_id</code>。例如 HR 项目 Candidate Resume 归项目 owner 访问。

### Processing Run 接口清单

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| GET | /api/v1/processing-runs | 200 | 查询权限内任务 |
| GET | /api/v1/processing-runs/{run_id} | 200 | 查询状态和进度 |
| GET | /api/v1/processing-runs/{run_id}/errors | 200 | 分页查询逐项错误 |
| GET | /api/v1/processing-runs/{run_id}/result | 200 | 查询任务结果入口 |
| POST | /api/v1/processing-runs/{run_id}/retry | 202 | 创建授权重试 |
| POST | /api/v1/processing-runs/{run_id}/cancel | 202/200 | 请求合作式取消 |

列表筛选：

- run_type
- status
- created_from、created_to
- subject_type
- project_id，仅 HR/admin

任务响应：

~~~json
{
  "data": {
    "id": "a05aec27-1ea1-48d7-a57b-66c6419c4a34",
    "run_type": "process_jd_batch",
    "subject": {
      "type": "import_batch",
      "id": "40c01892-fbce-4e41-a8b7-761a9f33fbd9"
    },
    "status": "running",
    "current_stage": "extracting",
    "progress": {
      "total": 307,
      "processed": 120,
      "succeeded": 116,
      "failed": 4,
      "percent": 39.09
    },
    "cancel_requested": false,
    "attempt_count": 1,
    "started_at": "2026-08-05T08:10:00Z",
    "heartbeat_at": "2026-08-05T08:12:15Z",
    "completed_at": null,
    "links": {
      "errors": "/api/v1/processing-runs/a05aec27-1ea1-48d7-a57b-66c6419c4a34/errors",
      "result": null
    }
  }
}
~~~

重试规则：

- 只有 failed、enqueue_failed 和部分 dependency failure 可重试
- retry 创建新的 Processing Run，并设置 <code>retry_of_run_id</code>
- 旧 Run 不改回 pending
- 输入错误和权限错误不能重试

取消规则：

- pending：直接标记 cancelled
- running：标记 cancel_requested，返回 202
- completed/failed/cancelled：返回当前资源，操作幂等
- publishing Neo4j 事务中：记录请求，但必须等待当前事务完成或回滚

## 📥 市场 JD 导入与 Catalog API

### Import 接口清单

全部接口仅 admin 可用。

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/imports | 202 | 上传文件、创建批次并异步解析原始行 |
| GET | /api/v1/imports | 200 | 批次列表 |
| GET | /api/v1/imports/{batch_id} | 200 | 批次详情和质量汇总 |
| GET | /api/v1/imports/{batch_id}/rows | 200 | 查看原始与当前标准化行 |
| GET | /api/v1/imports/{batch_id}/warnings | 200 | 警告分类和行列表 |
| POST | /api/v1/imports/{batch_id}/process | 202 | 启动标准管线 |
| POST | /api/v1/imports/{batch_id}/reprocess | 202 | 使用新版本重新处理 |
| POST | /api/v1/imports/{batch_id}/archive | 200 | 归档批次 |

#### POST /imports

请求：<code>multipart/form-data</code>

| 字段 | 必填 | 说明 |
| --- | :---: | --- |
| file | 是 | csv、xlsx、json 或 txt |
| source_code | 是 | standard、liepin、zhilian、zhilian_direct |
| source_format | 否 | 默认 auto |
| collected_at | 是 | 相对日期解析锚点 |
| schema_version | 否 | 标准模板版本 |

上传阶段同步完成：

1. 文件安全验证
2. 保存 Stored File
3. 创建 Import Batch，状态 processing
4. 创建 import_market_jd Processing Run
5. 投递后台任务

后台任务负责检测表头和 Adapter、流式解析、写入 Raw JD、统计行数和警告。这样 CSV、Excel、JSON 使用一致语义，API 不会因为文件大小产生 201/202 两种不确定行为。

202 响应：

~~~json
{
  "data": {
    "resource_id": "40c01892-fbce-4e41-a8b7-761a9f33fbd9",
    "run_id": "be4b4f56-49c9-4f62-a2b3-da8f593f8c75",
    "status": "processing",
    "poll_url": "/api/v1/processing-runs/be4b4f56-49c9-4f62-a2b3-da8f593f8c75"
  }
}
~~~

任务完成后，<code>GET /imports/{batch_id}</code> 返回 detected_adapter、adapter_version、counts 和 warning_summary。

错误：

| 错误码 | HTTP | 条件 |
| --- | ---: | --- |
| IMPORT_SCHEMA_NOT_RECOGNIZED | 422 | 无法识别字段 |
| SOURCE_ADAPTER_MISMATCH | 422 | 指定来源和检测格式冲突 |
| FILE_ENCODING_UNSUPPORTED | 422 | 无法安全解码 |
| IMPORT_EMPTY | 422 | 没有有效数据行 |
| IMPORT_ROW_LIMIT_EXCEEDED | 413 | 超过配置行数 |

#### GET /imports/{id}/rows

筛选：

- row_status：accepted、rejected、warning
- quality_flag
- mapping_status
- duplicate_only
- q：岗位名或公司名

返回 Raw 与当前 Normalized 的并列摘要，不默认返回完整 raw_payload 和全文；详情通过 <code>include=raw_payload,full_text</code> 且仅 admin 请求。

#### POST /imports/{id}/process

请求：

~~~json
{
  "pipeline_version": "jd_pipeline_v1",
  "enable_llm_fallback": true,
  "enable_discovery": false
}
~~~

行为：

- 创建 process_jd_batch Run
- 执行 normalize、deduplicate、extract、map、embed
- enable_discovery=false 时不自动创建 Discovery Run
- 同一 batch_id + pipeline_version 已成功时返回已有结果
- 若已有 Running Run，返回 409 PROCESSING_ALREADY_RUNNING

### Domain API

### Catalog Import API

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/catalog/imports | admin | 202 | 上传标准技能或岗位模板 |
| GET | /api/v1/catalog/imports | admin | 200 | 导入历史 |
| GET | /api/v1/catalog/imports/{id} | admin | 200 | 验证、应用结果和错误 |

请求：multipart，字段包括 file、import_type、schema_version、mode。

- validate_only：只检查格式、Domain、重复名称、别名歧义和外部 ID，不修改 Catalog
- apply：验证后创建 Catalog Version 并写入有效行
- 3 万级数据采用流式读取和 Chunk 事务
- 不允许自动覆盖已有 Active 主数据；冲突行进入 Processing Error

### Catalog Version API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/catalog/versions | authenticated | 查询 Published 目录版本 |
| GET | /api/v1/catalog/versions/current | authenticated | 当前最高 Published 版本 |
| GET | /api/v1/catalog/versions/{id} | authenticated | 版本摘要和变更项 |

普通用户只能看到 published Version；admin 可通过 <code>include_drafts=true</code> 查看 Draft。Graph Version 详情必须同时返回绑定的 Catalog Version。

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/catalog/domains | authenticated | 领域树 |
| POST | /api/v1/catalog/domains | admin | 创建领域 |
| PATCH | /api/v1/catalog/domains/{id} | admin | 修改或 deprecated |

GET 返回树结构和每个 Domain 的 active Capability/Job Role 计数。第一版不提供拖拽排序专用接口，PATCH sort_order 即可。

### Capability API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/catalog/capabilities | authenticated | 搜索技能 |
| POST | /api/v1/catalog/capabilities | admin | 创建 Candidate 或 Active 技能 |
| GET | /api/v1/catalog/capabilities/{id} | authenticated | 详情、别名和来源 |
| PATCH | /api/v1/catalog/capabilities/{id} | admin | 修改主数据 |
| POST | /api/v1/catalog/capabilities/{id}/deprecate | admin | 弃用并指定替代项 |
| POST | /api/v1/catalog/capabilities/{id}/aliases | admin | 添加别名 |
| PATCH | /api/v1/catalog/capability-aliases/{alias_id} | admin | 修改别名状态 |
| GET | /api/v1/catalog/capabilities/{id}/usage | admin | 查询 JD、简历和图谱引用统计 |

列表筛选：

- q：canonical_name 和 active Alias
- domain_id
- status
- skill_type
- source_type
- has_ambiguous_alias

列表默认只返回 active；admin 可显式查询其他状态。

创建请求：

~~~json
{
  "domain_id": "41902ab1-aae4-459d-a22f-fbf683a19021",
  "canonical_name": "RAG 评测",
  "description": "对检索增强生成系统的检索和生成质量进行评估",
  "skill_type": "method",
  "status": "candidate",
  "source_type": "manual",
  "aliases": ["RAG Evaluation"]
}
~~~

创建 Active 技能必须由 admin 明确提交 <code>status=active</code> 并生成 Catalog Version；从模型或用户 Submission 转入时应使用 Review 解决接口，避免绕过来源记录。

修改 canonical_name：

- 要求 If-Match
- 自动把旧 canonical_name 创建为 active Alias
- 检查新名称在 Domain 内唯一
- 创建新的 Catalog Version

弃用请求：

~~~json
{
  "replacement_capability_id": "e2092b26-6f42-4615-8fdd-95da062ba38e",
  "reason": "已合并到新的标准技能"
}
~~~

### Job Role API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/catalog/job-roles | authenticated | 岗位检索 |
| POST | /api/v1/catalog/job-roles | admin | 创建岗位 |
| GET | /api/v1/catalog/job-roles/{id} | authenticated | 岗位定义和当前能力 |
| PATCH | /api/v1/catalog/job-roles/{id} | admin | 修改岗位主数据 |
| POST | /api/v1/catalog/job-roles/{id}/deprecate | admin | 弃用岗位 |
| POST | /api/v1/catalog/job-roles/{id}/aliases | admin | 添加岗位别名 |
| GET | /api/v1/catalog/job-roles/{id}/requirements | authenticated | 按图谱版本查询能力要求 |

Job Role 主表不直接保存正式 Required/Bonus 关联；正式关系从 Neo4j 按 Graph Version 查询，发布前候选关系从 Graph Change Candidate 查询。

<code>POST /catalog/job-roles</code> 只创建 candidate Job Role 和 create_job_role Graph Change Candidate。Job Role 需要能力关系才能形成可用画像，因此不允许该接口直接创建 active Job Role；只有 Graph Version 发布事务可以激活。Capability 可以由 admin 在有可靠标准来源时直接创建 Active，但仍必须生成 Published Catalog Version 和 Version Item。

### Learning Resource API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/catalog/learning-resources | authenticated | 查询 approved 资料 |
| POST | /api/v1/catalog/learning-resources | admin | 创建待审核或 approved 资料 |
| GET | /api/v1/catalog/learning-resources/{id} | authenticated | 资料详情 |
| PATCH | /api/v1/catalog/learning-resources/{id} | admin | 修改和审核状态 |
| POST | /api/v1/catalog/learning-resources/{id}/check | admin | 触发链接可用性检查 |

普通用户只能看到 approved 且 is_available=true。admin 可按 review_status 查询全部。

### Capability Submission API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| POST | /api/v1/capability-submissions | applicant、hr、admin | 提交未知技能 |
| GET | /api/v1/capability-submissions | submitter、admin | 查询权限内提交 |
| GET | /api/v1/capability-submissions/{id} | submitter、admin | 详情和处理结果 |
| POST | /api/v1/capability-submissions/{id}/resolve | admin | 映射、创建或拒绝 |

提交请求：

~~~json
{
  "source_type": "resume",
  "source_id": "977bc2af-e30d-4c93-b723-49fc08eb60de",
  "raw_name": "Agentic RAG 评测",
  "suggested_domain_id": "41902ab1-aae4-459d-a22f-fbf683a19021"
}
~~~

Resolve 三种动作：

~~~json
{
  "resolution": "map_existing",
  "capability_id": "ed868b6f-08b3-4405-96a6-fb58ef169bad",
  "create_alias": true,
  "comment": "作为 RAG 评测的具体表述处理"
}
~~~

~~~json
{
  "resolution": "create_candidate",
  "canonical_name": "Agentic RAG 评测",
  "domain_id": "41902ab1-aae4-459d-a22f-fbf683a19021",
  "skill_type": "method",
  "comment": "进入知识审核"
}
~~~

~~~json
{
  "resolution": "reject",
  "comment": "属于项目名称，不是技能"
}
~~~

create_candidate 创建 Candidate Capability 和对应 Graph Change Candidate，不直接创建 Active Capability。

## 🔍 Discovery、Review 与 Graph API

### Discovery Run 接口

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/discovery-runs | admin | 202 | 启动候选组合发现 |
| GET | /api/v1/discovery-runs | admin | 200 | 运行历史 |
| GET | /api/v1/discovery-runs/{id} | admin、hr | 200 | 运行参数和汇总 |
| GET | /api/v1/discovery-runs/{id}/candidates | admin、hr | 200 | 候选列表 |

启动请求：

~~~json
{
  "input_batch_ids": [
    "40c01892-fbce-4e41-a8b7-761a9f33fbd9"
  ],
  "algorithm_version": "skill-combination-v1",
  "embedding_version": "embedding-v1",
  "parameters": {
    "minimum_support_jobs": 5,
    "minimum_source_count": 2,
    "minimum_quality_score": 60,
    "similarity_threshold": 0.78,
    "maximum_candidates": 50
  }
}
~~~

后端验证：

- 批次全部存在并完成处理
- 输入中有可用的 mapped active Capability
- minimum_source_count 不大于实际来源数
- threshold 在允许范围
- 不允许普通前端暴露任意算法参数；API Schema 只接受上述稳定白名单

返回 202 和 Run ID。

### Discovery Candidate 接口

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/discovery-candidates | admin、hr | 跨运行候选列表 |
| GET | /api/v1/discovery-candidates/{id} | admin、hr | 定义、技能和分数 |
| GET | /api/v1/discovery-candidates/{id}/evidence | admin、hr | 支持 JD 与来源 |
| POST | /api/v1/discovery-candidates/{id}/feedback | hr | 业务采纳、修订或不采纳 |
| POST | /api/v1/discovery-candidates/{id}/propose-review | admin | 转成知识变更候选 |

列表筛选：

- discovery_run_id
- domain_id
- status
- min_support_score
- min_novelty_score
- skill_id
- q

默认排序：<code>overall_candidate_score desc</code>、<code>support_job_count desc</code>。

详情响应：

~~~json
{
  "data": {
    "id": "78b8296a-2839-4f67-bb45-235123120fdc",
    "label": "新岗位发现候选",
    "suggested_name": "大模型评测工程师",
    "definition": {
      "core_responsibilities": [
        "构建大模型和 RAG 系统评测方案"
      ],
      "typical_scenarios": [
        "企业知识库问答质量验证"
      ]
    },
    "skills": [
      {
        "capability_id": "ed868b6f-08b3-4405-96a6-fb58ef169bad",
        "name": "RAG 评测",
        "skill_role": "core",
        "weight": 0.91
      }
    ],
    "support": {
      "jobs": 18,
      "sources": 2,
      "companies": 15
    },
    "scores": {
      "support": 0.82,
      "diversity": 0.76,
      "coherence": 0.88,
      "novelty": 0.71,
      "evidence": 0.84,
      "overall": 0.80
    },
    "status": "candidate",
    "disclaimer": "该结果是候选技能组合，不代表已经确认的长期市场趋势"
  }
}
~~~

Evidence 响应必须包含来源、公司、发布日期/采集时间、质量分和去重簇信息。HR 默认看到必要证据摘要，不读取完整 Raw Payload；admin 可展开完整数据。

### HR Feedback

请求：

~~~json
{
  "decision": "revise",
  "revised_definition": {
    "suggested_name": "RAG 评测工程师",
    "core_responsibilities": [
      "设计并执行 RAG 系统端到端评测"
    ]
  },
  "comment": "名称应突出 RAG 场景"
}
~~~

行为：

- 验证调用者 role=hr
- recruitment_project_id 可选；传入时验证项目归调用者
- 同一上下文重复反馈创建新版本行，旧反馈 is_current=false，并通过 supersedes_feedback_id 形成历史链
- 不改变 Candidate 全局状态为 approved
- admin 在知识审核时看到反馈统计和修订建议

### Propose Review

admin 将 Discovery Candidate 转为一组 Graph Change Candidate：

1. 若岗位不存在：create_job_role
2. 对每个核心技能：add_required_capability
3. 对每个加分技能：add_bonus_capability
4. 若发现未知技能：先创建 capability_submission 或 create_capability Candidate

转换是幂等的，同一 Discovery Candidate 同一 Revision 不重复生成变更。

### Review 接口清单

全部仅 admin。

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| GET | /api/v1/reviews | 200 | 审核队列 |
| GET | /api/v1/reviews/{candidate_id} | 200 | 候选、证据、反馈和影响 |
| POST | /api/v1/reviews/{candidate_id}/approve | 200 | 批准 |
| POST | /api/v1/reviews/{candidate_id}/reject | 200 | 拒绝 |
| POST | /api/v1/reviews/{candidate_id}/revise | 200 | 修订并保留审核记录 |
| POST | /api/v1/reviews/bulk-approve | 200 | 同类型有限批量批准 |

列表筛选：

- review_status
- change_type
- source_type
- domain_id
- min_confidence
- created_from、created_to

默认排序：pending 优先、confidence desc、created_at asc。

详情必须返回：

- proposed_properties
- Evidence 摘要与可展开来源
- Algorithm、LLM 和合并版本
- HR Feedback 统计
- 对现有 Catalog 和图谱的影响
- 潜在名称或别名冲突
- 当前 Revision 和审核历史

Approve 请求：

~~~json
{
  "comment": "证据覆盖两个来源，技能组合稳定",
  "expected_revision": 2
}
~~~

Revise 请求：

~~~json
{
  "proposed_properties": {
    "canonical_name": "RAG 评测工程师",
    "description": "负责 RAG 系统检索与生成质量评测"
  },
  "comment": "根据 HR 反馈调整岗位名称",
  "expected_revision": 1
}
~~~

规则：

- approve：pending/needs_revision -> approved
- depends_on_candidate_id 非空时，依赖 Candidate 必须已 approved
- reject：pending/needs_revision -> rejected
- revise：pending/needs_revision -> needs_revision，并 revision_no + 1
- approved/rejected/published 不能重复动作
- If-Match 或 expected_revision 不一致返回 409 STALE_RESOURCE_VERSION
- bulk-approve 最多 50 项，要求同一 change_type，任何一项冲突则整批拒绝，避免部分知识审核难以确认

### Graph Version Admin API

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/graph-versions | admin | 201 | 从 Approved Candidate 创建 Draft |
| GET | /api/v1/graph-versions | authenticated | 200 | 版本列表 |
| GET | /api/v1/graph-versions/{id} | authenticated | 200 | 版本详情 |
| GET | /api/v1/graph-versions/{id}/items | authenticated | 200 | 版本变更项 |
| POST | /api/v1/graph-versions/{id}/publish | admin | 202 | 启动或重试发布 |
| POST | /api/v1/graph-versions/{id}/abandon | admin | 200 | 放弃永久失败版本 |
| GET | /api/v1/graph-versions/{id}/publication | admin | 200 | 发布尝试和验证 |

创建请求：

~~~json
{
  "candidate_ids": [
    "4a5e20a7-cd1b-4a1b-b2d5-cfc3db9bc6df",
    "1373a5e2-b9fa-4ac3-8639-353321e5c742"
  ],
  "change_summary": "新增 RAG 评测工程师及其核心技能"
}
~~~

创建时：

- 锁定 Candidate，必须全部 approved
- create 类型 Candidate 和其依赖关系必须使用预分配的稳定 subject_id
- 固定 Candidate Snapshot
- 分配下一个 version_no
- 基于当前 Catalog Version 创建 Draft Catalog Version，并生成待应用的 Catalog Version Item
- Graph Version 固定该 Draft Catalog Version
- Draft 创建后 Candidate 不能再进入其他版本
- 同时只允许一个用于 Graph Publication 的 Draft Catalog Version；若 Current Published Catalog Version 在发布前变化，返回 GRAPH_BASE_VERSION_CHANGED 并要求重建 Draft
- 不允许存在未解决的 failed Graph Version；它必须先成功重试或由 admin 明确标记 abandoned。创建下一版本时 base_version_id 指向最近 published Version，version_no 使用历史最大值加一，不复用 abandoned 版本号

发布请求：

~~~json
{
  "expected_version_no": 4
}
~~~

返回 202。错误：

| 错误码 | HTTP | 条件 |
| --- | ---: | --- |
| GRAPH_VERSION_NOT_DRAFT | 409 | 不是 Draft 或 Failed |
| GRAPH_PUBLICATION_RUNNING | 409 | 已有版本发布中 |
| GRAPH_BASE_VERSION_CHANGED | 409 | Current Version 已变化 |
| GRAPH_CANDIDATE_NOT_APPROVED | 409 | 候选状态不正确 |
| NEO4J_UNAVAILABLE | 503 | 发布依赖不可用 |

### Graph 查询 API

| 方法 | 路径 | 角色 | 用途 |
| --- | --- | --- | --- |
| GET | /api/v1/graph | authenticated | 全局有限子图 |
| GET | /api/v1/graph/job-roles/{id} | authenticated | 岗位能力子图 |
| GET | /api/v1/graph/capabilities/{id} | authenticated | 技能邻域 |
| GET | /api/v1/graph/capabilities/{id}/prerequisites | authenticated | 前置技能 |
| GET | /api/v1/graph/diff | authenticated | 两版本差异 |
| GET | /api/v1/graph/versions/current | authenticated | 当前版本元数据 |

GET /graph 参数：

| 参数 | 默认 | 限制 |
| --- | --- | --- |
| version | current | 已发布版本 |
| domain_id | 无 | 可选 |
| job_level | 无 | junior/mid/senior |
| max_job_roles | 30 | 1 到 50 |
| max_capabilities | 120 | 1 到 200 |

岗位子图参数：version、job_level、include_prerequisites、include_related。

Diff 参数：<code>from_version</code>、<code>to_version</code>、<code>domain_id</code>。返回新增、关闭和属性变化的节点/关系摘要，不返回内部 Publication 账本。

## 👤 Applicant 简历、匹配与成长路径 API

### Resume 接口清单

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/resumes | applicant、hr | 202 | 上传简历并启动解析 |
| GET | /api/v1/resumes | applicant、hr、admin | 200 | 按所有权列表 |
| GET | /api/v1/resumes/{id} | owner、admin | 200 | 简历和状态 |
| GET | /api/v1/resumes/{id}/profiles | owner、admin | 200 | 画像版本 |
| GET | /api/v1/resumes/{id}/profiles/{version_no} | owner、admin | 200 | 完整画像 |
| POST | /api/v1/resumes/{id}/profiles/{version_no}/revisions | owner、admin | 201 | 基于当前画像创建 Draft Revision |
| PUT | /api/v1/resumes/{id}/profiles/{draft_version_no} | owner、admin | 200 | 替换未确认 Draft 结构 |
| POST | /api/v1/resumes/{id}/profiles/{version_no}/confirm | owner、admin | 200 | 确认画像 |
| POST | /api/v1/resumes/{id}/profiles/{version_no}/skills | owner、admin | 201 | 补充技能 |
| PATCH | /api/v1/resumes/{id}/profiles/{version_no}/skills/{skill_id} | owner、admin | 200 | 修正技能映射 |
| DELETE | /api/v1/resumes/{id}/profiles/{version_no}/skills/{skill_id} | owner、admin | 204 | 从新草稿版本移除误识别技能 |
| POST | /api/v1/resumes/{id}/reparse | owner、admin | 202 | 新版本重新解析 |
| POST | /api/v1/resumes/{id}/archive | owner、admin | 200 | 归档简历 |
| GET | /api/v1/resumes/{id}/extracted-text | owner、admin | 200 | 查看解析正文 |

HR 一般不直接调用 <code>POST /resumes</code>，而通过 Candidate Import 或 Candidate Resume 接口创建，保证 candidate_record_id 正确。独立 HR 上传必须要求 candidate_record_id。

### POST /resumes

applicant 请求：<code>multipart/form-data</code>

| 字段 | 必填 | 说明 |
| --- | :---: | --- |
| file | 是 | pdf 或 docx |
| display_name | 否 | 默认原文件名 |
| candidate_record_id | 否 | 仅 HR 必填，applicant 不允许传 |

返回：

~~~json
{
  "data": {
    "resource_id": "b7e8c612-358e-4e09-8256-e9012706ec7a",
    "run_id": "591b9d4b-5207-4249-99d4-e95677277c15",
    "status": "processing",
    "poll_url": "/api/v1/processing-runs/591b9d4b-5207-4249-99d4-e95677277c15"
  }
}
~~~

解析管线：

~~~mermaid
sequenceDiagram
    accTitle: Resume Parsing Sequence
    accDescr: Resume parsing flow from secure upload through text extraction and OCR fallback, parallel intelligent extraction, catalog mapping, evidence validation, and versioned profile persistence

    participant user as 👤 User
    participant api as 🌐 FastAPI
    participant worker as ⚙️ Celery worker
    participant algorithm as 🧠 Algorithm service
    participant llm as ☁️ LLM API
    participant database as 💾 PostgreSQL

    user->>api: Upload PDF or DOCX
    api->>database: Create file, resume, run
    api-->>user: 202 and run id
    worker->>worker: Extract text or OCR
    par Intelligent extraction
        worker->>algorithm: Parse resume
        algorithm-->>worker: Structured candidates
    and
        worker->>llm: Parse redacted resume
        llm-->>worker: Structured candidates
    end
    worker->>worker: Validate evidence and map catalog
    worker->>database: Save profile version
    worker->>database: Mark run completed
~~~

个人信息处理：

- Algorithm Service 在可信内网，可以接收任务必需文本
- 云端 LLM 请求前去除姓名、电话、邮箱、身份证号和详细地址
- 去敏替换符保留文本位置关系时，Evidence 校验需要使用映射表还原
- 原始正文只存 PostgreSQL 受控表，不写普通日志

### Profile 详情响应

~~~json
{
  "data": {
    "id": "977bc2af-e30d-4c93-b723-49fc08eb60de",
    "resume_id": "b7e8c612-358e-4e09-8256-e9012706ec7a",
    "version_no": 1,
    "status": "candidate",
    "summary": {
      "highest_education_level": "bachelor",
      "total_experience_months": 24
    },
    "educations": [],
    "experiences": [],
    "projects": [],
    "skills": [
      {
        "id": "42c7c299-0a20-4cd8-a479-349fd55efef1",
        "capability": {
          "id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
          "name": "Python"
        },
        "raw_name": "Python",
        "proficiency": "intermediate",
        "evidence_strength": "project",
        "mapping_status": "mapped",
        "confidence": 0.94,
        "user_confirmed": false,
        "evidence": [
          {
            "quote": "使用 Python 和 FastAPI 构建简历解析接口",
            "page_no": 1
          }
        ]
      }
    ],
    "unmapped_skill_count": 1,
    "validation_warnings": []
  }
}
~~~

### Profile 修改和确认

不允许直接 PATCH 已生成的 Profile。修改流程：

1. 第一次修改 Candidate Profile 时创建 Draft Revision，版本号递增
2. 技能增删改、教育、经历和项目修正写入新版本
3. confirm 动作验证映射状态和必填字段
4. 新版本变为 confirmed，旧 confirmed 变为 superseded

教育、经历和项目通过完整 Draft 更新：

1. <code>POST .../profiles/{version_no}/revisions</code> 基于 candidate 或 confirmed Profile 创建 manual_revision Draft；同一 Base Profile 已有 Draft 时返回该 Draft
2. <code>PUT .../profiles/{draft_version_no}</code> 用完整结构替换 Draft 内容
3. PUT 请求必须包含 expected_version_no 或 If-Match
4. 后端不允许客户端写 confidence、source、Evidence ID 和系统状态

补充已有技能：

~~~json
{
  "capability_id": "ed868b6f-08b3-4405-96a6-fb58ef169bad",
  "proficiency": "beginner",
  "evidence_strength": "mention"
}
~~~

补充未知技能：

~~~json
{
  "raw_name": "Agentic RAG 评测",
  "suggested_domain_id": "41902ab1-aae4-459d-a22f-fbf683a19021",
  "proficiency": "beginner"
}
~~~

后者同时创建 Capability Submission，响应包含 submission_id 和 pending_review。

### Applicant Job Recommendation API

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/job-recommendations | applicant | 202 | 对所有 Active Job Role 启动推荐 |
| GET | /api/v1/job-recommendations | applicant、admin | 200 | 推荐运行历史 |
| GET | /api/v1/job-recommendations/{match_run_id} | owner、admin | 200 | 推荐结果列表 |
| GET | /api/v1/matches/{match_id} | owner、admin | 200 | 匹配详情 |
| GET | /api/v1/matches/{match_id}/graph | owner、admin | 200 | 匹配相关局部图谱 |

启动请求：

~~~json
{
  "resume_profile_id": "977bc2af-e30d-4c93-b723-49fc08eb60de",
  "domain_ids": [
    "41902ab1-aae4-459d-a22f-fbf683a19021"
  ],
  "job_levels": ["junior", "mid"],
  "limit": 50
}
~~~

规则：

- applicant Profile 必须 confirmed
- 固定 Current Graph Version 和 Active Weight Version
- Algorithm /recommend-jobs 可以召回最多 50 个岗位候选
- 后端对召回候选逐一执行确定性评分
- 若 Algorithm Service 不可用，可以使用技能倒排查询做降级召回
- 完成后按高、中、低匹配分层，但保留原始分数

建议分层：

| 层级 | 条件 |
| --- | --- |
| high | overall_score >= 80 且 hard_requirement_status != not_met |
| medium | overall_score >= 60 |
| low | overall_score < 60 |

阈值属于版本化展示配置，不影响 Match Result 原始分数。

结果列表响应：

~~~json
{
  "data": [
    {
      "match_id": "f20bdcc7-93f6-40a8-bef1-80726a3abf4d",
      "job_role": {
        "id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
        "name": "AI 应用开发工程师"
      },
      "tier": "medium",
      "skill_score": 88.0,
      "overall_score": 76.5,
      "hard_requirement_status": "not_met",
      "matched_skill_count": 8,
      "missing_skill_count": 2
    }
  ],
  "meta": {
    "graph_version": 3,
    "weight_version": "match_weights_v1",
    "page": 1,
    "page_size": 20,
    "total": 35,
    "total_pages": 2
  }
}
~~~

### Match Detail

详情必须包含：

- Skill Score 和 Overall Score
- Hard Requirement Status 和问题
- 五个维度得分、权重和贡献
- matched、partial、missing、preferred 技能
- 简历 Evidence 和岗位 Evidence
- 使用的 Graph Version、Weight Version、Resume Profile Version
- 目标岗位局部图谱链接

不能只返回一个百分比。

### Growth Plan API

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/growth-plans | applicant、hr | 202 | 创建计划 |
| GET | /api/v1/growth-plans | owner、admin | 200 | 历史计划 |
| GET | /api/v1/growth-plans/{id} | owner、admin | 200 | 计划详情 |
| POST | /api/v1/growth-plans/{id}/regenerate | owner、admin | 202 | 基于当前版本重新生成 |
| POST | /api/v1/growth-plans/{id}/archive | owner、admin | 200 | 归档 |

applicant 创建请求：

~~~json
{
  "resume_profile_id": "977bc2af-e30d-4c93-b723-49fc08eb60de",
  "target_job_role_id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
  "match_result_id": "f20bdcc7-93f6-40a8-bef1-80726a3abf4d",
  "focus_capability_id": null
}
~~~

HR 创建时额外要求 recruitment_project_id，且 Profile 必须属于该项目的 Candidate Record。

点击某个缺失技能时传 <code>focus_capability_id</code>；点击意向岗位时传 null，生成完整岗位差距路径。

详情响应：

~~~json
{
  "data": {
    "id": "d6dd9f08-3c11-4bce-af8e-7dcf8135fa6d",
    "status": "ready",
    "target_job_role": {
      "id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
      "name": "AI 应用开发工程师"
    },
    "graph_version": 3,
    "summary": "优先补齐 RAG 评测基础，再进入端到端评测实践。",
    "steps": [
      {
        "sequence_no": 1,
        "stage": "core",
        "capability": {
          "id": "ed868b6f-08b3-4405-96a6-fb58ef169bad",
          "name": "RAG 评测"
        },
        "reason": "该技能是目标岗位的必备差距项",
        "task_description": "完成一个包含检索和生成指标的评测报告",
        "resources": [
          {
            "id": "99bceacd-f4de-4760-883a-823249048a91",
            "title": "RAG 评测入门",
            "url": "https://example.edu/rag-evaluation"
          }
        ]
      }
    ]
  }
}
~~~

如果没有审核资料，Step 仍可保存，但 resources 为空并将 Plan 标记 partial；LLM 不得临时编造 URL。

## 👥 HR 招聘项目与匹配 API

### Recruitment Project 接口

| 方法 | 路径 | 角色 | 成功 | 用途 |
| --- | --- | --- | ---: | --- |
| POST | /api/v1/recruitment-projects | hr、admin | 201 | 创建项目 |
| GET | /api/v1/recruitment-projects | hr、admin | 200 | 项目列表 |
| GET | /api/v1/recruitment-projects/{id} | owner、admin | 200 | 项目汇总 |
| PATCH | /api/v1/recruitment-projects/{id} | owner、admin | 200 | 修改名称和状态 |
| POST | /api/v1/recruitment-projects/{id}/close | owner、admin | 200 | 关闭项目 |
| POST | /api/v1/recruitment-projects/{id}/archive | owner、admin | 200 | 归档项目 |

创建请求：

~~~json
{
  "title": "AI 应用开发工程师招聘",
  "description": "2026 年秋季招聘"
}
~~~

项目详情返回 JD 数、候选人数、已解析人数、最近 Match Run 和状态统计。

### Recruitment JD 接口

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/recruitment-projects/{id}/job-descriptions | 202 | 输入或上传 JD 并解析 |
| GET | /api/v1/recruitment-projects/{id}/job-descriptions | 200 | JD 列表 |
| GET | /api/v1/recruitment-projects/{id}/job-descriptions/{jd_id} | 200 | JD 结构和技能 |
| POST | /api/v1/recruitment-projects/{id}/job-descriptions/{jd_id}/revisions | 201 | 基于当前版本创建修订 Draft |
| PUT | /api/v1/recruitment-projects/{id}/job-descriptions/{draft_jd_id} | 200 | 更新修订 Draft |
| POST | /api/v1/recruitment-projects/{id}/job-descriptions/{jd_id}/confirm | 200 | 确认匹配输入 |
| POST | /api/v1/recruitment-projects/{id}/job-descriptions/{jd_id}/reparse | 202 | 新版本重解析 |

创建支持二选一：

文本请求：

~~~json
{
  "title": "AI 应用开发工程师",
  "text": "岗位职责与任职要求全文"
}
~~~

或 multipart 文件上传。不能同时传 file 和 text，也不能都不传。

确认前 HR 可在修订 Draft 中：

- 修改 required/preferred
- 调整 importance
- 选择标准 Capability
- 提交未知技能审核
- 修改学历和经验 required/preferred

后端不允许 HR 创建全局 Active Capability。

<code>POST .../revisions</code> 不修改原 Job Description，而是复用 logical_jd_id 创建 version_no+1 的 Draft；<code>PUT .../{draft_jd_id}</code> 只允许在 If-Match 校验后更新 Draft。confirm 后旧 confirmed 版本变为 superseded。

### Candidate 接口

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/recruitment-projects/{id}/candidates | 201 | 创建候选记录 |
| GET | /api/v1/recruitment-projects/{id}/candidates | 200 | 候选列表 |
| GET | /api/v1/candidate-records/{id} | 200 | 候选详情 |
| PATCH | /api/v1/candidate-records/{id} | 200 | 修改联系信息和备注 |
| POST | /api/v1/candidate-records/{id}/resume | 202 | 上传候选简历 |
| GET | /api/v1/candidate-records/{id}/resumes | 200 | 简历版本列表 |
| POST | /api/v1/candidate-records/{id}/archive | 200 | 归档候选 |

创建候选请求：

~~~json
{
  "display_name": "候选人 A",
  "email": "candidate@example.com",
  "phone": null,
  "external_reference": "CAND-001"
}
~~~

### Candidate Import

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/recruitment-projects/{id}/candidate-imports | 202 | 批量上传简历 |
| GET | /api/v1/recruitment-projects/{id}/candidate-imports | 200 | 导入历史 |
| GET | /api/v1/recruitment-projects/{id}/candidate-imports/{import_id} | 200 | 导入结果 |

请求：multipart，可上传多份 PDF/DOCX，最多 100 个文件。可选 Manifest CSV 字段：filename、display_name、email、phone、external_reference。

处理规则：

- 文件名匹配 Manifest
- 无 Manifest 时 display_name 使用去扩展名文件名
- 每份文件创建 Candidate Record + Resume
- 单文件失败不阻止其他文件
- 任务完成后返回 created、parsed、failed 统计和错误下载链接

### Candidate Material API

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/candidate-records/{id}/materials | 201 | 添加文件或链接 |
| GET | /api/v1/candidate-records/{id}/materials | 200 | 材料列表 |
| PATCH | /api/v1/candidate-records/{id}/materials/{material_id} | 200 | 修改标题和顺序 |
| DELETE | /api/v1/candidate-records/{id}/materials/{material_id} | 204 | 移除材料关联 |

删除只移除 Candidate Material。若 Stored File 无其他引用，标记为待清理；不立即删除共享文件。

### Recruitment Match Run

| 方法 | 路径 | 成功 | 用途 |
| --- | --- | ---: | --- |
| POST | /api/v1/recruitment-projects/{id}/match-runs | 202 | 启动批量匹配 |
| GET | /api/v1/recruitment-projects/{id}/match-runs | 200 | 匹配历史 |
| GET | /api/v1/recruitment-projects/{id}/match-runs/{run_id} | 200 | Run 汇总 |
| GET | /api/v1/recruitment-projects/{id}/rankings | 200 | 当前或指定 Run 排名 |
| GET | /api/v1/recruitment-projects/{id}/matches/{match_id} | 200 | 匹配详情 |

启动请求：

~~~json
{
  "job_description_id": "14fc1002-5b07-468f-b337-a41708ff1a73",
  "candidate_ids": null,
  "include_partial_profiles": false
}
~~~

规则：

- JD 必须 confirmed/ready
- 默认匹配项目全部 ready Candidate
- candidate_ids 可选用于重算子集
- HR 候选使用 active_profile_id 指向的最新 candidate 或 confirmed Profile；存在 ambiguous/unmapped required input、解析失败或阻塞性警告时跳过并记录错误
- include_partial_profiles=false 时跳过 parse_status=partial 的候选；true 时允许使用 partial Profile，但 Match Detail 必须显示画像不完整警告
- 固定 Graph Version 和 Weight Version
- 每个候选独立失败，Run 可 partial

Rankings 参数：

- match_run_id，默认最近 completed/partial
- hard_requirement_status
- min_overall_score
- has_missing_required_skill
- q：候选名或编号
- page、page_size

排名响应：

~~~json
{
  "data": [
    {
      "rank": 1,
      "candidate": {
        "id": "8ebdbd46-5d41-4de0-89d4-71bbfc7d20af",
        "display_name": "候选人 A",
        "external_reference": "CAND-001"
      },
      "match_id": "f20bdcc7-93f6-40a8-bef1-80726a3abf4d",
      "skill_score": 88.0,
      "overall_score": 76.5,
      "hard_requirement_status": "not_met",
      "matched_skill_count": 8,
      "missing_skill_count": 2,
      "profile_status": "confirmed"
    }
  ],
  "meta": {
    "match_run_id": "db1cf0be-bc68-4cc4-9ee0-4e268eb5ade1",
    "job_description_id": "14fc1002-5b07-468f-b337-a41708ff1a73",
    "graph_version": 3,
    "weight_version": "match_weights_v1",
    "page": 1,
    "page_size": 20,
    "total": 42,
    "total_pages": 3
  }
}
~~~

HR Match Detail 与 applicant Match Detail 使用同一个 Response Schema，但增加 Candidate 和 Project 上下文以及材料链接。

## 🧩 内部 Algorithm Service 与 LLM 契约

### 网络与认证

Algorithm Service 只暴露在 Docker Compose 内部网络，不映射公网端口。FastAPI/Worker 调用时携带：

~~~text
Authorization: Bearer <ALGORITHM_SERVICE_TOKEN>
X-Request-ID: <request-id>
Content-Type: application/json
~~~

Algorithm Service：

- 不连接 PostgreSQL、Redis、Neo4j 和文件 Volume
- 不持久化用户业务数据
- 请求结束后不保留完整简历正文
- 只返回结构化候选和模型元数据
- 对相同输入不承诺业务幂等，由主系统通过 Input Hash 管理

### GET /health

响应：

~~~json
{
  "status": "ok",
  "ready": true,
  "service_version": "1.0.0"
}
~~~

### GET /model-info

响应：

~~~json
{
  "service_version": "1.0.0",
  "label_schema_version": "job-capability-labels-v1",
  "models": {
    "analyze_jd": "job-analyzer@2026-08-04",
    "parse_resume": "resume-parser@2026-08-04",
    "recommend_jobs": "job-retriever@2026-08-04",
    "cluster_skills": "skill-clusterer@2026-08-04"
  },
  "ready": true
}
~~~

Worker 在任务开始时记录此响应。模型版本与任务要求不兼容时，不继续运行并写 <code>ALGORITHM_SCHEMA_INCOMPATIBLE</code>。

### POST /analyze-jd

请求：

~~~json
{
  "request_id": "3f087e48-b82c-46a3-8caf-625d1738953e",
  "job": {
    "title": "AI 测试开发工程师",
    "description": "完整清洗后 JD 文本",
    "source_tags": ["Python", "自动化测试"],
    "education_text": "本科",
    "experience_text": "3 年以上"
  },
  "catalog": {
    "version": 2,
    "candidate_capabilities": [
      {
        "id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
        "name": "Python",
        "aliases": ["Python 语言"]
      }
    ],
    "candidate_job_roles": [
      {
        "id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
        "name": "AI 应用开发工程师",
        "aliases": []
      }
    ]
  }
}
~~~

响应：

~~~json
{
  "request_id": "3f087e48-b82c-46a3-8caf-625d1738953e",
  "model": {
    "name": "job-analyzer",
    "version": "2026-08-04",
    "label_schema_version": "job-capability-labels-v1"
  },
  "job_family": {
    "raw_label": "测试运维",
    "candidate_job_role_id": null,
    "confidence": 0.93,
    "evidence": {
      "quote": "负责大模型应用的自动化测试与评测",
      "start_offset": 0,
      "end_offset": 18
    }
  },
  "skills": [
    {
      "raw_name": "Python",
      "candidate_capability_id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
      "requirement_type": "required",
      "required_level": "intermediate",
      "importance": 0.9,
      "confidence": 0.96,
      "evidence": {
        "quote": "熟练使用 Python 开发自动化测试工具",
        "start_offset": 42,
        "end_offset": 61
      }
    }
  ],
  "education": {
    "mode": "required",
    "level": "bachelor",
    "confidence": 0.98,
    "evidence": {
      "quote": "本科及以上学历",
      "start_offset": 80,
      "end_offset": 87
    }
  },
  "experience": {
    "mode": "required",
    "minimum_months": 36,
    "confidence": 0.95,
    "evidence": {
      "quote": "3 年以上相关经验",
      "start_offset": 88,
      "end_offset": 97
    }
  }
}
~~~

主系统校验：

- request_id 完全一致
- Model Info 字段存在
- Evidence Offset 和 Quote 匹配输入
- candidate_capability_id 出现在请求候选集中
- requirement_type、level、importance 和 confidence 合法
- 不接受 Algorithm 返回的最终正式 Job Role 或 Capability 创建指令

### POST /parse-resume

请求：

~~~json
{
  "request_id": "503093e4-c48d-402e-a885-c66adfb50667",
  "resume": {
    "text": "完成文本提取后的简历正文",
    "language": "zh-CN"
  },
  "catalog": {
    "version": 2,
    "candidate_capabilities": [
      {
        "id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
        "name": "Python",
        "aliases": ["Python 语言"]
      }
    ]
  }
}
~~~

响应字段：

- education[]
- work_experiences[]
- projects[]
- skills[]
- 每项 Evidence
- Model Name、Version 和 Label Schema Version

技能项：

~~~json
{
  "raw_name": "Python",
  "candidate_capability_id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
  "proficiency": "intermediate",
  "experience_months": 24,
  "evidence_strength": "project",
  "confidence": 0.94,
  "evidence": {
    "quote": "使用 Python 和 FastAPI 构建简历解析接口",
    "start_offset": 120,
    "end_offset": 145
  }
}
~~~

candidate_capability_id 只表示候选映射。主系统仍需执行 Catalog Status、别名歧义和 Evidence 校验。

### POST /recommend-jobs

用途：候选召回，不计算正式匹配分。

请求：

~~~json
{
  "request_id": "f45a4870-d242-40ba-aa48-d28fc3c13b71",
  "profile": {
    "capabilities": [
      {
        "id": "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
        "proficiency": "intermediate",
        "evidence_strength": "project"
      }
    ],
    "education_level": "bachelor",
    "experience_months": 24,
    "project_summaries": [
      "使用 Python 和 FastAPI 构建简历解析接口"
    ]
  },
  "candidate_job_roles": [
    {
      "id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
      "name": "AI 应用开发工程师",
      "required_capability_ids": [
        "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9"
      ]
    }
  ],
  "limit": 50
}
~~~

响应：

~~~json
{
  "request_id": "f45a4870-d242-40ba-aa48-d28fc3c13b71",
  "model": {
    "name": "job-retriever",
    "version": "2026-08-04"
  },
  "candidates": [
    {
      "job_role_id": "ce7a14c1-0cf4-4b51-8294-5beb9e2ca26d",
      "relevance_score": 0.91,
      "reason_codes": ["skill_overlap", "project_evidence"]
    }
  ]
}
~~~

relevance_score 只用于召回排序，不保存为 Overall Score。

### POST /cluster-skills

用途：接受经过主系统过滤和去重的 JD 技能向量或引用特征，输出聚类候选。

请求不传数据库连接信息。第一版为了避免一次传入大量全文，只传匿名 Feature Item：

~~~json
{
  "request_id": "53b45634-5d88-433c-9a44-1f1f30a6b73e",
  "algorithm_version": "skill-combination-v1",
  "items": [
    {
      "item_id": "opaque-feature-id-1",
      "capability_ids": [
        "2b59bc2b-9860-4b4f-9c22-e58e97cf19c9",
        "ed868b6f-08b3-4405-96a6-fb58ef169bad"
      ],
      "embedding": [0.12, 0.08, 0.44],
      "sample_weight": 0.82
    }
  ],
  "parameters": {
    "minimum_cluster_size": 5,
    "similarity_threshold": 0.78,
    "maximum_clusters": 50
  }
}
~~~

实际 Embedding 维度由模型契约确定。示例仅缩短展示。

响应：

~~~json
{
  "request_id": "53b45634-5d88-433c-9a44-1f1f30a6b73e",
  "model": {
    "name": "skill-clusterer",
    "version": "2026-08-04"
  },
  "clusters": [
    {
      "cluster_id": "cluster-1",
      "item_ids": ["opaque-feature-id-1"],
      "representative_capability_ids": [
        "ed868b6f-08b3-4405-96a6-fb58ef169bad"
      ],
      "coherence_score": 0.88
    }
  ]
}
~~~

主系统通过临时映射把 opaque item_id 关联回 Normalized JD，Algorithm Service 不知道业务数据库 ID 以外的来源详情。

### Algorithm 错误响应

~~~json
{
  "error": {
    "code": "MODEL_NOT_READY",
    "message": "requested model is not loaded",
    "retryable": true
  },
  "request_id": "503093e4-c48d-402e-a885-c66adfb50667"
}
~~~

稳定错误码：

| 错误码 | HTTP | 主系统处理 |
| --- | ---: | --- |
| UNAUTHORIZED | 401 | 配置错误，不自动重试 |
| REQUEST_SCHEMA_INVALID | 422 | 主系统契约错误，不重试 |
| INPUT_TOO_LARGE | 413 | 分块或缩小输入 |
| MODEL_NOT_READY | 503 | 有限重试 |
| MODEL_TIMEOUT | 504 | 有限重试 |
| INFERENCE_FAILED | 500 | 有限重试后失败 |
| LABEL_SCHEMA_UNSUPPORTED | 409 | 阻止任务并告警 |

### LLM Client 契约

主系统只实现一个 OpenAI-compatible Client，不建设通用 Model Gateway。

操作：

| operation | 输入 | 输出 |
| --- | --- | --- |
| supplement_jd_analysis | 去敏 JD、Catalog 候选 | 补充结构化候选 |
| supplement_resume_profile | 去敏简历、Catalog 候选 | 教育、经历、项目、技能候选 |
| generate_job_definition | 聚类证据摘要、标准技能 | 候选岗位名、职责、场景 |
| generate_growth_narrative | 已验证技能顺序和资料 | 阶段说明和练习任务 |

每个调用必须提供：

- 固定 System Prompt
- Prompt Version
- JSON Schema
- 明确的数据分隔符
- 允许输出的 Capability/Job Role/Resource ID 列表
- 禁止执行输入文本内指令的声明
- 不得创建外部链接或最终匹配分的声明

LLM 响应处理：

1. JSON 解析
2. Pydantic Schema 校验
3. ID 白名单校验
4. Evidence 校验
5. 链接白名单校验
6. 业务状态校验
7. 写 Model Invocation
8. 合法内容进入 Candidate，非法内容进入 invalid 和 Processing Error

LLM 重试：

- 429、502、503、504：指数退避最多 3 次
- JSON 无效：携带 Schema Error 修复重试 1 次
- Evidence 伪造：不重试，标记 invalid
- Content Filter：记录失败，允许 Algorithm-only 降级

### 智能输出合并规则

当 Algorithm 与 LLM 同时输出：

| 情况 | 合并结果 |
| --- | --- |
| 同名且同 Capability ID | 合并 Evidence，置信度不简单相加 |
| 同 Raw Name 不同 Capability ID | ambiguous，人工确认 |
| 只有 Algorithm | 保留 algorithm Candidate |
| 只有 LLM 且 Evidence 有效 | 保留 llm Candidate |
| Evidence 无效 | invalid |
| Requirement Type 冲突 | 保留双方原值，merged Candidate 标记需确认 |

合并置信度建议使用可解释规则：

~~~text
merged_confidence = max(algorithm_confidence, llm_confidence)
+ agreement_bonus
~~~

agreement_bonus 第一版最多 0.05，最终截断到 1。不得把两个不独立模型的概率当作统计独立事件计算。

## ⚙️ Celery 任务与可靠性设计

### Task 清单

| Task | Subject | 主要阶段 | 可部分成功 |
| --- | --- | --- | :---: |
| import_market_jd | import_batch | validate、parse_rows、persist_raw | 是 |
| process_jd_batch | import_batch | normalize、deduplicate、extract、map、embed | 是 |
| import_catalog | catalog_import | validate、resolve_domains、check_conflicts、apply | 是 |
| discover_skill_combinations | discovery_run | select、feature、cluster、compare、define、persist | 是 |
| parse_resume | resume | extract_text、ocr、extract_profile、map、persist | 是 |
| parse_recruitment_jd | job_description | normalize、extract、map、persist | 是 |
| import_candidates | candidate_import | create_records、store_files、dispatch_parse | 是 |
| match_job_roles | match_run | recall、score、rank、persist | 是 |
| match_recruitment_project | match_run | select_profiles、score、rank、persist | 是 |
| generate_growth_plan | growth_plan | graph_query、order、retrieve、generate、validate | 是 |
| publish_graph_version | graph_version | snapshot、write、verify、switch | 否 |
| check_learning_resource | learning_resource | head_or_get、classify、persist | 单项 |
| reconcile_pending_runs | system | scan、requeue、mark_stale | 是 |
| clean_expired_sessions | system | scan、delete | 是 |
| clean_unattached_files | system | scan、verify、delete | 是 |

### Run 状态机

~~~mermaid
stateDiagram-v2
    accTitle: Durable Processing Lifecycle
    accDescr: Formal PostgreSQL task lifecycle including enqueue failure, worker execution, review waiting, cooperative cancellation, authorized retry, and terminal states

    [*] --> Pending: Create run
    Pending --> Running: Worker claims
    Pending --> EnqueueFailed: Queue unavailable
    Pending --> Cancelled: Cancel before claim
    EnqueueFailed --> Pending: Reconcile or retry
    Running --> WaitingReview: Human decision required
    Running --> Completed: All required work done
    Running --> Failed: Retry budget exhausted
    Running --> CancelRequested: User requests cancel
    CancelRequested --> Cancelled: Worker reaches safe point
    WaitingReview --> Running: Approved continuation
    WaitingReview --> Completed: Review closes workflow
    Failed --> Pending: New retry run created
    Completed --> [*]: Terminal
    Cancelled --> [*]: Terminal
~~~

注意：Failed -> Pending 表示创建了新 Retry Run 的逻辑关系，旧 Failed Run 本身保持 Failed。

### 投递一致性

API 创建任务：

1. PostgreSQL 事务创建业务资源、Processing Run 和 Idempotency Record
2. 提交事务
3. 调用 Celery <code>apply_async</code>
4. 成功后写 celery_task_id 和 enqueued_at
5. 失败则写 enqueue_failed

第一版不增加通用 Outbox 表。Celery Beat 每分钟扫描 enqueue_failed 和超过阈值的 pending Run，重新投递；Processing Run 的幂等键防止重复业务结果。若后续证明投递丢失频繁，再引入专用 Outbox。

### Worker Claim

Worker 收到 Run ID 后：

~~~sql
SELECT ... FOR UPDATE SKIP LOCKED;
~~~

只有 pending/enqueue_failed 可以 Claim。Claim 原子写：

- status=running
- attempt_count=attempt_count+1
- started_at=COALESCE(started_at, now())
- heartbeat_at=now()

若 Run 已终态，Task 直接退出；重复 Celery 消息不会重复处理。

### Heartbeat 与 Stale Run

- Worker 每 30 秒或阶段切换更新 heartbeat_at
- Running Run 超过 5 分钟无心跳标记为疑似 stale
- Reconciler 先检查 Celery Worker 和依赖健康，再决定重投递
- 达到 max_attempts 后标记 failed
- 发布图谱使用独立 claim_token，不由通用 Stale 逻辑直接抢占

阈值保存配置，不通过普通前端暴露。

### 进度更新

更新条件满足任意一项：

- 阶段切换
- 处理 10 项
- 距上次更新 2 秒
- 新增错误
- 任务结束

progress_percent 由后端计算，Worker 不能任意提交超过已完成阶段的百分比。对于阶段权重不同的任务，Task 定义固定 Stage Weight。

示例：process_jd_batch

| 阶段 | 进度范围 |
| --- | --- |
| validating | 0-5 |
| normalizing | 5-25 |
| deduplicating | 25-35 |
| extracting | 35-70 |
| mapping | 70-85 |
| embedding | 85-98 |
| finalizing | 98-100 |

### 分批与事务

| 任务 | 建议 Chunk | 事务边界 |
| --- | ---: | --- |
| Raw JD 写入 | 500 行 | 每 Chunk |
| Normalization | 100 条 | 每 Chunk |
| Algorithm/LLM 抽取 | 10-20 条 | 每条结果独立持久化 |
| Embedding | 服务允许批量大小 | 每批 |
| Candidate Import | 10 个文件 | 每个候选独立 |
| Matching | 20 个候选 | 每个 Match Result 独立 |
| Graph Publication | 一个版本 | 单个 Neo4j Transaction 或可验证的小批次 |

批任务中一项失败不能回滚已经完成的其他项，但同一项的 Profile、Skill 和 Evidence 必须同事务写入。

### 重试矩阵

| 错误 | 自动重试 | 次数 | 说明 |
| --- | :---: | ---: | --- |
| PostgreSQL 连接瞬断 | 是 | 3 | 指数退避 |
| Redis/Celery Broker 瞬断 | 是 | 3 | Run 保留 |
| Algorithm 5xx/timeout | 是 | 3 | Item 级重试 |
| LLM 429/5xx | 是 | 3 | 尊重 Retry-After |
| LLM JSON 无效 | 是 | 1 | Schema 修复提示 |
| Neo4j 连接失败 | 是 | 3 | 发布幂等 |
| OCR 进程失败 | 是 | 1 | 再失败标记该文件失败 |
| 文件格式非法 | 否 | 0 | 输入错误 |
| Evidence 无效 | 否 | 0 | Candidate invalid |
| Catalog 映射歧义 | 否 | 0 | 等待人工确认 |
| 权限错误 | 否 | 0 | API 阻止 |
| 业务状态冲突 | 否 | 0 | 返回 409 |

### 合作式取消

检查点：

- 每个阶段开始前
- 每个 Chunk 完成后
- 外部服务调用前
- 外部服务调用返回后
- 最终持久化前

取消保留：

- 已保存 Raw JD
- 已完成的 Profile Version
- 已完成的 Match Result
- Processing Errors
- Model Invocation

取消不删除已有中间结果。用户重新启动时可以选择新版本处理。

### 任务结果链接

Processing Run 的 result_summary 保存资源摘要和 API 链接，例如：

~~~json
{
  "resource_type": "match_run",
  "resource_id": "db1cf0be-bc68-4cc4-9ee0-4e268eb5ade1",
  "result_url": "/api/v1/job-recommendations/db1cf0be-bc68-4cc4-9ee0-4e268eb5ade1",
  "summary": {
    "created_results": 35,
    "failed_items": 0
  }
}
~~~

API 不根据 run_type 在前端猜测跳转地址。

### 定时任务

| 周期 | Task | 用途 |
| --- | --- | --- |
| 每分钟 | reconcile_pending_runs | 重投递 enqueue_failed 和检查 pending |
| 每 5 分钟 | detect_stale_runs | 检查 Running 心跳 |
| 每小时 | clean_expired_sessions | 清理过期 Session |
| 每天 | clean_unattached_files | 清理过期且无引用文件 |
| 每天 | check_selected_learning_resources | 可选检查近期使用链接 |

不在第一版自动执行市场 JD 爬取，也不自动运行 Discovery 或图谱发布。

## 🛡️ 权限、安全与数据治理

### 权限矩阵

| 资源或动作 | applicant | hr | admin |
| --- | --- | --- | --- |
| 登录 | 允许 | 允许 | 允许 |
| 查看全局正式图谱 | 允许 | 允许 | 允许 |
| 查看 Catalog Active 数据 | 允许 | 允许 | 允许 |
| 上传本人简历 | 允许 | 不适用 | 允许 |
| 查看本人简历和匹配 | 允许 | 不允许 | 允许 |
| 创建招聘项目 | 不允许 | 允许 | 允许 |
| 查看本人招聘项目 | 不允许 | 允许 | 允许 |
| 查看其他 HR 项目 | 不允许 | 不允许 | 允许 |
| 上传外部候选简历 | 不允许 | 允许 | 允许 |
| 查看项目候选材料 | 不允许 | 项目 owner | 允许 |
| 导入市场 JD | 不允许 | 不允许 | 允许 |
| 运行候选组合发现 | 不允许 | 不允许 | 允许 |
| 查看新岗位发现候选 | 不允许 | 允许 | 允许 |
| 提交 HR Business Feedback | 不允许 | 允许 | 可以 |
| 全局知识审核 | 不允许 | 不允许 | 允许 |
| 维护 Catalog | 不允许 | 不允许 | 允许 |
| 发布图谱版本 | 不允许 | 不允许 | 允许 |
| 管理用户 | 不允许 | 不允许 | 允许 |
| 查看完整 Model Invocation | 不允许 | 不允许 | 允许 |
| 查看权限内任务 | 本人 | 本人项目 | 全部 |

### 对象所有权规则

#### Resume

- owner_user_id 非空：只有该 applicant 和 admin 可访问
- candidate_record_id 非空：只有 Candidate 所属 Project Owner 和 admin 可访问
- HR 不能访问独立 applicant Resume
- applicant 不能访问任何 Candidate Record Resume

#### Recruitment Project

- owner_hr_id 等于当前用户：允许
- 当前用户 admin：允许
- 其他情况：404

第一版没有 Project Member 表，不存在隐式协作者。

#### Processing Run

- owner_scope_type=user：scope_id 必须等于当前用户
- owner_scope_type=recruitment_project：项目必须归当前 HR
- owner_scope_type=admin_global：仅 admin

#### File

文件访问从业务引用反查：

1. applicant Resume File -> Resume Owner
2. Candidate Resume/Material -> Project Owner
3. Recruitment JD File -> Project Owner
4. Market Import File -> admin
5. 尚未绑定的 File -> uploaded_by_user_id，且只能短期访问

不能因为用户曾上传文件，就永久拥有该文件的访问权。

#### Match Result

- applicant Recommendation -> Match Run applicant_user_id
- HR Project Match -> Recruitment Project Owner
- admin -> 全部

#### Growth Plan

- owner_user_id -> applicant
- recruitment_project_id -> HR Project Owner
- admin -> 全部

### 数据库权限

应用使用单一受限 PostgreSQL 用户：

- 允许业务表 SELECT/INSERT/UPDATE/DELETE
- 不允许 CREATE DATABASE、SUPERUSER 和文件系统函数
- Migration 使用独立数据库用户或启动阶段凭证
- Algorithm Service 没有数据库凭证
- Neo4j 凭证只提供给 API/Worker

### 文件安全流程

~~~mermaid
flowchart LR
    accTitle: Secure File Intake Flow
    accDescr: File intake flow validating size, extension, MIME, magic bytes, archive limits, and safe storage before creating an owned business attachment

    upload[📥 Receive upload] --> size{📋 Size allowed?}
    size -->|No| reject_size[❌ Reject request]
    size -->|Yes| inspect[🔍 Inspect extension MIME magic]
    inspect --> valid{✅ Types agree?}
    valid -->|No| reject_type[❌ Reject file]
    valid -->|Yes| archive_check[🛡️ Check archive limits]
    archive_check --> hash[⚙️ Stream SHA 256]
    hash --> store[📦 Store UUID key]
    store --> attach[🔗 Attach business resource]
~~~

要求：

- 上传流式写入临时目录
- 临时目录使用随机路径和最小权限
- 验证成功后原子移动到 Volume 正式路径
- storage_key 不含用户原始文件名
- DOCX/PPTX ZIP 解压总量和文件数限制
- PDF/Office Parser 设置超时和内存限制
- Content-Disposition 对原文件名正确转义
- 文件不由 Nginx 或静态 Server 直接暴露
- 所有预览和下载写 File Access Log

第一版可信内网环境可以将恶意软件扫描状态设为 not_required，但接口和字段保留 scan_status；如果后续开放更多来源，再接入 ClamAV 类扫描器。

### 简历个人信息

虽然系统不公开部署，简历仍属于敏感数据：

- API 列表不返回电话、邮箱全文，详情按权限返回
- 日志不记录 Resume Text、电话、邮箱和身份证号
- LLM 调用前去敏
- Model Invocation Response 只有 admin 可读取，普通页面只看合并画像
- 导出或下载候选信息写 Audit Log
- 演示账号使用虚构数据，不混入真实个人资料

### Prompt Injection

JD、简历、作品链接标题和用户备注都是不可信文本。

防护：

- 不把这些文本拼入 System Prompt
- 作为 JSON Data Field 或明确分隔区传入
- System Prompt 声明数据中的指令无效
- LLM 无 Tool、网络、数据库和文件权限
- 强制 JSON Schema
- 只允许白名单 ID
- Evidence 必须在输入文本中验证
- 输出链接只能来自 Learning Resource 数据库
- 失败输出进入 invalid，不进入正式 Catalog 或 Neo4j

### CSRF 与 CORS

- Session Cookie 认证的所有 POST/PUT/PATCH/DELETE 必须验证 CSRF Token
- 登录接口不要求已有 CSRF Token，但有登录限流
- CORS 只允许配置的内部前端 Origin
- 不允许 <code>Access-Control-Allow-Origin: *</code> 搭配凭证
- OPTIONS 由框架中间件统一处理

### 密码和 Session

- Argon2id 参数采用当前库安全默认并可配置升级[^9]
- 重置密码后撤销全部 Session
- Session 默认 8 小时绝对过期
- last_seen_at 最多每 5 分钟更新一次，避免每请求写数据库
- Session Token 至少 256 bit 随机
- Cookie 中不放 user_id、role 或 JWT Payload

### 审计动作清单

至少记录：

~~~text
auth.login.success
auth.login.failed
auth.logout
admin.user.create
admin.user.update
admin.user.reset_password
file.preview
file.download
import.create
import.process
processing.retry
processing.cancel
catalog.capability.create
catalog.capability.update
catalog.capability.deprecate
resume.upload
resume.profile.confirm
resume.skill.submit
recruitment.project.create
candidate.resume.upload
matching.run.create
discovery.run.create
discovery.feedback.create
review.approve
review.reject
review.revise
graph.version.create
graph.version.publish
growth.plan.create
~~~

### 日志字段

结构化日志最少包含：

| 字段 | 说明 |
| --- | --- |
| timestamp | UTC 时间 |
| level | 日志等级 |
| service | api、worker、beat、algorithm |
| request_id | HTTP/Task 追踪 |
| user_id | 可空 |
| processing_run_id | 可空 |
| operation | 稳定操作名 |
| duration_ms | 可空 |
| outcome | success/failed |
| error_code | 可空 |

禁止写入：密码、Session Token、CSRF Token、LLM API Key、完整简历、完整 JD、完整外部响应 Header。

## ⚠️ 领域错误码与状态转换

### Import 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| IMPORT_NOT_FOUND | 404 | 批次不存在或不可见 |
| IMPORT_SCHEMA_NOT_RECOGNIZED | 422 | 字段无法识别 |
| SOURCE_ADAPTER_MISMATCH | 422 | 来源与格式冲突 |
| IMPORT_EMPTY | 422 | 无有效行 |
| IMPORT_ALREADY_PROCESSING | 409 | 已有运行任务 |
| IMPORT_ALREADY_ARCHIVED | 409 | 批次已归档 |
| IMPORT_PIPELINE_ALREADY_COMPLETED | 409 | 同版本已完成 |

### Catalog 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| CAPABILITY_NAME_CONFLICT | 409 | Domain 内标准名冲突 |
| CAPABILITY_ALIAS_AMBIGUOUS | 409 | 别名指向多个技能 |
| CAPABILITY_NOT_ACTIVE | 409 | 不能用于正式关系 |
| CAPABILITY_IN_USE | 409 | 无法执行破坏性修改 |
| JOB_ROLE_NAME_CONFLICT | 409 | 岗位名称冲突 |
| CATALOG_VERSION_CONFLICT | 409 | 目录版本变化 |
| SUBMISSION_ALREADY_RESOLVED | 409 | 未知技能已处理 |

### Resume 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| RESUME_NOT_READY | 409 | 尚无可用画像 |
| RESUME_PROFILE_NOT_DRAFT | 409 | 不能修改非 Draft |
| RESUME_PROFILE_ALREADY_CONFIRMED | 409 | 已确认 |
| RESUME_SKILL_AMBIGUOUS | 409 | 技能映射歧义 |
| RESUME_FILE_PARSE_FAILED | 422 | 文件无法解析 |
| OCR_FAILED | 422 | 扫描文档 OCR 失败 |

### Recruitment 与 Matching 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| PROJECT_NOT_ACTIVE | 409 | 项目关闭或归档 |
| JOB_DESCRIPTION_NOT_READY | 409 | JD 未确认 |
| CANDIDATE_NOT_READY | 409 | 候选画像不可用 |
| NO_MATCHABLE_CANDIDATES | 422 | 没有可匹配候选 |
| MATCH_RUN_ALREADY_RUNNING | 409 | 同目标任务正在运行 |
| MATCH_WEIGHT_VERSION_MISSING | 503 | 无 Active 权重版本 |
| GRAPH_VERSION_MISSING | 503 | 无 Published 当前图谱 |
| MATCH_RESULT_NOT_FOUND | 404 | 结果不存在或不可见 |

### Discovery、Review 与 Graph 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| DISCOVERY_INPUT_NOT_READY | 409 | 输入批次未完成 |
| DISCOVERY_INSUFFICIENT_DATA | 422 | 支持样本不足 |
| DISCOVERY_ALREADY_PROPOSED | 409 | 已转审核候选 |
| REVIEW_ALREADY_DECIDED | 409 | 已审核 |
| REVIEW_EVIDENCE_MISSING | 422 | 没有可验证证据 |
| GRAPH_VERSION_NOT_DRAFT | 409 | 版本不可发布 |
| GRAPH_PUBLICATION_RUNNING | 409 | 已有发布运行 |
| GRAPH_BASE_VERSION_CHANGED | 409 | Base 变化 |
| GRAPH_PUBLICATION_VERIFY_FAILED | 502 | Neo4j 读回不一致 |

### Growth 错误码

| 错误码 | HTTP | 说明 |
| --- | ---: | --- |
| GROWTH_TARGET_NOT_MATCHED | 422 | 目标与画像无有效匹配上下文 |
| GROWTH_NO_SKILL_GAPS | 409 | 没有缺失或部分技能 |
| GROWTH_GRAPH_CYCLE | 422 | 前置关系无法安全排序 |
| GROWTH_RESOURCE_UNAVAILABLE | 200 | 不作为失败，Plan 标记 partial |

### 资源状态转换

| 资源 | 合法转换 |
| --- | --- |
| Import Batch | uploaded -> processing -> processed/partial/failed -> archived；当前 API 创建后直接进入 processing |
| Resume | uploaded -> processing -> ready/partial/failed -> archived |
| Resume Profile | candidate -> draft/confirmed/invalid；draft -> confirmed/invalid；confirmed -> superseded |
| Recruitment Project | draft -> active -> closed -> archived |
| Recruitment JD | draft -> processing -> ready/partial/failed；ready/draft -> confirmed；confirmed -> superseded；任意非归档终态 -> archived |
| Candidate Record | imported -> processing -> ready/partial/failed -> archived |
| Discovery Candidate | candidate -> feedback_collected/proposed_for_review/rejected |
| Graph Change Candidate | pending -> needs_revision/approved/rejected -> published |
| Graph Version | draft -> publishing -> published/failed；failed -> publishing/abandoned |
| Growth Plan | pending -> generating -> ready/partial/failed -> archived |

状态动作只能通过对应 Domain Service，不允许 Repository 接收任意 status 更新。

## 🩺 健康检查与运行诊断

### 主系统健康接口

| 方法 | 路径 | 认证 | 用途 |
| --- | --- | --- | --- |
| GET | /health/live | 无 | 进程事件循环可响应 |
| GET | /health/ready | 无或内网 | PostgreSQL、Redis、Neo4j 必需依赖 |
| GET | /api/v1/admin/system/dependencies | admin | 依赖明细和延迟 |
| GET | /api/v1/admin/system/versions | admin | API、Migration、Prompt、模型和当前图谱版本 |

Ready 规则：

| 依赖 | 是否阻止 Ready |
| --- | :---: |
| PostgreSQL | 是 |
| Redis | 是，无法创建后台任务 |
| Neo4j | 是，图谱和匹配依赖 |
| Algorithm Service | 否，报告 degraded |
| LLM API | 否，报告 unknown/degraded，不主动消耗 Token 探测 |
| File Volume | 是，必须可读写 |

Ready 响应：

~~~json
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
~~~

### Worker 诊断

Admin Dependencies 返回：

- 活跃 Worker 数
- Celery Queue 长度
- Pending/Running/Stale Run 数
- 最近一次 Beat 心跳
- Algorithm Model Info
- Current Graph Version
- Active Catalog Version
- Active Match Weight Version

不向普通用户开放系统依赖细节。

## 🧱 Migration 与实施顺序

### Migration 原则

- 每个 Migration 只完成一个可验证主题
- 先建被引用表，再建引用表
- 循环 FK 延后添加
- Check Constraint 和 Unique Index 与表同时创建
- Seed 使用单独可重复执行脚本，不把大量技能数据硬编码进 Alembic
- Neo4j Constraint 由独立启动 Migration 命令执行
- Migration 不调用 LLM、Algorithm 或外部网络

### 建议 Alembic 顺序

| Migration | 内容 |
| --- | --- |
| 0001 | pgvector、pg_trgm 扩展与基础约定 |
| 0002 | users、auth_sessions、login_attempts、audit_logs |
| 0003 | stored_files、file_access_logs |
| 0004 | processing_runs、processing_errors、idempotency_records |
| 0005 | data_sources、import_batches、raw_job_postings、normalized_job_postings |
| 0006 | duplicate_clusters、duplicate_cluster_members |
| 0007 | catalog_versions、catalog_version_items、domains、capabilities、aliases、job_roles、aliases |
| 0008 | catalog_imports、learning_resources、capability_submissions |
| 0009 | job_analysis_profiles、job_skill_candidates、evidence_spans、model_invocations、embedding_records |
| 0010 | discovery_runs、skill_combination_candidates、combination_skills、combination_evidence、business_feedback |
| 0011 | graph_change_candidates、review_decisions、graph_versions、graph_version_items、graph_publications、graph_settings |
| 0012 | recruitment_projects、candidate_records |
| 0013 | resumes、resume_profiles、education、experience、projects、skills，随后添加 active_profile FK |
| 0014 | job_descriptions、job_requirement_skills、candidate_materials、candidate_imports |
| 0015 | match_weight_versions、match_runs、match_results、维度/技能/条件明细 |
| 0016 | growth_plans、growth_steps、growth_step_resources |
| 0017 | 查询性能索引和搜索索引 |

Migration 可以在实施时按真实依赖合并相邻小步，但不能把全部表塞进一个初始 Migration，避免难以审查和回滚。

### Seed 顺序

1. 创建首个 admin，密码通过环境变量或启动命令输入
2. 创建 Initial Catalog Version
3. 导入 Domain 骨架
4. 导入初始 Capability 和 Alias 骨架
5. 导入初始 Job Role 和 Alias
6. 创建 match_weights_v1 并激活
7. 创建 Demo Applicant 和 Demo HR，可选
8. 导入审核后的 Learning Resource
9. 创建首个 Graph Version 并发布

Demo 数据必须标记 source_type=seed/demo，答辩页面不把 Seed 结果冒充实时发现结果。

### API 实施批次

#### Batch A：基础可运行

- Auth、Admin User
- Files
- Processing Run
- Health
- OpenAPI 公共响应和错误中间件

#### Batch B：市场数据中心

- Imports
- Adapter
- Raw/Normalized JD
- Processing Pipeline
- Catalog 查询和管理

#### Batch C：智能候选和图谱

- Algorithm/LLM Client
- Job Analysis
- Discovery
- Review
- Graph Version/Publication/Query

#### Batch D：Applicant

- Resume Parse/Profile
- Applicant Recommendation
- Match Detail
- Growth Plan

#### Batch E：HR

- Recruitment Project/JD
- Candidate/Materials/Import
- Batch Matching/Ranking
- HR Discovery Feedback

这个顺序允许在每批结束后形成一个可演示闭环，不要求等全部接口完成才可运行。

## 🧪 数据库与 API 测试设计

### 数据库约束测试

必须覆盖：

- username_normalized 唯一
- Resume owner_user_id 与 candidate_record_id 二选一
- Growth Plan owner_user_id 与 recruitment_project_id 二选一
- Match Run 两种模式二选一
- Match Result 两种 Target 二选一
- Candidate Material file/url 二选一
- 分数和置信度范围
- Profile Version 唯一
- 一个 Resume 同时最多一个 Confirmed Profile
- 一个 Graph Change Candidate 最多进入一个 Graph Version
- 同时最多一个 Publishing Graph Version
- Active Match Weight Version 唯一
- 幂等键唯一

### Repository 测试

- 权限范围查询不返回他人资源
- Raw JD 不支持更新
- Audit Log 只追加
- 列表筛选、分页和总数一致
- Partial Index 对队列查询生效
- Catalog Alias 歧义返回多个候选
- Current Profile 和 Current Graph Pointer 原子切换

### Service 测试

- 登录成功、失败、限流和停用
- 文件 MIME/扩展名/Magic 冲突
- Import Adapter 识别和相对日期
- 乱码修复和城市冲突警告
- JD 去重不重复放大 Evidence
- Algorithm/LLM Evidence 校验
- 未知技能只进入 Submission
- applicant Profile 确认与人工修订创建新版本；HR 未修订 Candidate Profile 可直接用于批量匹配
- HR 与 applicant 所有权隔离
- 必备/优先技能分别计分
- 学历经验硬条件独立展示
- Partial Skill 只接受正式图谱关系
- Growth Plan 不生成未知链接
- Review 状态并发冲突
- Graph Publication 崩溃恢复

### API 测试

每个写接口至少覆盖：

- 成功路径
- 未登录 401
- 角色不允许 403
- 他人资源 404
- Schema 错误 422
- 状态冲突 409
- Idempotency 重复请求
- Audit Log 生成

每个列表接口至少覆盖：

- 权限范围
- 默认排序
- 页码边界
- page_size 最大值
- 筛选组合
- 空结果

### 异步任务测试

- API 创建 Run 后投递成功
- Broker 失败后 Run 保留为 enqueue_failed
- 重复 Celery 消息只 Claim 一次
- Worker 中断后 Stale 检测
- Item 级失败形成 partial
- Cancel 在阶段边界生效
- Retry 创建新 Run，不覆盖旧 Run
- Progress 单调不回退
- Result URL 正确

### Algorithm Contract 测试

使用 Mock Server 覆盖：

- 正常响应
- 超时和 5xx
- 无效 JSON
- Label Schema 不兼容
- Evidence Quote 不存在
- Offset 错误
- 未请求的 Capability ID
- Requirement Type 非法
- 重试后成功

### Neo4j 集成测试

- Node UUID Constraint
- 当前版本关系查询
- 历史版本关系查询
- 关闭旧关系
- 重复发布幂等
- Neo4j 提交后 PostgreSQL Ack 前模拟崩溃
- 读回数量不一致不切 Current Pointer
- Job Role 两跳子图限制
- Growth 前置深度和循环检测

### PRD 端到端验收

#### 场景 1：智联市场 JD 导入

1. admin 上传智联样例
2. 系统识别 zhilian_v1
3. 307 行进入 Raw JD
4. 缺正文记录形成质量警告
5. 双重编码文本得到修复或明确警告
6. 城市冲突保留 Raw 值和标准化决定
7. 处理任务完成或 partial
8. 每个 Normalized JD 可回到 Raw Row

#### 场景 2：候选技能组合发现

1. admin 选择已处理批次
2. 系统过滤低质量和重复 JD
3. 生成技能共现特征
4. Algorithm Service 聚类
5. 与当前图谱比较
6. LLM 生成候选定义
7. Candidate 展示技能、支持 JD、来源和置信度
8. 页面明确标注候选而非确认趋势

#### 场景 3：HR 反馈和图谱发布

1. HR 查看 Candidate 和 Evidence
2. HR 提交 revise Feedback
3. admin 转为 Graph Change Candidate
4. admin 修订并 approve
5. 创建 Draft Graph Version
6. 发布到 Neo4j
7. 读回验证成功
8. Current Version 切换
9. 旧版本仍可查询

#### 场景 4：Applicant 简历与岗位推荐

1. applicant 登录上传普通 PDF
2. PyMuPDF 提取文本
3. Algorithm 与 LLM 产生候选
4. 后端校验 Evidence 和 Catalog
5. applicant 补充一个已有技能和一个未知技能
6. 未知技能进入 Submission
7. applicant 确认 Profile
8. 启动岗位推荐
9. 展示 High/Medium/Low 和 Match Detail
10. 选择缺失技能生成 Growth Plan

#### 场景 5：扫描简历

1. 上传无有效文本层 PDF
2. 触发 PaddleOCR
3. 保存 text_extraction_method=ocr
4. OCR 失败时返回明确错误，不生成空 Profile
5. OCR 成功时 Evidence 保留页码

#### 场景 6：HR 批量候选匹配

1. HR 创建 Project 和 JD
2. 确认 required/preferred 技能、学历和经验
3. 批量上传 10 份简历
4. 其中 1 份格式失败，Run 标记 partial
5. 9 份 Profile 可用
6. 启动 Match Run
7. 排名按 Overall、Skill、Hard Status 稳定输出
8. Match Detail 显示项目 Evidence、缺失技能和硬条件
9. HR 查看 Candidate Material

#### 场景 7：权限隔离

1. HR A 创建项目和候选
2. HR B 使用资源 ID 请求详情
3. API 返回 404
4. applicant 无法访问任何 Candidate Record
5. HR 无法访问独立 Applicant Resume
6. admin 可以审计访问

#### 场景 8：任务恢复

1. 创建批处理 Run
2. Worker 处理中重启
3. Heartbeat 超时
4. Reconciler 判断可重试
5. 新尝试复用已完成 Item 结果
6. 不生成重复 Profile、Match Result 或 Graph Relation

### 性能基线

第一版内部部署目标，不承诺互联网级并发：

| 场景 | 目标 |
| --- | --- |
| 普通列表 API | P95 小于 500 ms，不含外部服务 |
| 图谱岗位子图 | P95 小于 1 s |
| 任务轮询 | P95 小于 300 ms |
| 100 份候选排名读取 | 小于 1 s |
| 307 行样例批次导入 | 可在单次演示流程内完成，具体时间记录基准 |
| 文件上传 | 流式处理，不随文件大小线性占用内存 |

算法、LLM、OCR 的处理时间单独记录，不纳入同步 API 延迟目标。

### 测试覆盖目标

- 核心 Domain Service 和权限分支覆盖率不低于 80%
- 项目整体覆盖率不低于 PRD 要求的 60%
- 所有权限矩阵行至少一个集成测试
- 所有核心状态转换至少一个成功和一个非法转换测试
- 所有外部依赖至少一个失败恢复测试

## 📌 最终实施结论

### 第一阶段必须落地

为了尽快形成真实可用闭环，第一阶段实现顺序是：

1. Identity、Session、Files、Processing Run
2. Market JD Import、Raw/Normalized JD、Catalog Skeleton
3. Algorithm/LLM JD Analysis、Candidate Mapping
4. Discovery、Review、Graph Publication 和 Graph Query
5. Resume Parse/Profile
6. Applicant Matching
7. Recruitment Project、JD、Candidate Import 和 Ranking
8. Growth Plan

### 有意识的简化

当前方案没有引入：

- 通用微服务拆分
- 通用 Outbox 框架
- 通用 Workflow/Agent 编排
- 通用动态字段系统
- 多租户权限模型
- 自动生成所有表 CRUD
- 为每种多态 Evidence 建独立表
- 多个 Embedding 维度混存

这些简化不会破坏当前 PRD 的真实闭环。只有出现明确吞吐、协作、部署或模型需求时才升级。

### 实施前仅需固定的配置值

这些不是产品歧义，不阻止设计评审；实施时通过配置确定：

| 配置 | 建议默认 |
| --- | --- |
| Session 绝对过期 | 8 小时 |
| Polling 间隔 | 2-3 秒 |
| 市场 JD 文件上限 | 50 MB |
| 简历文件上限 | 20 MB |
| Candidate Import 上限 | 100 份 |
| Graph 全局节点上限 | 250 |
| Growth Graph 最大深度 | 4 |
| LLM Timeout | 60 秒 |
| Algorithm Timeout | 60 秒 |
| 外部服务自动重试 | 最多 3 次 |
| Processing Heartbeat | 30 秒 |
| Stale Run 阈值 | 5 分钟 |

### 文档与实现关系

实施过程中：

- Alembic Migration 必须满足本文数据库约束
- SQLAlchemy Model 不得弱化二选一、范围和唯一约束
- Pydantic Schema 不得允许客户端写系统字段
- Router 不得绕过 Domain Service 状态转换
- Celery Task 不得成为唯一业务状态源
- Neo4j 不得接收未审核 Candidate
- Algorithm/LLM 输出不得直接进入正式 Catalog、Match Score 或外部链接

### 参考资料

[^1]: FastAPI. "FastAPI Documentation." https://fastapi.tiangolo.com/

[^2]: SQLAlchemy. "SQLAlchemy 2.0 Documentation." https://docs.sqlalchemy.org/en/20/

[^3]: Alembic. "Alembic Documentation." https://alembic.sqlalchemy.org/

[^4]: PostgreSQL Global Development Group. "PostgreSQL Documentation." https://www.postgresql.org/docs/

[^5]: pgvector. "Open-source vector similarity search for Postgres." https://github.com/pgvector/pgvector

[^6]: Neo4j. "Cypher Manual." https://neo4j.com/docs/cypher-manual/current/

[^7]: Celery Project. "Celery Documentation." https://docs.celeryq.dev/

[^8]: Redis. "Redis Documentation." https://redis.io/docs/latest/

[^9]: IETF. (2021). "The memory-hard Argon2 password hash and proof-of-work function." RFC 9106. https://www.rfc-editor.org/rfc/rfc9106

---

_文档结束 · 数据库与 API 设计版本 v1.0 · 2026-08-05_
