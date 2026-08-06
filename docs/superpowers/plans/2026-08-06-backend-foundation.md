# Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可通过 Docker Compose 启动、支持三角色内部账号登录、受控文件读取、后台任务状态轮询和依赖健康检查的 Batch A 后端基础闭环。

**Architecture:** 在单个 `backend` Python 工程中实现 FastAPI 模块化单体，API 与 Celery Worker 共用 SQLAlchemy 模型和领域服务。PostgreSQL 保存用户、Session、审计、文件元数据和 Processing Run；Redis 只做 Celery Broker；Neo4j 在本批只接入健康检查，不写业务图谱。

**Tech Stack:** Python 3.12、FastAPI、Pydantic Settings、SQLAlchemy 2、Alembic、PostgreSQL 16 + pgvector、Celery、Redis 7、Neo4j 5、Argon2id、Docker Compose、pytest、HTTPX、Ruff、uv。

---

## 1. 计划边界

本计划是五个可独立验收批次中的第一个：

| 批次 | 交付闭环 | 本计划是否实现 |
| --- | --- | :---: |
| A | 工程、登录、文件、任务、健康检查 | 是 |
| B | 市场 JD 导入、Adapter、清洗、Catalog 骨架 | 否 |
| C | Algorithm/LLM、候选组合、审核、图谱发布 | 否 |
| D | Applicant 简历、推荐、差距和成长路径 | 否 |
| E | HR 项目、JD、候选导入和批量匹配 | 否 |

本批明确不创建 JD、Catalog、Resume、Recruitment、Match、Growth 或 Graph 业务表。文件模块只实现元数据、受控存储和读取能力；文件上传由 Batch B/D/E 的具体业务入口调用同一个 Storage Service，不增加无业务归属的通用上传接口。

## 2. 本批验收结果

完成后必须同时满足：

1. `docker compose up -d postgres redis neo4j` 后三个依赖健康。
2. `docker compose run --rm migrate` 可从空库升级到 `0004`。
3. `docker compose up -d api worker scheduler` 后 `/health/live` 返回 200，`/health/ready` 返回 200。
4. 初始 admin 可通过命令创建；admin 可创建 applicant、hr、admin 账号。
5. 三种账号都可登录；停用账号、过期 Session、错误密码和登录限流有稳定错误码。
6. 所有受 Cookie 保护的写接口验证 `X-CSRF-Token`。
7. 文件读取只能访问可见文件，路径不能逃逸 `FILE_STORAGE_ROOT`，预览和下载写访问日志。
8. Processing Run 可按权限查询、查看逐项错误、取消和重试；旧 Run 不被覆盖。
9. 所有 API 响应带 `X-Request-ID`；业务错误使用统一 JSON 结构。
10. `uv run ruff check .` 与 `uv run pytest` 全部通过。

## 3. 文件结构

本批结束时新增或修改以下文件。没有职责的目录不预建空壳。

```text
.
├── .env.example
├── .gitignore
├── compose.yaml
├── README.md
└── backend/
    ├── Dockerfile
    ├── alembic.ini
    ├── pyproject.toml
    ├── uv.lock
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       ├── 0001_extensions.py
    │       ├── 0002_identity.py
    │       ├── 0003_files.py
    │       └── 0004_processing.py
    ├── app/
    │   ├── __init__.py
    │   ├── main.py
    │   ├── worker.py
    │   ├── api/
    │   │   ├── dependencies.py
    │   │   └── router.py
    │   ├── core/
    │   │   ├── config.py
    │   │   ├── errors.py
    │   │   ├── logging.py
    │   │   ├── middleware.py
    │   │   └── security.py
    │   ├── infrastructure/
    │   │   ├── database.py
    │   │   ├── file_storage.py
    │   │   ├── neo4j.py
    │   │   └── redis.py
    │   ├── audit/
    │   │   ├── models.py
    │   │   └── service.py
    │   ├── auth/
    │   │   ├── models.py
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   └── service.py
    │   ├── files/
    │   │   ├── models.py
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   └── service.py
    │   ├── processing/
    │   │   ├── models.py
    │   │   ├── router.py
    │   │   ├── schemas.py
    │   │   ├── service.py
    │   │   └── tasks.py
    │   └── system/
    │       ├── router.py
    │       └── service.py
    ├── scripts/
    │   └── create_user.py
    └── tests/
        ├── conftest.py
        ├── test_admin_users.py
        ├── test_auth.py
        ├── test_database_constraints.py
        ├── test_errors.py
        ├── test_files.py
        ├── test_health.py
        └── test_processing_runs.py
```

## 4. 固定契约

### 4.1 API 与安全

- 业务 API 基础路径：`/api/v1`。
- Session Cookie：`session`，`HttpOnly=true`，`SameSite=Lax`，生产环境 `Secure=true`。
- CSRF Cookie：`csrf`，允许前端读取；客户端把相同值放入 `X-CSRF-Token`。
- Session 和 CSRF 在数据库中只保存 HMAC-SHA256，不保存明文。
- Session 绝对有效期 8 小时；`last_seen_at` 最多每 5 分钟更新一次。
- Session Token 和 CSRF Token 都由 `secrets.token_urlsafe(32)` 生成。
- 密码长度 8 到 128 字符，使用 Argon2id；不自行调整 Argon2 参数。
- 登录名保存原值，唯一比较值为 `username.strip().lower()`。
- 同一用户名或 IP 在 10 分钟内失败达到 10 次时返回 429。

### 4.2 Processing Run

```python
RUN_STATUSES = {
    "pending",
    "enqueue_failed",
    "running",
    "waiting_review",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
}

RETRYABLE_STATUSES = {"failed", "enqueue_failed"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
```

- `pending` 取消后直接变为 `cancelled`。
- `running` 或 `waiting_review` 取消后变为 `cancel_requested`。
- 终态取消是幂等读取，不创建新记录。
- 重试总是创建新 Run，并设置 `retry_of_run_id`；旧 Run 保持不变。
- 本批通过 `celery_app.send_task(f"app.{run_type}", args=[run_id])` 投递；Batch B/C/D/E 各自注册对应同名任务。
- 未注册或 Broker 不可用时，新 Run 保留并变为 `enqueue_failed`，不丢失业务记录。

### 4.3 文件访问

- 本批只允许 admin 访问任意文件，以及上传者访问 `status=uploaded` 的未绑定文件。
- `status=attached` 的业务所有权解析在创建 Resume、Import、Recruitment 资源时扩展；在扩展前普通用户不能仅凭 `uploaded_by_user_id` 读取 attached 文件。
- `storage_key` 必须是相对路径；解析后的绝对路径必须位于 `FILE_STORAGE_ROOT` 下。
- 使用 Starlette `FileResponse` 的原生 Range 支持，不另写分段下载器。

---

