# 岗位能力图谱系统后端

面向比赛展示与团队内部真实使用的岗位能力图谱后端。当前已形成 Batch A-G 七段岗位图谱闭环，并完成应聘者简历画像与岗位推荐闭环：

- Batch A：三角色内部账号、Session/CSRF、安全文件读取、Processing Run 生命周期和依赖健康诊断。
- Batch B：市场 JD 批量上传、来源 Adapter、Raw/Normalized 双层数据、质量警告、重新处理，以及技能/岗位 Catalog 骨架导入。
- Batch C：标准技能库精确映射、候选技能组合发现、可追溯 Evidence、Discovery Run 和 admin/hr 查询 API。
- Batch D：候选岗位定义提案、HR/admin 人工修改与确认、不采纳、不可变审核历史和审计记录。
- Batch E：管理员把审核通过的岗位提案发布为 PostgreSQL 正式岗位、完整 Catalog Version 和 Neo4j 岗位能力子图。
- Batch F：三种登录角色读取 Neo4j 正式全局有限子图和单岗位能力子图，PostgreSQL 校验当前发布水位与正式主数据状态。
- Applicant Resume Profile：应聘者上传单份 PDF/DOCX，异步抽取可追溯画像，人工修订并确认唯一当前版本。
- Batch G：Applicant 基于当前 confirmed Profile 和正式岗位目录同步生成确定性推荐，保存完整 Match Run/Result 快照，支持历史分页、岗位差距明细和自然幂等复用。
- Applicant Growth Path：基于历史岗位匹配快照和全部缺失必备技能，同步生成受标准技能库约束、可解释且可复用的结构化成长路径。

本仓库包含后端、前端、JD 数据和知识图谱生成工具。当前没有公开注册接口，也没有脱离业务资源的通用文件上传接口。

## 技术栈

- Python 3.12、FastAPI、SQLAlchemy 2、Alembic
- PostgreSQL 16 + pgvector：业务事实与任务状态唯一真相源
- Neo4j 5 Community：只接收审核通过并由管理员发布的正式图谱投影
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

