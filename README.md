# 岗位能力图谱系统后端

面向比赛展示与团队内部真实使用的岗位能力图谱后端。当前 Batch A 已形成可运行的基础闭环：三角色内部账号、Session/CSRF、管理员账号维护、安全文件读取、Processing Run 生命周期、Celery Worker/Beat，以及依赖健康诊断。

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

本地测试依赖已运行并迁移到 `0004` 的 PostgreSQL 测试库。创建测试库并应用 Migration：

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
- Neo4j 在 Batch A 只做连接检查，不写入算法或大模型未经审核的候选知识。

## 设计文档

- [后端技术架构详细设计](./outputs/岗位能力图谱系统_后端技术架构详细设计.md)
- [数据库与 API 详细设计](./outputs/岗位能力图谱系统_数据库与API详细设计.md)
- [Batch A：后端基础闭环实施计划](./docs/superpowers/plans/2026-08-06-backend-foundation.md)

下一阶段从市场 JD 数据中心开始：批量导入、数据源 Adapter、Raw JD、标准化 JD、清洗警告与 Catalog 初始骨架。爬虫管理、算法抽取和 Neo4j 发布不进入这一基础批次。