### Task 1: 创建可启动的 FastAPI 与 Docker Compose 骨架

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `compose.yaml`
- Create: `backend/pyproject.toml`
- Create: `backend/Dockerfile`
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: 写存活检查的失败测试**

```python
# backend/tests/test_health.py
from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_live_is_public_and_does_not_probe_dependencies() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行测试并确认它因应用尚不存在而失败**

Run: `cd backend && uv run pytest tests/test_health.py -q`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'app'`。

- [ ] **Step 3: 创建项目依赖与测试配置**

`backend/pyproject.toml` 使用以下内容：

```toml
[project]
name = "job-capability-graph-backend"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = [
  "alembic>=1.16,<2",
  "argon2-cffi>=25,<26",
  "asyncpg>=0.30,<1",
  "celery[redis]>=5.5,<6",
  "fastapi>=0.116,<1",
  "neo4j>=5.28,<6",
  "pydantic-settings>=2.10,<3",
  "python-multipart>=0.0.20,<1",
  "redis>=6,<7",
  "sqlalchemy[asyncio]>=2.0.41,<3",
  "uvicorn[standard]>=0.35,<1",
]

[dependency-groups]
dev = [
  "httpx>=0.28,<1",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.0,<2",
  "ruff>=0.12,<1",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

`backend/tests/conftest.py` 在导入应用前设置完整测试环境：

```python
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_BASE_URL", "http://test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://job_graph:job_graph@postgres:5432/job_graph_test"
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("NEO4J_URI", "bolt://neo4j:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "job_graph_dev")
os.environ.setdefault("FILE_STORAGE_ROOT", "/tmp/job-graph-tests")
os.environ.setdefault("SESSION_SECRET", "test-secret-at-least-32-characters")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("ALGORITHM_SERVICE_URL", "http://algorithm:8001")
```

Run: `cd backend && uv lock`

Expected: 创建 `backend/uv.lock`，依赖解析成功。

- [ ] **Step 4: 实现最小配置和存活接口**

```python
# backend/app/core/config.py
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "internal"]
    app_base_url: AnyHttpUrl
    database_url: str
    redis_url: str
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: SecretStr
    file_storage_root: Path
    session_secret: SecretStr = Field(min_length=32)
    session_ttl_seconds: int = Field(default=28_800, ge=300)
    cors_origins: list[str]
    algorithm_service_url: AnyHttpUrl

    @property
    def secure_cookie(self) -> bool:
        return self.app_env == "internal"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

```python
# backend/app/main.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(title="岗位能力图谱系统 API", version="0.1.0")

    @application.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
```

- [ ] **Step 5: 增加容器配置**