启动前端：

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5174`，开发代理会把 `/api` 转发到后端 `/api/v1`。

创建首个管理员时，命令行会通过 `getpass` 要求输入并确认密码；密码不会回显。首个账号必须是 `admin`，后续 applicant、hr、admin 账号由管理员 API 创建和维护。

启动成功后：

- OpenAPI / Swagger UI：<http://127.0.0.1:8000/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>
- API 根前缀：`/api/v1`

在尚未单独启动 Algorithm Service 时，Ready 响应中的 `algorithm_service` 会是 `degraded`；LLM 三项配置任一缺失时，`llm_service` 也会是 `degraded`。这两项都是允许的降级状态，PostgreSQL、Redis、Neo4j 和文件卷四个必需依赖必须全部为 `ok`。

示例：

```json
{
  "status": "ready",
  "dependencies": {
    "postgresql": "ok",
    "redis": "ok",
    "neo4j": "ok",
    "file_volume": "ok",
    "algorithm_service": "degraded",
    "llm_service": "degraded"
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

文件 API 只提供可见性校验后的读取、Range 预览、附件下载和访问审计。业务文件分别由 Import、Catalog 和 Resume 模块创建，不提供无业务归属的普通上传 API。已绑定 Resume 的原始文件仅 applicant owner 和 admin 可读，HR 或其他 applicant 获得脱敏的 404。

### Processing Run

- `GET /api/v1/processing-runs`
- `GET /api/v1/processing-runs/{run_id}`
- `GET /api/v1/processing-runs/{run_id}/errors`
- `GET /api/v1/processing-runs/{run_id}/result`
- `POST /api/v1/processing-runs/{run_id}/retry`
- `POST /api/v1/processing-runs/{run_id}/cancel`

普通用户只能看到 `owner_scope_type=user` 且属于自己的任务；管理员可以查看全局任务。失败重试会创建新 Run，不会把旧 Run 改回 pending。

### Applicant Resume Profile

- `POST /api/v1/resumes`
- `GET /api/v1/resumes`
- `GET /api/v1/resumes/{resume_id}`
- `GET /api/v1/resumes/{resume_id}/profiles`
- `GET /api/v1/resumes/{resume_id}/profiles/{version_no}`
- `GET /api/v1/resumes/{resume_id}/extracted-text`
- `POST /api/v1/resumes/{resume_id}/profiles/{version_no}/revisions`
- `PUT /api/v1/resumes/{resume_id}/profiles/{version_no}`
- `POST /api/v1/resumes/{resume_id}/profiles/{version_no}/confirm`
- `POST /api/v1/resumes/{resume_id}/archive`

当前能力：

- applicant 单份上传 20 MB 以内的 PDF/DOCX/JPG/PNG，获得异步 `ProcessingRun` 和轮询地址；图片先在后端使用中英 Tesseract OCR 转写，再由 DeepSeek 完成结构化抽取和证据校验，图片原件不发送给模型；
- 后端在本地提取正文，对手机号、Email、身份证号和微信号进行等长脱敏后才调用 Provider；
- 使用 Responses API Structured Outputs，校验原文 exact evidence，并只与 active Capability/active Alias 精确匹配；
- extracted Profile 不原地修改；applicant 从 candidate/confirmed 创建人工 Revision，整体替换 Draft，并为每份 Resume 保持最多一个 confirmed Profile；
- PostgreSQL 是 Resume、Profile、Skill、Run 和审核事实唯一真相源；简历流程不写 Neo4j，也不自动创建 Capability。

Resume LLM 配置是可选的，三项必须同时提供才会启用解析：

```dotenv
LLM_RESPONSES_URL=https://api.deepseek.com/anthropic
LLM_API_KEY=<provider-api-key>
LLM_MODEL=deepseek-v4-flash
```

任一项缺失（包括三项全部为空）时，API、其他模块和 `/health/ready` 仍可启动；Ready 返回 200 且 `llm_service=degraded`。新 Resume Worker 会以稳定错误码 `LLM_NOT_CONFIGURED` 失败，配置恢复后可通过现有 Processing Run retry 接口创建新的不可变 Run。

Provider 兼容边界：

- `LLM_RESPONSES_URL` 支持 OpenAI Responses endpoint，也支持 DeepSeek Anthropic 兼容根地址（自动请求 `/v1/messages`）；
- DeepSeek `deepseek-v4-flash` 的 `thinking` 内容会被跳过，只解析 `text` 内容，且 Anthropic 兼容请求至少保留 8000 `max_tokens`；
- 请求固定使用 `input`/`input_text`、`text.format.type=json_schema`、`strict=true`、`stream=false` 和 `store=false`；
- 不提供 Chat Completions fallback，不接通用 Provider 抽象，也不使用 LangChain/LangGraph。

当前非目标：OCR、简历批量导入、Resume 图谱写入、自动创建 Capability、调用 Algorithm Service。扫描版 PDF 应先在外部完成 OCR，再上传文字型 PDF/DOCX。

以下命令只使用 placeholder 和仓库内的虚构测试 PDF，不要把真实 Session、API Key、简历正文或 Provider raw response 写入 README、Shell 历史或 Git。

上传简历；响应中的 `resource_id` 是 `RESUME_ID`，`run_id` 是 `RUN_ID`：

```bash
curl -X POST http://localhost:8000/api/v1/resumes \
  -b "session=<session-cookie>" \
  -H "X-CSRF-Token: <csrf-token>" \
  -H "Idempotency-Key: demo-resume-001" \
  -F "file=@./backend/tests/fixtures/resume_text.pdf;type=application/pdf" \
  -F "display_name=比赛演示简历"
```

轮询 Processing Run；完成后从 `/result` 读取 `result_url`：

```bash
curl -b "session=<session-cookie>" \
  http://localhost:8000/api/v1/processing-runs/<run-id>

curl -b "session=<session-cookie>" \
  http://localhost:8000/api/v1/processing-runs/<run-id>/result
```

读取 candidate Profile。普通 Resume 详情不会返回 `extracted_text`；原始正文只能通过专用 `/api/v1/resumes/{resume_id}/extracted-text` endpoint 读取，并且仅 owner/admin 有权访问：

```bash
curl -b "session=<session-cookie>" \
  http://localhost:8000/api/v1/resumes/<resume-id>/profiles/<profile-version>
```

从 candidate/confirmed 创建 Revision，整体保存 Draft，再确认该版本：

```bash
curl -X POST \
  -b "session=<session-cookie>" \
  -H "X-CSRF-Token: <csrf-token>" \
  http://localhost:8000/api/v1/resumes/<resume-id>/profiles/<source-version>/revisions

curl -X PUT \
  -b "session=<session-cookie>" \
  -H "X-CSRF-Token: <csrf-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "document_language": "zh-CN",
    "summary": "人工确认后的画像",
    "educations": [],
    "experiences": [],
    "projects": [],
    "skills": [{
      "raw_name": "Python",
      "capability_id": null,
      "proficiency": "intermediate",
      "explicit_experience_months": 24,
      "evidence_strength": "mention",
      "evidence_quote": null
    }]
  }' \
  http://localhost:8000/api/v1/resumes/<resume-id>/profiles/<draft-version>

curl -X POST \
  -b "session=<session-cookie>" \
  -H "X-CSRF-Token: <csrf-token>" \
  http://localhost:8000/api/v1/resumes/<resume-id>/profiles/<draft-version>/confirm
```

### Applicant 岗位推荐

- `POST /api/v1/job-recommendations`
- `GET /api/v1/job-recommendations`
- `GET /api/v1/job-recommendations/{match_run_id}`
- `GET /api/v1/job-recommendations/{match_run_id}/job-roles/{job_role_id}`

POST 请求体只接受 `resume_id`，需要 CSRF；GET 不需要 CSRF。Applicant 只能访问自己的 Resume 和 Match Run，Admin 可以为任意 applicant Resume 运营排查，HR 不可访问本模块。

匹配只读取 PostgreSQL 中当前唯一 confirmed Profile、current published Graph/Catalog 水位和目录内 active 岗位/技能，不调用 LLM、Algorithm Service、Celery、Redis 或 Neo4j。`match_weights_v1` 使用 required、bonus、evidence、experience、education 五维 Decimal 评分，结果按自然键 `resume_profile_id + graph_version_id + weight_version` 幂等复用。

每次成功计算会保存全部岗位的不可变 Match Run/Match Result 快照，POST 只返回 Top 20；历史列表和结果页支持 `page=1..`、`page_size=1..100`，单岗位详情返回完整 matched/missing 技能数组。历史岗位名称、定义和 Domain 均来自结果快照，不会被当前 Catalog 修改覆盖。

### Applicant 成长路径

- `POST /api/v1/job-recommendations/{match_run_id}/job-roles/{job_role_id}/growth-path`
- `GET /api/v1/job-recommendations/{match_run_id}/job-roles/{job_role_id}/growth-path`

POST 无请求体，需要 CSRF；第一次生成返回 `reused=false`，相同 Match Result 和 `growth_path_v1` 再次请求直接返回已保存结果并标记 `reused=true`。GET 只读取已有结果，不需要 CSRF；尚未生成时返回 `GROWTH_PATH_NOT_FOUND`。Applicant 只能操作自己的 Match Result，Admin 可以代为生成或读取，HR 返回 `ROLE_NOT_ALLOWED`。

成长路径一次覆盖该岗位全部缺失的 `required` Capability。没有缺失必备技能时，POST 返回 `409 GROWTH_PATH_NOT_REQUIRED`，不会调用 LLM。生成沿用 `LLM_RESPONSES_URL`、`LLM_API_KEY` 和 `LLM_MODEL`，固定使用 Responses API `text.format` strict Structured Outputs；只发送不可变岗位快照、标准 Capability 事实和脱敏匹配摘要，不发送简历正文、姓名、联系方式、学校/公司、`raw_name` 或 `evidence_quote`。

后端要求每个缺失必备 Capability 在模型结果中必须且只能出现一次，并用 PostgreSQL 标准技能快照补全名称、类型和 Domain；总周数由后端求和。结果按 `match_run_id + job_role_id + growth_path_v1` 幂等保存，不写 Neo4j，不使用 LangChain、LangGraph、Celery、Redis、web search 或外部课程检索，也不会生成课程 URL。

### HR 私有 JD 招聘匹配

HR 招聘项目是内部演示版的完整闭环，使用单独的项目和候选人数据边界：

- `POST /api/v1/recruitment-projects`、`GET /api/v1/recruitment-projects`、`GET /api/v1/recruitment-projects/{project_id}`
- `POST /api/v1/recruitment-projects/{project_id}/jd`
- `PUT /api/v1/recruitment-projects/{project_id}/requirements`
- `POST /api/v1/recruitment-projects/{project_id}/requirements/confirm`
- `POST /api/v1/recruitment-projects/{project_id}/candidates`、`GET /api/v1/recruitment-projects/{project_id}/candidates`、`GET /api/v1/recruitment-projects/{project_id}/candidates/{candidate_id}`
- `POST /api/v1/recruitment-projects/{project_id}/match-runs`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results`
- `GET /api/v1/recruitment-projects/{project_id}/match-runs/{run_id}/results/{candidate_id}`

最小演示顺序如下。所有写请求都需要当前登录 Session 的 CSRF Header；带文件的请求同时使用 `multipart/form-data` 和 `Idempotency-Key`。

1. 以 `hr` 登录，创建招聘项目，保存返回的 `PROJECT_ID`。
2. 提交文本 JD 或 PDF/DOCX/TXT 文件。接口立即返回 `run_id`，通过 `/api/v1/processing-runs/{run_id}` 轮询，不在 HTTP 请求中等待 LLM。
3. 任务完成后，从项目详情的 `jd_draft_payload` 读取抽取草稿；HR 可以通过 `PUT .../requirements` 整体替换岗位标题、学历/经验门槛、标准 Capability 要求和未映射技能，再调用 `POST .../requirements/confirm` 固化不可变 revision。相同内容重复确认会复用原 revision。
4. 批量上传 1 到 20 份 PDF/DOCX 候选简历，继续轮询候选解析 Processing Run。每个候选独立处理；部分失败不会回滚已成功候选，失败候选在后续 Match Run 中进入 `skipped_candidates` 快照。
5. 调用 `POST .../match-runs` 同步生成全量确定性排名，再读取结果列表和单候选差距明细。相同已确认要求、候选状态/Profile 版本和 `match_weights_v1` 会直接返回 `reused=true` 的历史 Run。
   默认启用 Compose 中的 `graph_match_v1.0` 服务，结果中的 `dimension_scores.lgf` 会附带算法模型分数。后端把已确认 JD 的标准 Capability、权重和候选人的标准技能动态传给模型，不依赖 10 岗占位数据。LGF 不改写现有五维 `total_score` 和排序；超时、不可用或响应无效时只标记 `degraded`，原有匹配继续生效。
6. 通过候选详情中的 file URL 读取原始简历元数据、预览或下载内容。项目 owner 和 admin 可见，其他 HR 与 applicant 得到脱敏 404；跨项目的 candidate/run ID 也不会被解析。

这条链路的职责边界是固定的：市场爬虫暂未接入，当前数据入口是管理员批量导入；LLM 只负责 JD/简历的结构化候选抽取和 Evidence 校验，标准 Capability Catalog 是唯一真相源，后端负责映射、五维评分、排序、快照和幂等；企业私有 JD 匹配不调用 Neo4j，也不依赖 LangChain/LangGraph。Neo4j 只服务于已经审核发布的公共岗位能力图谱读取。

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
- `GET /api/v1/emerging-jobs`
- `GET /api/v1/capability-evolution`

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

算法同学离线生成的岗位定义可以由管理员直接导入待审核队列：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -F 'file=@new_job_definitions.json;type=application/json' \
  http://127.0.0.1:8000/api/v1/algorithm-results/job-definitions
```

导入只精确映射现有 active Capability/active Alias，未知技能保留在来源快照中，不会自动入库。结果以 `pending` 提案进入现有审核与图谱发布流程；相同文件重复上传会复用已有提案。

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

`approve` 只表示审核通过并获得后续发布资格，不会自动创建 active JobRole，也不会自动写入 Neo4j；管理员还需要执行下方的正式发布接口。每次决定都保存 before/after Payload、审核人、时间和意见；发布完成后提案进入 `published` 只读终态。

### 正式图谱发布

- `POST /api/v1/graph-versions`
- `GET /api/v1/graph-versions`
- `GET /api/v1/graph-versions/{version_id}`
- `POST /api/v1/graph-versions/{version_id}/publish`

四个接口全部仅管理员可用，两个写接口需要 CSRF Token。管理员先从一个 `approved` 且类型为 `create_job_role` 的审核提案创建 Draft Graph Version：

```bash
PROPOSAL_ID='替换为 approved review proposal id'

curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"proposal_id\": \"${PROPOSAL_ID}\"}" \
  http://127.0.0.1:8000/api/v1/graph-versions
```

创建接口会校验：提案已经审核通过、至少包含两个 active 必备技能、必备技能属于同一技术域、加分技能全部 active，并且同一技术域中不存在同名岗位。系统同时创建 Draft Catalog Version、预分配稳定 JobRole UUID，并固化 Domain、岗位定义、技能、证据摘要和 SHA256 relation key 快照。对同一 Proposal 重复调用会返回原 Graph Version，不会重复创建。

将返回的 `id` 赋给 `GRAPH_VERSION_ID` 后执行同步发布：

```bash
GRAPH_VERSION_ID='替换为 graph version id'

curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -X POST \
  "http://127.0.0.1:8000/api/v1/graph-versions/${GRAPH_VERSION_ID}/publish"
```

发布流程先使用 PostgreSQL UUID 和 relation key 向 Neo4j 幂等 `MERGE` Domain、JobRole、Capability、`BELONGS_TO`、`REQUIRES` 和 `BONUS`，再读回目标岗位的技能与关系数量。验证成功后，PostgreSQL 在一个事务内完成以下操作：

1. 创建 active JobRole 和 JobRoleCapability。
2. 将全部 active Capability、既有 active JobRole 和新岗位写入新的完整 Catalog Version。
3. 将新的 Catalog Version 和 Graph Version 标记为 `published/current`。
4. 将审核提案标记为 `published` 并保存审计记录。

查询发布结果：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/graph-versions/${GRAPH_VERSION_ID}"
curl -sS -b /tmp/job-graph-cookies.txt \
  http://127.0.0.1:8000/api/v1/catalog/versions/current
curl -sS -b /tmp/job-graph-cookies.txt \
  http://127.0.0.1:8000/api/v1/catalog/job-roles
```

Neo4j 写入或读回验证失败时，Graph Version 进入 `failed`，`last_error` 只保存安全的错误类型；PostgreSQL 不会创建 active JobRole，也不会激活 Catalog Version。管理员可对同一 Graph Version 再次调用 publish，系统会复用原 UUID、快照和 relation key 重试。第一版是适合比赛展示与团队内部使用的同步单岗位发布，不包含 Celery 发布 Worker、批量发布拓扑或企业级回滚编排。

### 正式图谱读取

- `GET /api/v1/graph`
- `GET /api/v1/graph/job-roles/{job_role_id}`

两个接口允许 applicant、hr、admin 读取，只要求有效 Session Cookie；GET 不需要 CSRF Token。读取 current published GraphVersion 作为响应水位，但不会按 current version 过滤 Neo4j 节点，因为正式图投影会累积保留更早发布且仍然 active 的岗位。

读取全局有限子图：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  'http://127.0.0.1:8000/api/v1/graph?max_job_roles=30&max_capabilities=120'
```

按 active Domain 限制岗位：

```bash
DOMAIN_ID='替换为 active domain id'

curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/graph?domain_id=${DOMAIN_ID}&max_job_roles=30&max_capabilities=120"
```

读取单个 active JobRole 的完整岗位能力子图：

```bash
JOB_ROLE_ID='替换为 active job role id'

curl -sS -b /tmp/job-graph-cookies.txt \
  "http://127.0.0.1:8000/api/v1/graph/job-roles/${JOB_ROLE_ID}"
```

全局接口最多返回 50 个岗位和 200 个唯一 Capability，默认分别为 30 和 120。岗位、技能或内部关系行超出限制时，响应中的 `truncated` 为 `true`；调用方可以缩小 Domain 范围或调整允许的 limit。单岗位当前最多包含 20 个必备技能和 20 个加分技能，因此不分页。

响应只包含 `domain`、`job_role`、`capability` 节点和 `belongs_to`、`requires`、`bonus` 关系。节点 ID 使用 PostgreSQL UUID，关系 ID 使用发布阶段生成的 SHA256 `relation_key`。接口不返回原始 JD、Evidence、审核提案、发布快照、数据库连接信息或 Neo4j 查询文本。

没有 current published GraphVersion、Domain/JobRole 不存在、PostgreSQL 与 Neo4j 投影不一致、Neo4j 读取失败时，分别返回稳定的 `GRAPH_VERSION_NOT_PUBLISHED`、`GRAPH_DOMAIN_NOT_FOUND`、`GRAPH_JOB_ROLE_NOT_FOUND`、`GRAPH_PROJECTION_INCONSISTENT` 或 `GRAPH_READ_FAILED`。

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

本地测试依赖应迁移到当前 Alembic head（现为 `0012`）。创建测试库并应用 Migration：

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
- Neo4j 只接收管理员正式发布的审核通过图谱，不接收导入原文，也不写入未经审核的算法或大模型候选知识。

## 设计文档

- [后端技术架构详细设计](./outputs/岗位能力图谱系统_后端技术架构详细设计.md)
- [数据库与 API 详细设计](./outputs/岗位能力图谱系统_数据库与API详细设计.md)
- [Batch A：后端基础闭环实施计划](./docs/superpowers/plans/2026-08-06-backend-foundation.md)
- [Batch B：市场 JD 数据中心实施计划](./docs/superpowers/plans/2026-08-06-market-jd-center.md)
- [Batch C：候选技能组合发现实施计划](./docs/superpowers/plans/2026-08-06-candidate-discovery.md)
- [Batch D：候选岗位审核实施计划](./docs/superpowers/plans/2026-08-06-candidate-review.md)
- [Batch E：正式图谱发布实施计划](./docs/superpowers/plans/2026-08-06-graph-publication.md)
- [Batch F：正式图谱读取实施计划](./docs/superpowers/plans/2026-08-06-graph-read-api.md)
- [Applicant Resume Profile 设计](./docs/superpowers/specs/2026-08-06-resume-profile-design.md)
- [Applicant Resume Profile 实施计划](./docs/superpowers/plans/2026-08-06-resume-profile.md)
- [Applicant 成长路径生成设计](./docs/superpowers/specs/2026-08-07-growth-paths-design.md)

当前实现仍不包含爬虫管理、定时调度、JD 语义聚类或外部 Algorithm Service。Resume 模块只用 LLM 生成可人工确认的候选画像；它不能创建正式 Capability/JobRole，也不能写 Neo4j。岗位侧算法或大模型候选仍必须经过人工审核，并由管理员通过正式 Catalog/Graph Version 发布后才能进入 active 主数据和 Neo4j 投影。