`backend/Dockerfile`：

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`compose.yaml` 只暴露 API；数据库端口仅为本机调试映射：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: job_graph
      POSTGRES_USER: job_graph
      POSTGRES_PASSWORD: job_graph_dev
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U job_graph -d job_graph"]
      interval: 3s
      timeout: 3s
      retries: 20
    ports: ["127.0.0.1:5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 20

  neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/job_graph_dev
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p job_graph_dev 'RETURN 1' >/dev/null"]
      interval: 5s
      timeout: 3s
      retries: 30
    ports: ["127.0.0.1:7474:7474", "127.0.0.1:7687:7687"]
    volumes: ["neo4j_data:/data"]

  api:
    build: ./backend
    env_file: .env
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      neo4j: {condition: service_healthy}
    ports: ["127.0.0.1:8000:8000"]
    volumes: ["app_files:/data/files"]

volumes:
  postgres_data:
  neo4j_data:
  app_files:
```

`.env.example`：

```dotenv
APP_ENV=local
APP_BASE_URL=http://localhost:8000
DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph
REDIS_URL=redis://redis:6379/0
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=job_graph_dev
FILE_STORAGE_ROOT=/data/files
SESSION_SECRET=replace-with-at-least-32-random-characters
SESSION_TTL_SECONDS=28800
CORS_ORIGINS=["http://localhost:3000"]
ALGORITHM_SERVICE_URL=http://algorithm:8001
```

Run: `test -f .env || cp .env.example .env`

Expected: 首次执行创建未被 Git 跟踪的本地 `.env`；已有 `.env` 时不覆盖。

`.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.py[cod]
backend/.coverage
backend/htmlcov/
```

- [ ] **Step 6: 验证最小应用**

Run: `cd backend && uv run ruff check . && uv run pytest tests/test_health.py -q`

Expected: Ruff 无错误，`1 passed`。

- [ ] **Step 7: 提交工程骨架**

```bash
git add .env.example .gitignore compose.yaml backend
git commit -m "build: bootstrap backend runtime"
```

---

### Task 2: 实现统一请求 ID、错误响应与 API Router

**Files:**
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/core/middleware.py`
- Create: `backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_errors.py`

- [ ] **Step 1: 写请求 ID 和错误结构测试**

```python
# backend/tests/test_errors.py
from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_request_id_is_preserved() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/testing/not-found", headers={"X-Request-ID": "req_test_123"}
        )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req_test_123"
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "资源不存在",
        "request_id": "req_test_123",
        "details": {},
    }


async def test_invalid_request_id_is_replaced() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/health/live", headers={"X-Request-ID": "contains spaces"}
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
```

- [ ] **Step 2: 运行测试并确认 404 仍是 FastAPI 默认结构**

Run: `cd backend && uv run pytest tests/test_errors.py -q`

Expected: FAIL，第一条断言收到 `{"detail":"Not Found"}`。

- [ ] **Step 3: 实现错误类型和处理器**

```python
# backend/app/core/errors.py
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(request: Request, code: str, message: str, details: Any) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request.state.request_id,
            "details": details,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                request,
                "VALIDATION_FAILED",
                "请求参数校验失败",
                jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "资源不存在" if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, code, message, {}),
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled request error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body(request, "INTERNAL_ERROR", "系统内部错误", {}),
        )
```

- [ ] **Step 4: 实现请求 ID 中间件和统一 Router**

```python
# backend/app/core/middleware.py
from contextvars import ContextVar
import re
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied
            if REQUEST_ID_PATTERN.fullmatch(supplied)
            else f"req_{uuid.uuid4().hex}"
        )
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)
```

```python
# backend/app/core/logging.py
import json
import logging
from datetime import UTC, datetime

from app.core.middleware import request_id_context


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
```

```python
# backend/app/api/router.py
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
```

修改 `create_app()`，安装顺序固定为 CORS、Request ID、错误处理器、Router：

```python
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    application = FastAPI(title="岗位能力图谱系统 API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    application.add_middleware(RequestIDMiddleware)
    install_error_handlers(application)
    application.include_router(api_router)

    @application.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return application
```

- [ ] **Step 5: 验证 HTTP 公共契约**

Run: `cd backend && uv run ruff check . && uv run pytest tests/test_errors.py -q`

Expected: `2 passed`。

- [ ] **Step 6: 提交公共 HTTP 契约**

```bash
git add backend/app backend/tests/test_errors.py
git commit -m "feat: add API request and error contracts"
```

---

### Task 3: 建立 PostgreSQL、Alembic 与 Batch A 数据约束

**Files:**
- Create: `backend/app/infrastructure/database.py`
- Create: `backend/app/auth/models.py`
- Create: `backend/app/audit/models.py`
- Create: `backend/app/files/models.py`
- Create: `backend/app/processing/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_extensions.py`
- Create: `backend/alembic/versions/0002_identity.py`
- Create: `backend/alembic/versions/0003_files.py`
- Create: `backend/alembic/versions/0004_processing.py`
- Create: `backend/tests/test_database_constraints.py`
- Modify: `compose.yaml`

- [ ] **Step 1: 写数据库约束测试**

测试必须真实连接 PostgreSQL，不使用 SQLite，因为本批使用 `INET`、`JSONB`、Partial Index 和 PostgreSQL Check Constraint。

```python
# backend/tests/test_database_constraints.py
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.processing.models import ProcessingRun


async def test_username_normalized_is_unique(db_session) -> None:
    db_session.add_all(
        [
            User(
                id=uuid4(), username="Demo", username_normalized="demo",
                password_hash="hash", display_name="A", role="applicant",
                password_changed_at=datetime.now(UTC),
            ),
            User(
                id=uuid4(), username="demo", username_normalized="demo",
                password_hash="hash", display_name="B", role="hr",
                password_changed_at=datetime.now(UTC),
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_processing_user_scope_requires_owner_id(db_session, user) -> None:
    db_session.add(
        ProcessingRun(
            id=uuid4(), run_type="test", subject_type="test",
            subject_id=uuid4(), created_by_user_id=user.id,
            owner_scope_type="user", owner_scope_id=None, status="pending",
            pipeline_version="test-v1", input_snapshot={}, result_summary={},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_session_expiry_must_follow_creation(db_session, user) -> None:
    from app.auth.models import AuthSession

    now = datetime.now(UTC)
    db_session.add(
        AuthSession(
            id=uuid4(), user_id=user.id, token_hash="a" * 64,
            csrf_token_hash="b" * 64, created_at=now,
            last_seen_at=now, expires_at=now - timedelta(seconds=1),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: 创建统一 Base、Engine 和 Session 依赖**

```python
# backend/app/infrastructure/database.py
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
```

- [ ] **Step 3: 实现四组模型**

创建 `users`、`auth_sessions`、`login_attempts`、`audit_logs`、`stored_files`、`file_access_logs`、`processing_runs`、`processing_errors`、`idempotency_records` 九张表。所有状态值使用 `String + CheckConstraint`，不得换成 PostgreSQL Enum。

以下声明是本批模型的完整字段和数据库级约束，不增加代码块以外的业务字段：

```python
# backend/app/auth/models.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CHAR, CheckConstraint, DateTime, ForeignKey,
    Index, String, Uuid, func, text, true,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class User(CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('applicant','hr','admin')", name="role"),
        CheckConstraint(
            "length(username_normalized) BETWEEN 3 AND 64", name="username_length"
        ),
        Index(
            "ix_users_active_role_created_at", "role", text("created_at DESC"),
            postgresql_where=text("is_active = true"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64))
    username_normalized: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthSession(CreatedAtMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(CHAR(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))


class LoginAttempt(CreatedAtMixin, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_username_created", "username_normalized", text("created_at DESC")),
        Index("ix_login_attempts_ip_created", "ip_address", text("created_at DESC")),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username_normalized: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    success: Mapped[bool] = mapped_column(Boolean)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str] = mapped_column(String(64))
```

```python
# backend/app/audit/models.py
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("outcome IN ('success','denied','failed')", name="outcome"),
        Index("ix_audit_logs_actor_created", "actor_user_id", text("created_at DESC")),
        Index(
            "ix_audit_logs_resource_created",
            "resource_type", "resource_id", text("created_at DESC"),
        ),
        Index("ix_audit_logs_action_created", "action", text("created_at DESC")),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str | None] = mapped_column(String(64))
    processing_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    ip_address: Mapped[str | None] = mapped_column(INET)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
```

```python
# backend/app/files/models.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, CHAR, CheckConstraint, DateTime, ForeignKey,
    Index, String, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class StoredFile(CreatedAtMixin, Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint(
            "category IN ('market_jd','catalog','resume','jd','portfolio','other')",
            name="category",
        ),
        CheckConstraint(
            "scan_status IN ('pending','clean','rejected','not_required')",
            name="scan_status",
        ),
        CheckConstraint(
            "status IN ('uploaded','attached','archived','deleted')", name="status"
        ),
        Index("ix_stored_files_uploader_created", "uploaded_by_user_id", text("created_at DESC")),
        Index("ix_stored_files_hash_size", "sha256", "size_bytes"),
        Index(
            "ix_stored_files_expiring_unattached", "expires_at",
            postgresql_where=text("status = 'uploaded' AND expires_at IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    media_type: Mapped[str] = mapped_column(String(150))
    extension: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    category: Mapped[str] = mapped_column(String(50))
    scan_status: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileAccessLog(CreatedAtMixin, Base):
    __tablename__ = "file_access_logs"
    __table_args__ = (
        CheckConstraint("action IN ('preview','download')", name="action"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("stored_files.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(64))
```

```python
# backend/app/processing/models.py
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CHAR, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, Uuid, false, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


PROCESSING_SCOPE_CHECK = """
(owner_scope_type = 'admin_global' AND owner_scope_id IS NULL)
OR (owner_scope_type IN ('user','recruitment_project') AND owner_scope_id IS NOT NULL)
"""


class ProcessingRun(CreatedAtMixin, Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint(
            "owner_scope_type IN ('user','recruitment_project','admin_global')",
            name="owner_scope_type",
        ),
        CheckConstraint(PROCESSING_SCOPE_CHECK, name="owner_scope_id"),
        CheckConstraint(
            "status IN ('pending','enqueue_failed','running','waiting_review',"
            "'cancel_requested','completed','failed','cancelled')",
            name="status",
        ),
        CheckConstraint("total_count >= 0", name="total_count"),
        CheckConstraint(
            "processed_count >= 0 AND processed_count <= total_count",
            name="processed_count",
        ),
        CheckConstraint("success_count >= 0 AND failed_count >= 0", name="result_counts"),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="progress"),
        CheckConstraint("attempt_count >= 0 AND max_attempts >= 1", name="attempts"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_type: Mapped[str] = mapped_column(String(60))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    retry_of_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_runs.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    owner_scope_type: Mapped[str] = mapped_column(String(30))
    owner_scope_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    current_stage: Mapped[str | None] = mapped_column(String(60))
    pipeline_version: Mapped[str] = mapped_column(String(80))
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    total_count: Mapped[int] = mapped_column(default=0, server_default="0")
    processed_count: Mapped[int] = mapped_column(default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(default=0, server_default="0")
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=false())
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(default=1, server_default="1")
    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    result_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessingError(Base):
    __tablename__ = "processing_errors"
    __table_args__ = (
        Index("ix_processing_errors_run_occurred", "run_id", "occurred_at"),
        Index("ix_processing_errors_run_stage_retryable", "run_id", "stage", "retryable"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("processing_runs.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(60))
    item_type: Mapped[str | None] = mapped_column(String(50))
    item_id: Mapped[UUID | None] = mapped_column(Uuid)
    item_key: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IdempotencyRecord(CreatedAtMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "endpoint_key", "idempotency_key", name="uq_idempotency_scope_key"
        ),
        CheckConstraint("state IN ('processing','completed','failed')", name="state"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    endpoint_key: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

`0004_processing.py` 额外执行 `audit_logs.processing_run_id -> processing_runs.id` 的 FK；downgrade 先删除该 FK，再删除 Processing 表。

- [ ] **Step 4: 初始化 Alembic 并生成四个可独立回滚的 Migration**

Run:

```bash
cd backend
uv run alembic init alembic
uv run alembic revision -m "enable postgres extensions" --rev-id 0001
uv run alembic revision --autogenerate -m "create identity tables" --rev-id 0002
uv run alembic revision --autogenerate -m "create file tables" --rev-id 0003
uv run alembic revision --autogenerate -m "create processing tables" --rev-id 0004
```

`0001_extensions.py` 的 upgrade/downgrade 固定为：

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
```

在生成每个 autogenerate Migration 时，`target_metadata` 只导入该步已存在的模型；生成后恢复 `env.py` 导入全部 Batch A 模型。最终 `alembic upgrade head` 必须按 `0001 -> 0002 -> 0003 -> 0004` 创建九张表。

- [ ] **Step 5: 增加测试数据库 Fixture**

`backend/tests/conftest.py` 增加事务隔离 Fixture；每个测试在同一连接的事务中执行，结束后回滚：

```python
import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await session.close()
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def user(db_session):
    from datetime import UTC, datetime
    from uuid import uuid4
    from app.auth.models import User

    value = User(
        id=uuid4(), username="fixture", username_normalized="fixture",
        password_hash="hash", display_name="Fixture", role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value
```

从 Task 4 开始，同一 `conftest.py` 增加真实应用依赖覆盖和登录客户端包装，测试中出现的 `admin_client.user_id`、`authenticated_client.db` 和 `.cookies` 都由该类型提供：

```python
from dataclasses import dataclass
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.infrastructure.database import get_db
from app.main import app


@dataclass
class AuthenticatedClient:
    http: AsyncClient
    user: User
    db: AsyncSession

    @property
    def user_id(self):
        return self.user.id

    @property
    def cookies(self):
        return self.http.cookies

    def __getattr__(self, name: str) -> Any:
        return getattr(self.http, name)


@pytest_asyncio.fixture
async def client(db_session):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    app.dependency_overrides.clear()
```

Task 4 的认证 Fixture 固定采用以下数据，不从 Seed 脚本读取：

| Fixture | 数据 |
| --- | --- |
| `seeded_hr` | `hr_demo` / `correct-password` / role=`hr` |
| `admin_client` | `admin_test` / role=`admin`，登录后包装为 `AuthenticatedClient` |
| `hr_client` | `hr_test` / role=`hr`，登录后包装为 `AuthenticatedClient` |
| `authenticated_client` | `applicant_test` / role=`applicant`，登录后包装为 `AuthenticatedClient` |
| `expired_session_cookie` | 创建已过期 `AuthSession`，返回对应明文 Cookie Token |
| `nine_failed_attempts` | 为 `hr_demo` 插入最近 10 分钟内 9 条失败 `LoginAttempt` |

- [ ] **Step 6: 增加 migrate Service 并验证升级、降级、再升级**

`compose.yaml` 增加：

```yaml
  migrate:
    build: ./backend
    env_file: .env
    command: ["uv", "run", "alembic", "upgrade", "head"]
    depends_on:
      postgres: {condition: service_healthy}
```

同时把 `api` 对 PostgreSQL 的直接启动依赖替换为 Migration 完成依赖：

```yaml
    depends_on:
      migrate: {condition: service_completed_successfully}
      redis: {condition: service_healthy}
      neo4j: {condition: service_healthy}
```

Run:

```bash
docker compose up -d postgres
docker compose exec postgres createdb -U job_graph job_graph_test
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test migrate
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test migrate uv run alembic downgrade base
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test migrate
docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://job_graph:job_graph_dev@postgres:5432/job_graph_test api uv run pytest tests/test_database_constraints.py -q
```

Expected: Migration 三条命令退出码均为 0，约束测试 `3 passed`。

- [ ] **Step 7: 提交数据库基础**

```bash
git add backend/app backend/alembic backend/alembic.ini backend/tests compose.yaml
git commit -m "feat: add foundation database schema"
```

---

### Task 4: 实现 Session 登录、CSRF 与管理员账号管理

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/app/audit/service.py`
- Create: `backend/app/auth/schemas.py`
- Create: `backend/app/auth/service.py`
- Create: `backend/app/auth/router.py`
- Create: `backend/app/api/dependencies.py`
- Create: `backend/scripts/create_user.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_auth.py`
- Create: `backend/tests/test_admin_users.py`

- [ ] **Step 1: 写登录、Session、CSRF 和限流失败测试**

```python
# backend/tests/test_auth.py（核心场景）
async def test_login_sets_opaque_session_and_csrf(client, seeded_hr) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": " hr_demo ", "password": "correct-password"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "hr"
    assert response.cookies["session"]
    assert response.cookies["csrf"] == response.json()["data"]["csrf_token"]
    assert "HttpOnly" in response.headers["set-cookie"]


async def test_protected_write_rejects_missing_csrf(authenticated_client) -> None:
    response = await authenticated_client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_expired_session_is_rejected(client, expired_session_cookie) -> None:
    client.cookies.set("session", expired_session_cookie)
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


async def test_tenth_recent_failure_is_rate_limited(client, nine_failed_attempts) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"username": "hr_demo", "password": "wrong"}
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LOGIN_RATE_LIMITED"
```

```python
# backend/tests/test_admin_users.py（核心场景）
async def test_only_admin_can_create_user(admin_client, hr_client) -> None:
    payload = {
        "username": "applicant_demo", "display_name": "演示应聘者",
        "role": "applicant", "initial_password": "temporary-password",
    }
    denied = await hr_client.post(
        "/api/v1/admin/users", json=payload,
        headers={"X-CSRF-Token": hr_client.cookies["csrf"]},
    )
    created = await admin_client.post(
        "/api/v1/admin/users", json=payload,
        headers={"X-CSRF-Token": admin_client.cookies["csrf"]},
    )
    assert denied.status_code == 403
    assert created.status_code == 201
    assert "initial_password" not in created.text


async def test_last_active_admin_cannot_be_disabled(admin_client) -> None:
    response = await admin_client.patch(
        f"/api/v1/admin/users/{admin_client.user_id}",
        json={"is_active": False},
        headers={"X-CSRF-Token": admin_client.cookies["csrf"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"
```

- [ ] **Step 2: 实现最小安全原语**

```python
# backend/app/core/security.py
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
```

- [ ] **Step 3: 定义请求响应 Schema**

`auth/schemas.py` 必须定义并限制：

```python
class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["applicant", "hr", "admin"]
    initial_password: str = Field(min_length=8, max_length=128)


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["applicant", "hr", "admin"] | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
```

响应模型不得包含 `password_hash`、`token_hash` 或 `csrf_token_hash`。

- [ ] **Step 4: 实现 Auth Service 的事务规则**

`auth/service.py` 实现以下精确接口；函数体按紧随其后的事务规则完成，不保留空函数：

| 函数 | 参数 | 返回 |
| --- | --- | --- |
| `login` | `db, username, password, request_id, ip_address, user_agent` | `tuple[User, str, str]`，依次为用户、明文 Session Token、明文 CSRF Token |
| `resolve_session` | `db, token` | `tuple[User, AuthSession]` |
| `revoke_session` | `db, session` | `None` |
| `revoke_all_sessions` | `db, user_id` | `None` |
| `ensure_csrf` | `db, session, csrf_cookie` | 可复用或新生成的明文 CSRF Token |
| `create_user` | `db, actor, payload` | `User` |
| `update_user` | `db, actor, target, payload` | `User` |
| `reset_password` | `db, actor, target, new_password` | `User` |

实现顺序：

1. 登录前查询最近 10 分钟同用户名或同 IP 的失败次数。
2. 达到 9 次时，本次错误密码写第 10 条失败记录并返回 429。
3. 成功时写 Login Attempt、更新 `last_login_at`、创建 Session、写 Audit Log，在一个事务中提交。
4. 无用户与密码错误都返回 `INVALID_CREDENTIALS`。
5. 已匹配但停用的用户写 `failure_code=inactive` 并返回 `ACCOUNT_INACTIVE`。
6. `resolve_session` 区分缺少 Cookie 的 `AUTH_REQUIRED` 与已有但过期/撤销的 `SESSION_EXPIRED`。
7. `update_user` 对停用或降级 admin 使用 `SELECT FOR UPDATE` 锁定有效 admin 集合，确认至少还有另一个有效 admin。
8. 停用、降级或重置密码时，在同一事务把目标用户全部有效 Session 的 `revoked_at` 设置为当前时间。

- [ ] **Step 5: 实现认证与权限依赖**

```python
# backend/app/api/dependencies.py
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession, User
from app.auth.service import resolve_session
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import constant_time_equal, token_digest
from app.infrastructure.database import get_db

DB = Annotated[AsyncSession, Depends(get_db)]


async def current_identity(
    db: DB, session: Annotated[str | None, Cookie()] = None
) -> tuple[User, AuthSession]:
    return await resolve_session(db, session)


Identity = Annotated[tuple[User, AuthSession], Depends(current_identity)]


async def require_admin(identity: Identity) -> User:
    user, _ = identity
    if user.role != "admin":
        raise APIError(403, "ROLE_NOT_ALLOWED", "当前角色不能执行此操作")
    return user


Admin = Annotated[User, Depends(require_admin)]


async def require_csrf(
    identity: Identity,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    _, auth_session = identity
    if not csrf_header:
        raise APIError(403, "CSRF_VALIDATION_FAILED", "CSRF 校验失败")
    digest = token_digest(
        csrf_header, get_settings().session_secret.get_secret_value()
    )
    if not constant_time_equal(digest, auth_session.csrf_token_hash):
        raise APIError(403, "CSRF_VALIDATION_FAILED", "CSRF 校验失败")


CSRF = Annotated[None, Depends(require_csrf)]
```

- [ ] **Step 6: 实现 Router 和 Cookie 行为**

`auth/router.py` 注册：

```text
POST /auth/login
POST /auth/logout
POST /auth/logout-all
GET  /auth/me
POST /admin/users
GET  /admin/users
GET  /admin/users/{user_id}
PATCH /admin/users/{user_id}
POST /admin/users/{user_id}/reset-password
```

登录成功时：

```python
response.set_cookie(
    "session", session_token, httponly=True, secure=settings.secure_cookie,
    samesite="lax", max_age=settings.session_ttl_seconds, path="/",
)
response.set_cookie(
    "csrf", csrf_token, httponly=False, secure=settings.secure_cookie,
    samesite="lax", max_age=settings.session_ttl_seconds, path="/",
)
```

所有 POST/PATCH 管理接口依赖 `CSRF`；所有 `/admin` 接口依赖 `Admin`。列表参数固定为 `page>=1`、`1<=page_size<=100`、`role`、`is_active`、`q`、`sort` 白名单和 `order`。

- [ ] **Step 7: 增加可重复执行的账号创建命令**

`scripts/create_user.py` 接受 `--username`、`--display-name`、`--role`，密码只通过 `getpass.getpass()` 交互输入；存在同名用户时退出码为 2，不覆盖密码。首个用户只允许创建 `admin`，其 `created_by_user_id` 为空。

Run:

```bash
docker compose run --rm api uv run python scripts/create_user.py \
  --username admin --display-name 系统管理员 --role admin
```

Expected: 交互输入两次密码后输出新用户 UUID，不回显密码。

- [ ] **Step 8: 验证 Auth 和 Admin API**

Run: `docker compose run --rm api uv run pytest tests/test_auth.py tests/test_admin_users.py -q`

Expected: 所有登录、CSRF、限流、角色、最后 admin 和 Session 撤销测试通过。

- [ ] **Step 9: 提交身份闭环**

```bash
git add backend/app backend/scripts backend/tests
git commit -m "feat: add session auth and admin users"
```

---

### Task 5: 实现安全文件存储和受控读取

**Files:**
- Create: `backend/app/infrastructure/file_storage.py`
- Create: `backend/app/files/schemas.py`
- Create: `backend/app/files/service.py`
- Create: `backend/app/files/router.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_files.py`

- [ ] **Step 1: 写路径逃逸、权限和审计失败测试**

```python
# backend/tests/test_files.py（核心场景）
async def test_uploader_can_preview_unattached_file(
    authenticated_client, stored_unattached_file
) -> None:
    response = await authenticated_client.get(
        f"/api/v1/files/{stored_unattached_file.id}/content"
    )
    assert response.status_code == 200
    assert response.content == b"safe file"
    assert response.headers["accept-ranges"] == "bytes"


async def test_other_user_sees_not_found(other_client, stored_unattached_file) -> None:
    response = await other_client.get(f"/api/v1/files/{stored_unattached_file.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_OWNED"


async def test_attached_file_is_not_owned_by_original_uploader(
    authenticated_client, attached_file
) -> None:
    response = await authenticated_client.get(f"/api/v1/files/{attached_file.id}")
    assert response.status_code == 404


async def test_storage_key_cannot_escape_root(file_storage, tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid storage key"):
        file_storage.resolve("../outside.txt")


async def test_download_creates_access_log(
    authenticated_client, stored_unattached_file, db_session
) -> None:
    response = await authenticated_client.get(
        f"/api/v1/files/{stored_unattached_file.id}/download"
    )
    assert response.status_code == 200
    log = await db_session.scalar(
        select(FileAccessLog).where(FileAccessLog.file_id == stored_unattached_file.id)
    )
    assert log.action == "download"
```

- [ ] **Step 2: 实现受控路径解析**

```python
# backend/app/infrastructure/file_storage.py
from pathlib import Path


class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, storage_key: str) -> Path:
        if Path(storage_key).is_absolute():
            raise ValueError("invalid storage key")
        path = (self.root / storage_key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return path

    def exists(self, storage_key: str) -> bool:
        return self.resolve(storage_key).is_file()
```

文件写入的流式校验与原子移动在首个上传入口 Batch B 实现；本批不增加只能被测试调用的通用上传 API。

- [ ] **Step 3: 实现文件可见性和审计**

`files/service.py` 暴露：

```python
async def get_visible_file(
    db: AsyncSession, file_id: UUID, actor: User
) -> StoredFile:
    file = await db.get(StoredFile, file_id)
    if file is None or file.status in {"archived", "deleted"}:
        raise APIError(404, "FILE_NOT_FOUND", "文件不存在")
    visible = actor.role == "admin" or (
        file.status == "uploaded" and file.uploaded_by_user_id == actor.id
    )
    if not visible:
        raise APIError(404, "RESOURCE_NOT_OWNED", "文件不存在")
    return file


async def log_access(
    db: AsyncSession, file: StoredFile, actor: User,
    action: Literal["preview", "download"], request_id: str,
) -> None:
    db.add(FileAccessLog(
        id=uuid4(), file_id=file.id, user_id=actor.id,
        action=action, request_id=request_id,
    ))
    await db.commit()
```

- [ ] **Step 4: 实现三个读取接口**

```python
@router.get("/{file_id}")
async def metadata(file_id: UUID, db: DB, identity: Identity) -> dict:
    actor, _ = identity
    file = await get_visible_file(db, file_id, actor)
    return {"data": FileResponseSchema.model_validate(file).model_dump()}


@router.get("/{file_id}/content")
async def content(
    file_id: UUID, request: Request, db: DB, identity: Identity
) -> FileResponse:
    actor, _ = identity
    file = await get_visible_file(db, file_id, actor)
    path = storage.resolve(file.storage_key)
    if not path.is_file():
        raise APIError(404, "FILE_CONTENT_MISSING", "文件内容不存在")
    await log_access(db, file, actor, "preview", request.state.request_id)
    return FileResponse(path, media_type=file.media_type)


@router.get("/{file_id}/download")
async def download(
    file_id: UUID, request: Request, db: DB, identity: Identity
) -> FileResponse:
    actor, _ = identity
    file = await get_visible_file(db, file_id, actor)
    path = storage.resolve(file.storage_key)
    if not path.is_file():
        raise APIError(404, "FILE_CONTENT_MISSING", "文件内容不存在")
    await log_access(db, file, actor, "download", request.state.request_id)
    return FileResponse(path, media_type=file.media_type, filename=file.original_name)
```

`preview_supported` 只对 PDF、纯文本、常见图片和浏览器可播放视频返回 `true`；Office 和 ZIP 返回 `false`，但仍可下载。

- [ ] **Step 5: 验证文件安全边界**

Run: `docker compose run --rm api uv run pytest tests/test_files.py -q`

Expected: 路径、权限、Range、Content-Disposition 和 Access Log 测试全部通过。

- [ ] **Step 6: 提交文件读取闭环**

```bash
git add backend/app backend/tests/test_files.py
git commit -m "feat: add controlled file access"
```

---

### Task 6: 实现 Processing Run 查询、取消、重试和 Celery 基础

**Files:**
- Create: `backend/app/worker.py`
- Create: `backend/app/processing/schemas.py`
- Create: `backend/app/processing/service.py`
- Create: `backend/app/processing/router.py`
- Create: `backend/app/processing/tasks.py`
- Modify: `backend/app/api/router.py`
- Modify: `compose.yaml`
- Create: `backend/tests/test_processing_runs.py`

- [ ] **Step 1: 写所有权、取消和重试失败测试**

```python
# backend/tests/test_processing_runs.py（核心场景）
async def test_user_only_lists_own_runs(authenticated_client, own_run, other_run) -> None:
    response = await authenticated_client.get("/api/v1/processing-runs")
    ids = {item["id"] for item in response.json()["data"]}
    assert str(own_run.id) in ids
    assert str(other_run.id) not in ids


async def test_cancel_pending_run_is_immediate(
    authenticated_client, pending_run
) -> None:
    response = await authenticated_client.post(
        f"/api/v1/processing-runs/{pending_run.id}/cancel",
        headers={"X-CSRF-Token": authenticated_client.cookies["csrf"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"


async def test_cancel_running_run_is_cooperative(
    authenticated_client, running_run
) -> None:
    response = await authenticated_client.post(
        f"/api/v1/processing-runs/{running_run.id}/cancel",
        headers={"X-CSRF-Token": authenticated_client.cookies["csrf"]},
    )
    assert response.status_code == 202
    assert response.json()["data"]["status"] == "cancel_requested"


async def test_retry_creates_new_run_without_mutating_old(
    authenticated_client, failed_run, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.processing.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="celery-test-id"),
    )
    response = await authenticated_client.post(
        f"/api/v1/processing-runs/{failed_run.id}/retry",
        headers={"X-CSRF-Token": authenticated_client.cookies["csrf"]},
    )
    assert response.status_code == 202
    assert response.json()["data"]["retry_of_run_id"] == str(failed_run.id)
    await authenticated_client.db.refresh(failed_run)
    assert failed_run.status == "failed"
```

- [ ] **Step 2: 实现 Run 可见性查询**

`processing/service.py` 的所有查询先应用同一作用域条件：

```python
def visible_run_predicate(actor: User):
    if actor.role == "admin":
        return true()
    if actor.role == "applicant":
        return and_(
            ProcessingRun.owner_scope_type == "user",
            ProcessingRun.owner_scope_id == actor.id,
        )
    return and_(
        ProcessingRun.owner_scope_type == "user",
        ProcessingRun.owner_scope_id == actor.id,
    )
```

本批 HR 只能看 `owner_scope_type=user` 且属于自己的 Run；不存在 Recruitment Project 表时不伪造项目所有权。

- [ ] **Step 3: 实现状态动作**

```python
async def cancel_run(db: AsyncSession, run: ProcessingRun) -> tuple[ProcessingRun, int]:
    if run.status == "pending":
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        status_code = 200
    elif run.status in {"running", "waiting_review"}:
        run.status = "cancel_requested"
        run.cancel_requested = True
        status_code = 202
    else:
        status_code = 200
    await db.commit()
    await db.refresh(run)
    return run, status_code


async def retry_run(
    db: AsyncSession, old: ProcessingRun, actor: User
) -> ProcessingRun:
    if old.status not in {"failed", "enqueue_failed"}:
        raise APIError(409, "RUN_NOT_RETRYABLE", "当前任务状态不能重试")
    new = ProcessingRun(
        id=uuid4(), run_type=old.run_type, subject_type=old.subject_type,
        subject_id=old.subject_id, retry_of_run_id=old.id,
        created_by_user_id=actor.id, owner_scope_type=old.owner_scope_type,
        owner_scope_id=old.owner_scope_id, status="pending",
        pipeline_version=old.pipeline_version, max_attempts=old.max_attempts,
        input_snapshot=old.input_snapshot, result_summary={},
    )
    db.add(new)
    await db.commit()
    try:
        result = celery_app.send_task(f"app.{new.run_type}", args=[str(new.id)])
        new.celery_task_id = result.id
        new.enqueued_at = datetime.now(UTC)
    except Exception:
        new.status = "enqueue_failed"
        new.error_code = "TASK_ENQUEUE_FAILED"
        new.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    await db.refresh(new)
    return new
```

`retry_run` 捕获投递异常后不得删除新 Run；日志记录异常类型和 Request ID，但不把 Redis URL 写入响应。

- [ ] **Step 4: 实现六个 Processing API**

```text
GET  /api/v1/processing-runs
GET  /api/v1/processing-runs/{run_id}
GET  /api/v1/processing-runs/{run_id}/errors
GET  /api/v1/processing-runs/{run_id}/result
POST /api/v1/processing-runs/{run_id}/retry
POST /api/v1/processing-runs/{run_id}/cancel
```

- 列表筛选白名单：`run_type`、`status`、`subject_type`、`created_from`、`created_to`。
- 列表固定 `created_at desc`，页码参数范围与公共契约一致。
- `/errors` 固定 `occurred_at asc`。
- `/result` 仅在 `completed`/`waiting_review` 且 `result_summary` 有链接时返回；其他状态返回 `409 RUN_RESULT_NOT_READY`。
- 他人 Run 统一返回 404，不暴露其存在。
- `retry` 和 `cancel` 依赖 `CSRF` 并写 Audit Log。

- [ ] **Step 5: 创建 Celery 应用和维护任务**

```python
# backend/app/worker.py
from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("job_graph", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    timezone="UTC",
    beat_schedule={
        "redispatch-pending-runs": {
            "task": "app.redispatch_pending_runs", "schedule": 60.0,
        },
        "mark-stale-runs": {
            "task": "app.mark_stale_runs", "schedule": 60.0,
        },
        "clean-expired-sessions-hourly": {
            "task": "app.clean_expired_sessions", "schedule": 3600.0,
        },
        "clean-unattached-files-daily": {
            "task": "app.clean_unattached_files", "schedule": 86400.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.processing"])
```

`processing/tasks.py` 注册四个维护任务。任务函数只建立 Session 并调用领域 Service：

- `redispatch_pending_runs`：扫描 `pending/enqueue_failed` 且未成功投递的 Run，按原 `run_type` 再投递；成功后写 `celery_task_id/enqueued_at`。
- `mark_stale_runs`：把 `status=running` 且 `heartbeat_at < now()-5 minutes` 的 Run 标为 `failed`，错误码为 `WORKER_HEARTBEAT_STALE`，同时写一条可重试 Processing Error。
- `clean_expired_sessions`：删除已过期或已撤销 Session。
- `clean_unattached_files`：只处理 `status=uploaded AND expires_at < now()`；先安全删除文件，再删除元数据；单个文件失败时记录错误并继续下一项。

- [ ] **Step 6: 增加 Worker 和 Scheduler 服务**

```yaml
  worker:
    build: ./backend
    env_file: .env
    command: ["uv", "run", "celery", "-A", "app.worker:celery_app", "worker", "-l", "INFO"]
    depends_on:
      migrate: {condition: service_completed_successfully}
      redis: {condition: service_healthy}
    volumes: ["app_files:/data/files"]

  scheduler:
    build: ./backend
    env_file: .env
    command: ["uv", "run", "celery", "-A", "app.worker:celery_app", "beat", "-l", "INFO"]
    depends_on:
      migrate: {condition: service_completed_successfully}
      redis: {condition: service_healthy}
```

- [ ] **Step 7: 验证任务 API 与 Celery 配置**

Run:

```bash
docker compose run --rm api uv run pytest tests/test_processing_runs.py -q
docker compose config -q
docker compose up -d worker scheduler
docker compose ps
```

Expected: Processing 测试全通过；Compose 配置有效；worker 和 scheduler 状态为 running。

- [ ] **Step 8: 提交任务闭环**

```bash
git add backend/app backend/tests/test_processing_runs.py compose.yaml
git commit -m "feat: add processing run lifecycle"
```

---

### Task 7: 实现 Readiness 和管理员依赖诊断

**Files:**
- Create: `backend/app/infrastructure/redis.py`
- Create: `backend/app/infrastructure/neo4j.py`
- Create: `backend/app/system/service.py`
- Create: `backend/app/system/router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/tests/test_health.py`

- [ ] **Step 1: 写必需依赖与降级依赖测试**

```python
# backend/tests/test_health.py（追加）
async def test_ready_succeeds_when_required_dependencies_are_ok(
    client, healthy_dependencies
) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"]["algorithm_service"] == "degraded"


async def test_ready_fails_when_postgres_is_down(client, failed_postgres) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


async def test_dependency_details_require_admin(admin_client, hr_client) -> None:
    denied = await hr_client.get("/api/v1/admin/system/dependencies")
    allowed = await admin_client.get("/api/v1/admin/system/dependencies")
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert "postgresql" in allowed.json()["data"]["dependencies"]
```

- [ ] **Step 2: 实现四个并发探测函数**

`system/service.py` 使用 `asyncio.gather()` 并对每个探测设置 2 秒超时：

```python
async def probe_postgres() -> DependencyStatus:
    started = monotonic()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_redis() -> DependencyStatus:
    started = monotonic()
    await redis_client.ping()
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_neo4j() -> DependencyStatus:
    started = monotonic()
    await neo4j_driver.verify_connectivity()
    return DependencyStatus("ok", elapsed_ms(started))


async def probe_file_volume() -> DependencyStatus:
    started = monotonic()
    root = get_settings().file_storage_root
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".health-{uuid4().hex}"
    probe.write_bytes(b"ok")
    probe.unlink()
    return DependencyStatus("ok", elapsed_ms(started))
```

Algorithm Service 只调用 `GET /health`，失败映射为 `degraded`，不阻止 Ready。LLM API 本批不主动探测。

- [ ] **Step 3: 实现公共健康接口和 admin 诊断**

```text
GET /health/live
GET /health/ready
GET /api/v1/admin/system/dependencies
GET /api/v1/admin/system/versions
```

- `/health/ready` 仅返回依赖名称和 `ok/degraded/down`，不返回主机、端口、异常文本或凭证。
- PostgreSQL、Redis、Neo4j、File Volume 任一 `down` 时返回统一 503。
- admin dependencies 增加毫秒延迟、Pending/Running/Stale Run 数和 Redis Celery 队列长度。
- versions 返回 `api_version=0.1.0`、当前 Alembic Revision；尚无 Prompt、Model、Catalog、Graph 和 Weight 版本时返回 `null`，不伪造版本。

- [ ] **Step 4: 用 lifespan 关闭连接**

`main.py` 使用 `asynccontextmanager`，进程关闭时依次执行：

```python
await engine.dispose()
await redis_client.aclose()
await neo4j_driver.close()
```

- [ ] **Step 5: 验证健康检查**

Run:

```bash
docker compose run --rm api uv run pytest tests/test_health.py -q
docker compose up -d api
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Expected: 测试全通过，两个 curl 都返回 200；Ready JSON 中四个必需依赖为 `ok`。

- [ ] **Step 6: 提交健康诊断**

```bash
git add backend/app backend/tests/test_health.py
git commit -m "feat: add dependency health checks"
```

---

### Task 8: 完成 Batch A 集成验收和运行文档

**Files:**
- Modify: `README.md`
- Create: `backend/tests/test_batch_a_flow.py`

- [ ] **Step 1: 写真实 HTTP 闭环测试**

`test_batch_a_flow.py` 必须在真实 PostgreSQL 上依次执行：

```python
async def test_admin_creates_hr_and_hr_reads_own_run(client, seeded_admin) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-test-password"},
    )
    csrf = login.json()["data"]["csrf_token"]
    created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "hr_flow", "display_name": "闭环 HR",
            "role": "hr", "initial_password": "hr-test-password",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201

    await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
    )
    hr_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "hr_flow", "password": "hr-test-password"},
    )
    assert hr_login.status_code == 200
    assert hr_login.json()["data"]["role"] == "hr"

    runs = await client.get("/api/v1/processing-runs")
    assert runs.status_code == 200
    assert runs.json()["data"] == []
```

同一文件增加 applicant 无法访问 admin_global Run、HR 不能进入 admin system details、logout 后 Session 失效三个断言。

- [ ] **Step 2: 更新 README 为可复制运行手册**

README 增加以下准确命令：

```bash
cp .env.example .env
docker compose up -d postgres redis neo4j
docker compose run --rm migrate
docker compose run --rm api uv run python scripts/create_user.py \
  --username admin --display-name 系统管理员 --role admin
docker compose up -d api worker scheduler
curl http://127.0.0.1:8000/health/ready
```

同时列出：API 文档 `http://127.0.0.1:8000/docs`、停止命令 `docker compose down`、保留数据的默认行为，以及只有明确需要清空本地演示数据时才执行 `docker compose down -v`。

- [ ] **Step 3: 运行完整质量门禁**

Run:

```bash
docker compose config -q
docker compose run --rm migrate
docker compose run --rm api uv run ruff check .
docker compose run --rm api uv run pytest -q
docker compose up -d api worker scheduler
docker compose ps
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
git diff --check
```

Expected:

- Compose 配置退出码 0。
- Migration 到 `0004`。
- Ruff 无错误。
- 全部测试通过。
- postgres、redis、neo4j、api、worker、scheduler 全部运行。
- 两个健康接口返回 200。
- `git diff --check` 无输出。

- [ ] **Step 4: 执行人工安全检查**

依次确认：

1. `.env` 未被 Git 跟踪。
2. API 响应和日志没有密码、Session Token、CSRF Token 哈希、连接字符串。
3. OpenAPI 中没有公开注册接口和普通文件上传接口。
4. applicant、hr、admin 三种账号权限符合矩阵。
5. `docker compose down` 后重新启动，PostgreSQL、Neo4j 和 File Volume 数据仍存在。

- [ ] **Step 5: 提交 Batch A**

```bash
git add README.md backend/tests/test_batch_a_flow.py
git commit -m "docs: add Batch A runbook and acceptance flow"
```

## 5. 需求追踪

| 已确认设计要求 | 负责 Task | 验收证据 |
| --- | ---: | --- |
| FastAPI 模块化单体 | 1、2 | `/health/live` 与 OpenAPI |
| PostgreSQL + pgvector | 3 | `0001` 扩展与 `0002-0004` 表 |
| 三种角色、admin 创建账号 | 4 | Auth/Admin API 测试 |
| Argon2id、不透明 Session、CSRF | 4 | Security 与 Auth 测试 |
| 统一错误、Request ID、CORS | 2 | HTTP 契约测试 |
| 本地 Volume + 文件元数据 | 3、5 | 文件权限与路径测试 |
| PostgreSQL 是任务状态源 | 3、6 | Processing Run 生命周期测试 |
| HTTP 轮询 | 6 | GET Processing Run API |
| Celery + Redis | 6 | Worker、Beat 和投递测试 |
| Neo4j 已接入但不写未审核数据 | 7 | 只做连接健康检查 |
| Docker Compose 内部部署 | 1、8 | Compose 集成门禁 |

## 6. 后续计划入口

Batch A 合并并通过完整门禁后，再创建 `2026-08-xx-market-jd-center.md`。第二份计划只覆盖：

```text
业务上传 -> standard_v1/liepin_v1/zhilian_v1 Adapter
-> Raw JD -> Normalized JD -> 警告/质量分 -> Catalog 骨架导入
```

它必须用两份现有猎聘、智联样例完成端到端验收；爬虫管理、定时爬取、算法抽取和 Neo4j 发布仍不进入 Batch B。
