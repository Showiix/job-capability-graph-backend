# Graph Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 为已正式发布到 Neo4j 的岗位能力图谱提供 authenticated 全局有限子图和单岗位局部子图读取 API，并用 PostgreSQL 校验当前发布水位和正式主数据状态。

**Architecture:** PostgreSQL 继续作为 GraphVersion、Domain 和 JobRole 正式状态的唯一真相源；Neo4j 只负责读取累积的正式图投影。新增独立 `graph/query.py` 统一执行 PostgreSQL 前置校验、两段式只读 Cypher、稳定标准化、截断和脱敏错误转换，现有发布 `graph/service.py` 不扩大职责。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2 AsyncSession、PostgreSQL 16、Neo4j 5 Async Driver、pytest、Ruff、Docker Compose。

---

## 0. 已锁定范围与文件责任

本计划只实现：

```text
GET /api/v1/graph
GET /api/v1/graph/job-roles/{job_role_id}
```

不增加 Migration、表、依赖、Redis、PostgreSQL 图查询 fallback、历史版本回放、递归遍历、Capability 邻域、`job_level` 筛选或前端代码。

文件责任固定如下：

```text
backend/app/graph/schemas.py
  GraphVersionRead、GraphNode、GraphEdge、GraphReadData 响应契约。

backend/app/graph/query.py
  current GraphVersion 与 active 主数据校验；Neo4j 只读查询；
  nodes/edges 映射、去重、稳定排序、截断和错误脱敏。

backend/app/graph/router.py
  保留现有 /graph-versions admin 路由；新增 /graph authenticated GET 路由。

backend/app/api/router.py
  同时挂载 graph version router 和 graph read router。

backend/tests/test_graph_query.py
  Query Service、Fake Async Driver、PostgreSQL 前置校验、投影一致性和截断测试。

backend/tests/test_graph_read_api.py
  三角色权限、无 CSRF GET、参数边界、响应和稳定错误码测试。

README.md
  Batch F 能力、curl、返回边界、部署与验收说明。
```

所有生产节点 UUID 都来自 PostgreSQL 主数据；所有 edge ID 都使用发布时写入的 SHA256 `relation_key`。current GraphVersion 只作为投影水位和响应元数据，不使用 `node.graph_version = current_version` 过滤累积图。

## Task 1: 隔离工作区、确认 179 测试基线并提交计划

**Files:**

- Modify: `docs/superpowers/specs/2026-08-06-graph-read-api-design.md`
- Create: `docs/superpowers/plans/2026-08-06-graph-read-api.md`

- [x] **Step 1: 确认设计分支和唯一未提交修正**

Run:

```bash
git status --short --branch
git diff --check
git diff -- docs/superpowers/specs/2026-08-06-graph-read-api-design.md
```

Expected:

```text
## codex/graph-read-api...origin/codex/graph-read-api
 M docs/superpowers/specs/2026-08-06-graph-read-api-design.md
```

设计 diff 只能是在“修改文件”列表增加：

```text
backend/app/api/router.py
```

- [x] **Step 2: 运行现有基线**

Run:

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

Expected:

```text
179 passed
All checks passed!
```

- [x] **Step 3: 提交并推送设计修正和本实施计划**

Run:

```bash
git add docs/superpowers/specs/2026-08-06-graph-read-api-design.md \
  docs/superpowers/plans/2026-08-06-graph-read-api.md
git commit -m "docs: plan graph read api"
git push origin codex/graph-read-api
```

Expected: 新提交只包含上述两个文档，远端 `origin/codex/graph-read-api` 指向该提交。

- [x] **Step 4: 在独立 worktree 开始生产代码**

在当前仓库目录执行：

```bash
git switch main
git worktree add ../1-1-ai-1-2-1-graph-read-api codex/graph-read-api
cd ../1-1-ai-1-2-1-graph-read-api
git status --short --branch
```

Expected: 主目录回到 `main`，新 worktree 位于 `codex/graph-read-api` 且工作树干净。后续 Task 2-6 全部在新 worktree 执行。

## Task 2: 响应契约与 current GraphVersion 前置校验

**Files:**

- Modify: `backend/app/graph/schemas.py`
- Create: `backend/app/graph/query.py`
- Create: `backend/tests/test_graph_query.py`

- [x] **Step 1: 写响应模型与无 current version 的 RED 测试**

创建 `backend/tests/test_graph_query.py`：

```python
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.catalog.models import CatalogVersion, Domain, JobRole
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.query import get_global_graph
from app.graph.schemas import GraphEdge, GraphNode, GraphReadData, GraphVersionRead
from app.reviews.models import GraphChangeCandidate


async def _published_context(db_session, user):
    suffix = uuid4().hex
    domain = Domain(
        id=uuid4(),
        code=f"graph-read-{suffix}",
        name="人工智能",
        status="active",
        sort_order=0,
    )
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"AI 工程师-{suffix}",
        description="建设 AI 系统",
        definition_payload={"role_name": "AI 工程师"},
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={"role_name": role.canonical_name},
        source_snapshot={},
        evidence_summary={},
        confidence=Decimal("0.9000"),
        review_status="published",
        created_by_user_id=user.id,
        reviewed_by_user_id=user.id,
        reviewed_at=datetime.now(UTC),
    )
    db_session.add_all([domain, role, proposal])
    await db_session.flush()
    catalog = CatalogVersion(
        id=uuid4(),
        version_no=(
            await db_session.scalar(select(func.max(CatalogVersion.version_no))) or 0
        )
        + 1,
        status="published",
        is_current=True,
        created_by_user_id=user.id,
        summary={"source": "graph_read_test"},
        published_at=datetime.now(UTC),
    )
    version = GraphVersion(
        id=uuid4(),
        version_no=(
            await db_session.scalar(select(func.max(GraphVersion.version_no))) or 0
        )
        + 1,
        source_proposal_id=proposal.id,
        catalog_version_id=catalog.id,
        job_role_id=role.id,
        status="published",
        is_current=True,
        snapshot={"job_role": {"id": str(role.id)}},
        attempt_count=1,
        created_by_user_id=user.id,
        published_at=datetime.now(UTC),
    )
    db_session.add_all([catalog, version])
    await db_session.flush()
    return SimpleNamespace(domain=domain, role=role, version=version)


def test_graph_read_schema_contract() -> None:
    version_id = uuid4()
    role_id = uuid4()
    capability_id = uuid4()
    value = GraphReadData(
        graph_version=GraphVersionRead(
            id=version_id,
            version_no=3,
            published_at=datetime(2026, 8, 6, tzinfo=UTC),
        ),
        nodes=[
            GraphNode(
                id=role_id,
                type="job_role",
                name="AI 自动化测试工程师",
                properties={"status": "active"},
            )
        ],
        edges=[
            GraphEdge(
                id="a" * 64,
                type="requires",
                source=role_id,
                target=capability_id,
                properties={"importance": 1.0},
            )
        ],
        truncated=False,
    )

    assert value.graph_version.id == version_id
    assert value.nodes[0].type == "job_role"
    assert value.edges[0].type == "requires"


async def test_global_graph_requires_current_published_version(
    db_session,
) -> None:
    class DriverMustNotRun:
        async def execute_query(self, query: str, *, parameters_: dict):
            raise AssertionError("Neo4j must not run without a current version")

    with pytest.raises(APIError) as error:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=DriverMustNotRun(),
        )

    assert error.value.status_code == 404
    assert error.value.code == "GRAPH_VERSION_NOT_PUBLISHED"
```

- [x] **Step 2: 运行 RED，确认缺少契约与查询模块**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
```

Expected: collection FAIL，错误包含 `ModuleNotFoundError: No module named 'app.graph.query'` 或缺少 `GraphReadData`。

- [x] **Step 3: 实现最小 Pydantic 响应契约**

将 `backend/app/graph/schemas.py` 改为：

```python
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GraphVersionCreate(BaseModel):
    proposal_id: UUID


class GraphVersionRead(BaseModel):
    id: UUID
    version_no: int
    published_at: datetime


class GraphNode(BaseModel):
    id: UUID
    type: Literal["domain", "job_role", "capability"]
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    type: Literal["belongs_to", "requires", "bonus"]
    source: UUID
    target: UUID
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphReadData(BaseModel):
    graph_version: GraphVersionRead
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
```

- [x] **Step 4: 实现 current GraphVersion 校验和临时空图返回**

创建 `backend/app/graph/query.py`：

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.schemas import GraphReadData, GraphVersionRead
from app.infrastructure.neo4j import neo4j_driver


async def _current_graph_version(db: AsyncSession) -> GraphVersion:
    version = await db.scalar(
        select(GraphVersion).where(
            GraphVersion.status == "published",
            GraphVersion.is_current.is_(True),
        )
    )
    if version is None:
        raise APIError(
            404,
            "GRAPH_VERSION_NOT_PUBLISHED",
            "当前尚无已发布图谱版本",
        )
    return version


def _version_data(version: GraphVersion) -> GraphVersionRead:
    if version.published_at is None:
        raise APIError(
            503,
            "GRAPH_PROJECTION_INCONSISTENT",
            "正式图谱投影不一致",
        )
    return GraphVersionRead(
        id=version.id,
        version_no=version.version_no,
        published_at=version.published_at,
    )


async def get_global_graph(
    db: AsyncSession,
    *,
    domain_id: UUID | None,
    max_job_roles: int,
    max_capabilities: int,
    driver=neo4j_driver,
) -> GraphReadData:
    version = await _current_graph_version(db)
    return GraphReadData(
        graph_version=_version_data(version),
        nodes=[],
        edges=[],
        truncated=False,
    )
```

这里的临时空图只用于让第一组契约测试转绿；Task 3 立即用全局查询测试替换这段函数主体。

- [x] **Step 5: 运行 GREEN 和 Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
uv run ruff check app/graph/schemas.py app/graph/query.py tests/test_graph_query.py
```

Expected:

```text
2 passed
All checks passed!
```

- [x] **Step 6: 提交并推送契约与版本校验**

Run:

```bash
git add backend/app/graph/schemas.py backend/app/graph/query.py \
  backend/tests/test_graph_query.py
git commit -m "feat: add graph read contracts"
git push origin codex/graph-read-api
```

Expected: commit 仅包含响应模型、current version 校验和对应测试。

## Task 3: 全局 Neo4j 查询、标准化与确定性截断

**Files:**

- Modify: `backend/app/graph/query.py`
- Modify: `backend/tests/test_graph_query.py`

- [x] **Step 1: 在 Query 测试模块增加 Fake Driver 和记录工厂**

在 `backend/tests/test_graph_query.py` 的 imports 增加：

```python
from copy import deepcopy

from app.graph.neo4j import relation_key
```

在 `_published_context` 后增加：

```python
class FakeAsyncDriver:
    def __init__(self, *responses: list[dict], error: Exception | None = None):
        self.responses = [deepcopy(response) for response in responses]
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, *, parameters_: dict):
        self.calls.append((query, deepcopy(parameters_)))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0), None, None


def _role_record(context, *, relation_id: str | None = None) -> dict:
    return {
        "role": {
            "id": str(context.role.id),
            "canonical_name": context.role.canonical_name,
            "description": context.role.description,
            "status": "active",
        },
        "domain": {
            "id": str(context.domain.id),
            "code": context.domain.code,
            "name": context.domain.name,
        },
        "relation_key": (
            relation_id
            if relation_id is not None
            else relation_key(
                "BELONGS_TO",
                str(context.role.id),
                str(context.domain.id),
            )
        ),
    }


def _capability_record(
    context,
    capability_id,
    name: str,
    *,
    requirement_type: str,
    role_id=None,
) -> dict:
    role_id = role_id or context.role.id
    return {
        "role_id": str(role_id),
        "requirement_relation_key": relation_key(
            requirement_type,
            str(role_id),
            str(capability_id),
        ),
        "requirement_type": requirement_type,
        "importance": 1.0 if requirement_type == "REQUIRES" else 0.5,
        "capability": {
            "id": str(capability_id),
            "canonical_name": name,
            "skill_type": "method",
            "status": "active",
        },
        "domain": {
            "id": str(context.domain.id),
            "code": context.domain.code,
            "name": context.domain.name,
        },
        "domain_relation_key": relation_key(
            "BELONGS_TO",
            str(capability_id),
            str(context.domain.id),
        ),
    }
```

- [x] **Step 2: 写全局映射、过滤、去重和排序 RED 测试**

在同一测试文件增加：

```python
async def test_global_graph_maps_filters_deduplicates_and_sorts(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    python_id = uuid4()
    testing_id = uuid4()
    python = _capability_record(
        context,
        python_id,
        "Python",
        requirement_type="REQUIRES",
    )
    testing = _capability_record(
        context,
        testing_id,
        "自动化测试",
        requirement_type="BONUS",
    )
    dangling = _capability_record(
        context,
        uuid4(),
        "不应返回",
        requirement_type="REQUIRES",
        role_id=uuid4(),
    )
    driver = FakeAsyncDriver(
        [_role_record(context)],
        [testing, python, deepcopy(python), dangling],
    )

    result = await get_global_graph(
        db_session,
        domain_id=context.domain.id,
        max_job_roles=30,
        max_capabilities=120,
        driver=driver,
    )

    assert result.graph_version.id == context.version.id
    assert [(node.type, node.name) for node in result.nodes] == [
        ("domain", "人工智能"),
        ("job_role", context.role.canonical_name),
        ("capability", "Python"),
        ("capability", "自动化测试"),
    ]
    assert {(edge.type, edge.source, edge.target) for edge in result.edges} == {
        ("belongs_to", context.role.id, context.domain.id),
        ("belongs_to", python_id, context.domain.id),
        ("belongs_to", testing_id, context.domain.id),
        ("bonus", context.role.id, testing_id),
        ("requires", context.role.id, python_id),
    }
    assert result.truncated is False
    assert len({edge.id for edge in result.edges}) == 5
    assert driver.calls[0][1] == {
        "domain_id": str(context.domain.id),
        "role_limit": 31,
    }
    assert driver.calls[1][1]["job_role_ids"] == [str(context.role.id)]
    assert driver.calls[1][1]["relation_limit"] == 1201
```

- [x] **Step 3: 写岗位、Capability 和内部行上限 RED 测试**

增加：

```python
async def test_global_graph_sets_truncated_for_each_limit(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    second_role_id = uuid4()
    third_role_id = uuid4()
    roles = [
        _role_record(context),
        {
            **_role_record(context),
            "role": {
                **_role_record(context)["role"],
                "id": str(second_role_id),
                "canonical_name": "第二岗位",
            },
            "relation_key": relation_key(
                "BELONGS_TO", str(second_role_id), str(context.domain.id)
            ),
        },
        {
            **_role_record(context),
            "role": {
                **_role_record(context)["role"],
                "id": str(third_role_id),
                "canonical_name": "第三岗位",
            },
            "relation_key": relation_key(
                "BELONGS_TO", str(third_role_id), str(context.domain.id)
            ),
        },
    ]
    capabilities = [
        _capability_record(
            context,
            uuid4(),
            f"技能-{index:03d}",
            requirement_type="REQUIRES",
        )
        for index in range(42)
    ]
    driver = FakeAsyncDriver(roles, capabilities)

    result = await get_global_graph(
        db_session,
        domain_id=None,
        max_job_roles=1,
        max_capabilities=1,
        driver=driver,
    )

    assert len([node for node in result.nodes if node.type == "job_role"]) == 1
    assert len([node for node in result.nodes if node.type == "capability"]) == 1
    assert result.truncated is True
    assert driver.calls[0][1]["role_limit"] == 2
    assert driver.calls[1][1]["relation_limit"] == 41
```

这一个用例同时触发岗位多读一项、唯一 Capability 超限和关系行多读一项；返回边必须只保留两端节点均已返回的边。

- [x] **Step 4: 写 Domain、空图库、relation key 与异常脱敏 RED 测试**

增加：

```python
async def test_global_graph_validates_domain_and_empty_projection(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    inactive = Domain(
        id=uuid4(),
        code=f"inactive-{uuid4().hex}",
        name="停用技术域",
        status="deprecated",
        sort_order=1,
    )
    db_session.add(inactive)
    await db_session.flush()

    with pytest.raises(APIError) as missing:
        await get_global_graph(
            db_session,
            domain_id=inactive.id,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(),
        )
    assert missing.value.code == "GRAPH_DOMAIN_NOT_FOUND"

    empty = await get_global_graph(
        db_session,
        domain_id=context.domain.id,
        max_job_roles=30,
        max_capabilities=120,
        driver=FakeAsyncDriver([]),
    )
    assert empty.nodes == []
    assert empty.edges == []
    assert empty.truncated is False

    with pytest.raises(APIError) as inconsistent:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver([]),
        )
    assert inconsistent.value.code == "GRAPH_PROJECTION_INCONSISTENT"


async def test_global_graph_rejects_missing_relation_key_and_sanitizes_driver_error(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    with pytest.raises(APIError) as missing_key:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(
                [_role_record(context, relation_id="")],
                [],
            ),
        )
    assert missing_key.value.code == "GRAPH_PROJECTION_INCONSISTENT"

    with pytest.raises(APIError) as failed:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(
                error=RuntimeError("bolt://neo4j:secret@internal:7687 QUERY")
            ),
        )
    assert failed.value.code == "GRAPH_READ_FAILED"
    assert "bolt" not in failed.value.message
    assert "secret" not in failed.value.message
    assert failed.value.details == {}
```

- [x] **Step 5: 运行 RED，确认临时空图实现不能满足行为**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
```

Expected: 新增全局图用例 FAIL；首个主要差异是 `result.nodes == []`，且 Fake Driver 没有两次查询记录。

- [x] **Step 6: 增加两个全局只读 Cypher 和安全执行器**

在 `backend/app/graph/query.py` imports 调整为：

```python
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Domain
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.schemas import GraphEdge, GraphNode, GraphReadData, GraphVersionRead
from app.infrastructure.neo4j import neo4j_driver

logger = logging.getLogger(__name__)
```

在 imports 后增加：

```python
GLOBAL_ROLE_QUERY = """
MATCH (role:JobRole {status: 'active'})
      -[belongs:BELONGS_TO]->(domain:Domain)
WHERE $domain_id IS NULL OR domain.id = $domain_id
RETURN role {
         .id,
         .canonical_name,
         .description,
         .status
       } AS role,
       domain {
         .id,
         .code,
         .name
       } AS domain,
       belongs.relation_key AS relation_key
ORDER BY toLower(role.canonical_name), role.id
LIMIT $role_limit
"""

GLOBAL_CAPABILITY_QUERY = """
UNWIND $job_role_ids AS role_id
MATCH (role:JobRole {id: role_id, status: 'active'})
MATCH (role)-[requirement]->(capability:Capability {status: 'active'})
WHERE type(requirement) IN ['REQUIRES', 'BONUS']
MATCH (capability)-[belongs:BELONGS_TO]->(domain:Domain)
RETURN role.id AS role_id,
       requirement.relation_key AS requirement_relation_key,
       type(requirement) AS requirement_type,
       requirement.importance AS importance,
       capability {
         .id,
         .canonical_name,
         .skill_type,
         .status
       } AS capability,
       domain {
         .id,
         .code,
         .name
       } AS domain,
       belongs.relation_key AS domain_relation_key
ORDER BY toLower(capability.canonical_name),
         capability.id,
         role.id
LIMIT $relation_limit
"""


def _projection_inconsistent() -> APIError:
    return APIError(
        503,
        "GRAPH_PROJECTION_INCONSISTENT",
        "正式图谱投影不一致",
    )


async def _execute_read(driver, query: str, parameters: dict) -> list[Any]:
    try:
        records, _, _ = await driver.execute_query(
            query,
            parameters_=parameters,
        )
    except Exception as error:
        logger.warning("graph read failed: %s", type(error).__name__)
        raise APIError(503, "GRAPH_READ_FAILED", "图谱读取失败") from None
    return list(records)
```

- [x] **Step 7: 增加 Domain 校验和统一 nodes/edges 标准化**

在 `_version_data` 后增加：

```python
async def _require_active_domain(db: AsyncSession, domain_id: UUID) -> None:
    exists = await db.scalar(
        select(Domain.id).where(
            Domain.id == domain_id,
            Domain.status == "active",
        )
    )
    if exists is None:
        raise APIError(
            404,
            "GRAPH_DOMAIN_NOT_FOUND",
            "技术域不存在或未启用",
        )


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise _projection_inconsistent() from None


def _relation_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise _projection_inconsistent()
    return value


def _domain_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="domain",
        name=str(value["name"]),
        properties={"code": value["code"], "status": "active"},
    )


def _role_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="job_role",
        name=str(value["canonical_name"]),
        properties={
            "status": value["status"],
            "description": value.get("description"),
        },
    )


def _capability_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="capability",
        name=str(value["canonical_name"]),
        properties={
            "status": value["status"],
            "skill_type": value["skill_type"],
        },
    )


def _sorted_nodes(nodes: dict[tuple[str, UUID], GraphNode]) -> list[GraphNode]:
    type_order = {"domain": 0, "job_role": 1, "capability": 2}
    return sorted(
        nodes.values(),
        key=lambda node: (
            type_order[node.type],
            node.name.casefold(),
            str(node.id),
        ),
    )


def _sorted_edges(edges: dict[str, GraphEdge]) -> list[GraphEdge]:
    return sorted(
        edges.values(),
        key=lambda edge: (
            edge.type,
            str(edge.source),
            str(edge.target),
            edge.id,
        ),
    )


def _normalize_graph(
    version: GraphVersion,
    role_records: list[Any],
    capability_records: list[Any],
    *,
    max_capabilities: int | None,
    truncated: bool,
) -> GraphReadData:
    nodes: dict[tuple[str, UUID], GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    returned_role_ids: set[UUID] = set()

    try:
        for record in role_records:
            role = _role_node(dict(record["role"]))
            domain = _domain_node(dict(record["domain"]))
            nodes[(role.type, role.id)] = role
            nodes[(domain.type, domain.id)] = domain
            returned_role_ids.add(role.id)
            edge_id = _relation_id(record["relation_key"])
            edges.setdefault(
                edge_id,
                GraphEdge(
                    id=edge_id,
                    type="belongs_to",
                    source=role.id,
                    target=domain.id,
                ),
            )

        ordered_records = sorted(
            capability_records,
            key=lambda record: (
                str(record["capability"]["canonical_name"]).casefold(),
                str(record["capability"]["id"]),
                str(record["role_id"]),
            ),
        )
        selected_capability_ids: set[UUID] = set()
        for record in ordered_records:
            capability_id = _uuid(record["capability"]["id"])
            if capability_id in selected_capability_ids:
                continue
            if (
                max_capabilities is not None
                and len(selected_capability_ids) >= max_capabilities
            ):
                truncated = True
                continue
            selected_capability_ids.add(capability_id)

        for record in ordered_records:
            role_id = _uuid(record["role_id"])
            capability = _capability_node(dict(record["capability"]))
            if (
                role_id not in returned_role_ids
                or capability.id not in selected_capability_ids
            ):
                continue
            domain = _domain_node(dict(record["domain"]))
            nodes[(capability.type, capability.id)] = capability
            nodes[(domain.type, domain.id)] = domain

            domain_edge_id = _relation_id(record["domain_relation_key"])
            edges.setdefault(
                domain_edge_id,
                GraphEdge(
                    id=domain_edge_id,
                    type="belongs_to",
                    source=capability.id,
                    target=domain.id,
                ),
            )
            requirement_type = str(record["requirement_type"])
            if requirement_type not in {"REQUIRES", "BONUS"}:
                raise _projection_inconsistent()
            requirement_edge_id = _relation_id(
                record["requirement_relation_key"]
            )
            edges.setdefault(
                requirement_edge_id,
                GraphEdge(
                    id=requirement_edge_id,
                    type=(
                        "requires" if requirement_type == "REQUIRES" else "bonus"
                    ),
                    source=role_id,
                    target=capability.id,
                    properties={"importance": float(record["importance"])},
                ),
            )
    except APIError:
        raise
    except (KeyError, TypeError, ValueError):
        raise _projection_inconsistent() from None

    returned_ids = {node.id for node in nodes.values()}
    edges = {
        edge_id: edge
        for edge_id, edge in edges.items()
        if edge.source in returned_ids and edge.target in returned_ids
    }
    return GraphReadData(
        graph_version=_version_data(version),
        nodes=_sorted_nodes(nodes),
        edges=_sorted_edges(edges),
        truncated=truncated,
    )
```

- [x] **Step 8: 用完整全局查询替换临时 `get_global_graph` 函数主体**

将函数改为：

```python
async def get_global_graph(
    db: AsyncSession,
    *,
    domain_id: UUID | None,
    max_job_roles: int,
    max_capabilities: int,
    driver=neo4j_driver,
) -> GraphReadData:
    version = await _current_graph_version(db)
    if domain_id is not None:
        await _require_active_domain(db, domain_id)

    role_records = await _execute_read(
        driver,
        GLOBAL_ROLE_QUERY,
        {
            "domain_id": str(domain_id) if domain_id is not None else None,
            "role_limit": max_job_roles + 1,
        },
    )
    if not role_records:
        if domain_id is None:
            raise _projection_inconsistent()
        return GraphReadData(
            graph_version=_version_data(version),
            nodes=[],
            edges=[],
            truncated=False,
        )

    role_records = sorted(
        role_records,
        key=lambda record: (
            str(record["role"]["canonical_name"]).casefold(),
            str(record["role"]["id"]),
        ),
    )
    role_overflow = len(role_records) > max_job_roles
    role_records = role_records[:max_job_roles]
    job_role_ids = [str(record["role"]["id"]) for record in role_records]
    relation_limit = max_job_roles * 40 + 1
    capability_records = await _execute_read(
        driver,
        GLOBAL_CAPABILITY_QUERY,
        {
            "job_role_ids": job_role_ids,
            "relation_limit": relation_limit,
        },
    )
    relation_overflow = len(capability_records) >= relation_limit
    if relation_overflow:
        capability_records = capability_records[: relation_limit - 1]

    return _normalize_graph(
        version,
        role_records,
        capability_records,
        max_capabilities=max_capabilities,
        truncated=role_overflow or relation_overflow,
    )
```

- [x] **Step 9: 运行全局 Query GREEN、回归和 Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
uv run pytest tests/test_graph_neo4j.py tests/test_graph_service.py -q
uv run ruff check app/graph/query.py tests/test_graph_query.py
```

Expected: 所有命令 PASS；Query 测试覆盖两次查询参数、空 Domain 结果、三类截断、dangling edge 清除、relation key 缺失和驱动错误脱敏。

- [x] **Step 10: 提交并推送全局图读取**

Run:

```bash
git add backend/app/graph/query.py backend/tests/test_graph_query.py
git commit -m "feat: query published global graph"
git push origin codex/graph-read-api
```

Expected: commit 不修改发布 service，不新增依赖或 Migration。

## Task 4: 单 JobRole 局部子图与投影一致性

**Files:**

- Modify: `backend/app/graph/query.py`
- Modify: `backend/tests/test_graph_query.py`

- [x] **Step 1: 导入局部查询函数并写 required/bonus RED 测试**

把 `backend/tests/test_graph_query.py` 中的 query import 改为：

```python
from app.graph.query import get_global_graph, get_job_role_graph
```

增加：

```python
async def test_job_role_graph_returns_complete_local_subgraph(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    python_id = uuid4()
    cicd_id = uuid4()
    required = _capability_record(
        context,
        python_id,
        "Python",
        requirement_type="REQUIRES",
    )
    bonus = _capability_record(
        context,
        cicd_id,
        "CI/CD",
        requirement_type="BONUS",
    )
    role_record = _role_record(context)
    records = []
    for capability in (required, bonus):
        records.append(
            {
                **capability,
                "role": role_record["role"],
                "domain": role_record["domain"],
                "relation_key": role_record["relation_key"],
                "capability_domain": capability["domain"],
            }
        )
    driver = FakeAsyncDriver(records)

    result = await get_job_role_graph(
        db_session,
        context.role.id,
        driver=driver,
    )

    assert result.graph_version.id == context.version.id
    assert {node.id for node in result.nodes} == {
        context.domain.id,
        context.role.id,
        python_id,
        cicd_id,
    }
    assert {edge.type for edge in result.edges} == {
        "belongs_to",
        "requires",
        "bonus",
    }
    assert result.truncated is False
    assert driver.calls[0][1] == {"job_role_id": str(context.role.id)}
```

- [x] **Step 2: 写零技能、PostgreSQL 校验和缺失投影 RED 测试**

增加：

```python
async def test_job_role_graph_allows_role_without_capabilities(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    empty_record = {
        **_role_record(context),
        "role_id": str(context.role.id),
        "requirement_relation_key": None,
        "requirement_type": None,
        "importance": None,
        "capability": None,
        "capability_domain": None,
        "domain_relation_key": None,
    }

    result = await get_job_role_graph(
        db_session,
        context.role.id,
        driver=FakeAsyncDriver([empty_record]),
    )

    assert [(node.type, node.id) for node in result.nodes] == [
        ("domain", context.domain.id),
        ("job_role", context.role.id),
    ]
    assert len(result.edges) == 1
    assert result.edges[0].type == "belongs_to"
    assert result.truncated is False


async def test_job_role_graph_validates_formal_role_and_current_version(
    db_session,
    user,
) -> None:
    domain = Domain(
        id=uuid4(),
        code=f"job-role-validation-{uuid4().hex}",
        name="岗位校验域",
        status="active",
        sort_order=0,
    )
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"待发布岗位-{uuid4().hex}",
        definition_payload={},
        status="active",
        source_type="manual",
    )
    db_session.add_all([domain, role])
    await db_session.flush()
    driver = FakeAsyncDriver(error=AssertionError("driver must not run"))

    with pytest.raises(APIError) as unpublished:
        await get_job_role_graph(db_session, role.id, driver=driver)
    assert unpublished.value.code == "GRAPH_VERSION_NOT_PUBLISHED"

    with pytest.raises(APIError) as missing:
        await get_job_role_graph(db_session, uuid4(), driver=driver)
    assert missing.value.code == "GRAPH_JOB_ROLE_NOT_FOUND"
    assert driver.calls == []


async def test_job_role_graph_rejects_missing_neo4j_projection(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)

    with pytest.raises(APIError) as error:
        await get_job_role_graph(
            db_session,
            context.role.id,
            driver=FakeAsyncDriver([]),
        )

    assert error.value.status_code == 503
    assert error.value.code == "GRAPH_PROJECTION_INCONSISTENT"
```

- [x] **Step 3: 运行 RED，确认函数尚不存在**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
```

Expected: collection 或执行 FAIL，错误指向缺少 `get_job_role_graph`。

- [x] **Step 4: 增加单岗位只读 Cypher**

在 `GLOBAL_CAPABILITY_QUERY` 后增加：

```python
JOB_ROLE_GRAPH_QUERY = """
MATCH (role:JobRole {id: $job_role_id, status: 'active'})
      -[roleBelongs:BELONGS_TO]->(domain:Domain)
OPTIONAL MATCH (role)-[requirement]->(capability:Capability {status: 'active'})
WHERE requirement IS NULL OR type(requirement) IN ['REQUIRES', 'BONUS']
OPTIONAL MATCH (capability)-[capabilityBelongs:BELONGS_TO]
      ->(capabilityDomain:Domain)
RETURN role {
         .id,
         .canonical_name,
         .description,
         .status
       } AS role,
       domain {
         .id,
         .code,
         .name
       } AS domain,
       roleBelongs.relation_key AS relation_key,
       role.id AS role_id,
       requirement.relation_key AS requirement_relation_key,
       type(requirement) AS requirement_type,
       requirement.importance AS importance,
       capability {
         .id,
         .canonical_name,
         .skill_type,
         .status
       } AS capability,
       capabilityDomain {
         .id,
         .code,
         .name
       } AS capability_domain,
       capabilityBelongs.relation_key AS domain_relation_key
ORDER BY toLower(capability.canonical_name), capability.id
"""
```

- [x] **Step 5: 增加 active JobRole 校验和局部查询函数**

先把 `backend/app/graph/query.py` 的 catalog import 改为：

```python
from app.catalog.models import Domain, JobRole
```

在 `_require_active_domain` 后增加：

```python
async def _require_active_job_role(
    db: AsyncSession,
    job_role_id: UUID,
) -> JobRole:
    role = await db.scalar(
        select(JobRole).where(
            JobRole.id == job_role_id,
            JobRole.status == "active",
        )
    )
    if role is None:
        raise APIError(
            404,
            "GRAPH_JOB_ROLE_NOT_FOUND",
            "岗位不存在或未启用",
        )
    return role
```

在文件末尾增加：

```python
async def get_job_role_graph(
    db: AsyncSession,
    job_role_id: UUID,
    *,
    driver=neo4j_driver,
) -> GraphReadData:
    role = await _require_active_job_role(db, job_role_id)
    version = await _current_graph_version(db)
    records = await _execute_read(
        driver,
        JOB_ROLE_GRAPH_QUERY,
        {"job_role_id": str(role.id)},
    )
    if not records:
        raise _projection_inconsistent()

    capability_records = []
    for record in records:
        if record["capability"] is None:
            continue
        capability_records.append(
            {
                **dict(record),
                "domain": record["capability_domain"],
            }
        )
    return _normalize_graph(
        version,
        [records[0]],
        capability_records,
        max_capabilities=None,
        truncated=False,
    )
```

- [x] **Step 6: 运行局部 Query GREEN、全部 Query 回归和 Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py -q
uv run ruff check app/graph/query.py tests/test_graph_query.py
```

Expected: 全部 PASS；零技能岗位返回 Domain、JobRole 和一条 `belongs_to`，Neo4j 缺失正式岗位返回 503。

- [x] **Step 7: 提交并推送单岗位子图**

Run:

```bash
git add backend/app/graph/query.py backend/tests/test_graph_query.py
git commit -m "feat: query published job role graph"
git push origin codex/graph-read-api
```

Expected: commit 只扩展 query 模块和 focused tests，`graph/service.py` 保持不变。

## Task 5: authenticated Read API、三角色和参数边界

**Files:**

- Modify: `backend/app/graph/router.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_graph_read_api.py`

- [x] **Step 1: 写 applicant/hr/admin 均可读且 GET 无 CSRF 的 RED 测试**

创建 `backend/tests/test_graph_read_api.py`：

```python
from datetime import UTC, datetime
from uuid import uuid4

from app.core.errors import APIError
from app.graph.schemas import GraphReadData, GraphVersionRead

pytest_plugins = ("tests.test_discovery_api",)


async def _login(client, role: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": f"discovery_api_{role}",
            "password": f"{role}-password",
        },
    )
    assert response.status_code == 200


def _graph_data() -> GraphReadData:
    return GraphReadData(
        graph_version=GraphVersionRead(
            id=uuid4(),
            version_no=3,
            published_at=datetime(2026, 8, 6, tzinfo=UTC),
        ),
        nodes=[],
        edges=[],
        truncated=False,
    )


async def test_all_authenticated_roles_read_graph_without_csrf(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    global_calls = []
    local_calls = []
    job_role_id = uuid4()

    async def fake_global(db, **kwargs):
        global_calls.append(kwargs)
        return _graph_data()

    async def fake_local(db, value, **kwargs):
        local_calls.append((value, kwargs))
        return _graph_data()

    monkeypatch.setattr("app.graph.router.get_global_graph", fake_global)
    monkeypatch.setattr("app.graph.router.get_job_role_graph", fake_local)

    for role in ("applicant", "hr", "admin"):
        await _login(client, role)
        global_response = await client.get(
            "/api/v1/graph",
            params={
                "domain_id": str(uuid4()),
                "max_job_roles": 12,
                "max_capabilities": 80,
            },
        )
        local_response = await client.get(
            f"/api/v1/graph/job-roles/{job_role_id}"
        )
        assert global_response.status_code == 200
        assert local_response.status_code == 200
        assert global_response.json()["data"]["graph_version"]["version_no"] == 3
        assert local_response.json()["data"]["truncated"] is False

    assert len(global_calls) == 3
    assert all(call["max_job_roles"] == 12 for call in global_calls)
    assert all(call["max_capabilities"] == 80 for call in global_calls)
    assert local_calls == [(job_role_id, {})] * 3
```

- [x] **Step 2: 写未登录、范围校验、稳定 404/503 和脱敏 RED 测试**

在同一文件增加：

```python
async def test_graph_read_requires_authentication(client, monkeypatch) -> None:
    async def must_not_run(*args, **kwargs):
        raise AssertionError("query service must not run")

    monkeypatch.setattr("app.graph.router.get_global_graph", must_not_run)
    monkeypatch.setattr("app.graph.router.get_job_role_graph", must_not_run)

    global_response = await client.get("/api/v1/graph")
    local_response = await client.get(f"/api/v1/graph/job-roles/{uuid4()}")

    assert global_response.status_code == 401
    assert local_response.status_code == 401
    assert global_response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert local_response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_global_graph_query_parameter_bounds(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    await _login(client, "applicant")

    async def must_not_run(*args, **kwargs):
        raise AssertionError("invalid parameters must not reach query service")

    monkeypatch.setattr("app.graph.router.get_global_graph", must_not_run)
    responses = [
        await client.get("/api/v1/graph?max_job_roles=0"),
        await client.get("/api/v1/graph?max_job_roles=51"),
        await client.get("/api/v1/graph?max_capabilities=0"),
        await client.get("/api/v1/graph?max_capabilities=201"),
        await client.get("/api/v1/graph?domain_id=not-a-uuid"),
    ]

    assert all(response.status_code == 422 for response in responses)
    assert all(
        response.json()["error"]["code"] == "VALIDATION_FAILED"
        for response in responses
    )


async def test_graph_read_returns_stable_service_errors(
    client,
    discovery_api_users,
    monkeypatch,
) -> None:
    await _login(client, "hr")

    async def missing_domain(db, **kwargs):
        raise APIError(404, "GRAPH_DOMAIN_NOT_FOUND", "技术域不存在或未启用")

    async def failed_role(db, job_role_id, **kwargs):
        raise APIError(503, "GRAPH_READ_FAILED", "图谱读取失败")

    monkeypatch.setattr("app.graph.router.get_global_graph", missing_domain)
    monkeypatch.setattr("app.graph.router.get_job_role_graph", failed_role)
    global_response = await client.get(
        "/api/v1/graph",
        params={"domain_id": str(uuid4())},
    )
    local_response = await client.get(f"/api/v1/graph/job-roles/{uuid4()}")

    assert global_response.status_code == 404
    assert global_response.json()["error"]["code"] == "GRAPH_DOMAIN_NOT_FOUND"
    assert local_response.status_code == 503
    assert local_response.json()["error"]["code"] == "GRAPH_READ_FAILED"
    assert "bolt://" not in local_response.text
    assert "password" not in local_response.text
    assert "query" not in local_response.text.lower()
```

- [x] **Step 3: 运行 RED，确认 `/api/v1/graph` 尚未挂载**

Run:

```bash
cd backend
uv run pytest tests/test_graph_read_api.py -q
```

Expected: 路由测试 FAIL，未登录请求首先返回 404 `NOT_FOUND`，登录后的请求也无法得到 200。

- [x] **Step 4: 在现有 graph router 中增加独立 read router**

修改 `backend/app/graph/router.py` imports：

```python
from app.api.dependencies import CSRF, DB, Admin, Identity
from app.graph.query import get_global_graph, get_job_role_graph
from app.graph.schemas import GraphVersionCreate
```

保留现有：

```python
router = APIRouter(prefix="/graph-versions", tags=["graph"])
```

紧接着增加：

```python
read_router = APIRouter(prefix="/graph", tags=["graph"])


@read_router.get("")
async def global_graph(
    db: DB,
    identity: Identity,
    domain_id: UUID | None = Query(default=None),
    max_job_roles: int = Query(default=30, ge=1, le=50),
    max_capabilities: int = Query(default=120, ge=1, le=200),
) -> dict:
    value = await get_global_graph(
        db,
        domain_id=domain_id,
        max_job_roles=max_job_roles,
        max_capabilities=max_capabilities,
    )
    return {"data": value.model_dump(mode="json")}


@read_router.get("/job-roles/{job_role_id}")
async def job_role_graph(
    job_role_id: UUID,
    db: DB,
    identity: Identity,
) -> dict:
    value = await get_job_role_graph(db, job_role_id)
    return {"data": value.model_dump(mode="json")}
```

`identity: Identity` 只负责触发现有 Session 认证；不检查具体角色，因此 applicant、hr、admin 均可读。两个 GET 均不声明 `CSRF`。

- [x] **Step 5: 挂载 read router，同时保留 graph version router**

在 `backend/app/api/router.py` 将 graph import 改为：

```python
from app.graph.router import read_router as graph_read_router
from app.graph.router import router as graph_router
```

在已有：

```python
api_router.include_router(graph_router)
```

之后增加：

```python
api_router.include_router(graph_read_router)
```

- [x] **Step 6: 运行 API GREEN、旧 GraphVersion API 回归和 Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_graph_read_api.py tests/test_graph_api.py -q
uv run ruff check app/graph/router.py app/api/router.py \
  tests/test_graph_read_api.py
```

Expected: 所有测试 PASS；旧 `/graph-versions` 仍为 admin-only，新的两个 GET 对三种登录角色开放且不需要 CSRF。

- [x] **Step 7: 提交并推送读取 API**

Run:

```bash
git add backend/app/graph/router.py backend/app/api/router.py \
  backend/tests/test_graph_read_api.py
git commit -m "feat: expose published graph read api"
git push origin codex/graph-read-api
```

Expected: commit 只包含路由、挂载和 API 测试。

## Task 6: README、完整门禁和真实 Neo4j 只读 EXPLAIN

**Files:**

- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-06-graph-read-api.md`

- [x] **Step 1: 更新 README 顶部闭环说明**

把：

```markdown
面向比赛展示与团队内部真实使用的岗位能力图谱后端。当前已形成五段可运行闭环：
```

改为：

```markdown
面向比赛展示与团队内部真实使用的岗位能力图谱后端。当前已形成六段可运行闭环：
```

在 Batch E 后增加：

```markdown
- Batch F：三种登录角色读取 Neo4j 正式全局有限子图和单岗位能力子图，PostgreSQL 校验当前发布水位与正式主数据状态。
```

- [x] **Step 2: 增加可执行读取示例和边界说明**

在 README“正式图谱发布”段落后增加：

````markdown
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

全局接口最多返回 50 个岗位和 200 个唯一 Capability，默认分别为 30 和 120。岗位、技能或内部关系行超出限制时，响应中的 `truncated` 为 `true`；调用方可以降低 Domain 范围或调整允许的 limit。单岗位当前最多包含 20 个必备技能和 20 个加分技能，因此不分页。

响应只包含 `domain`、`job_role`、`capability` 节点和 `belongs_to`、`requires`、`bonus` 关系。节点 ID 使用 PostgreSQL UUID，关系 ID 使用发布阶段生成的 SHA256 `relation_key`。接口不返回原始 JD、Evidence、审核提案、发布快照、数据库连接信息或 Neo4j 查询文本。

没有 current published GraphVersion、Domain/JobRole 不存在、PostgreSQL 与 Neo4j 投影不一致、Neo4j 读取失败时，分别返回稳定的 `GRAPH_VERSION_NOT_PUBLISHED`、`GRAPH_DOMAIN_NOT_FOUND`、`GRAPH_JOB_ROLE_NOT_FOUND`、`GRAPH_PROJECTION_INCONSISTENT` 或 `GRAPH_READ_FAILED`。
````

- [x] **Step 3: 在设计文档索引增加 Batch F**

在 README 的 Batch E 计划链接后增加：

```markdown
- [Batch F：正式图谱读取实施计划](./docs/superpowers/plans/2026-08-06-graph-read-api.md)
```

- [x] **Step 4: 运行 focused、全量测试和 Ruff**

Run:

```bash
cd backend
uv run pytest tests/test_graph_query.py tests/test_graph_read_api.py -q
uv run pytest -q
uv run ruff check .
```

Expected:

```text
focused graph tests passed
193 passed
All checks passed!
```

若实际总数大于 193，只要新增测试均被收集、没有 skip/xfail 且全量 PASS，即满足门禁。

- [x] **Step 5: 验证 Compose、Migration 无漂移和文件范围**

从仓库根目录运行：

```bash
docker compose config -q
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
  uv run alembic check
cd ..
git diff --check
git diff --name-only main...HEAD | rg 'backend/alembic|backend/pyproject.toml|backend/uv.lock'
```

Expected:

```text
docker compose config: exit 0
No new upgrade operations detected.
git diff --check: exit 0
最后一个 rg: 无输出，exit 1
```

最后一个 `rg` 的 exit 1 表示没有 Migration、依赖清单或 lockfile 变化，是预期结果。

- [x] **Step 6: 对三条生产 Cypher 执行真实 Neo4j 5 `EXPLAIN`**

使用既有 `backend-foundation` Compose project 启动 Neo4j，不删除 Volume：

```bash
docker compose -p backend-foundation up -d neo4j
docker compose -p backend-foundation ps neo4j
```

Expected: `neo4j` 为 `running` 或 `healthy`。

全局岗位查询：

```bash
docker compose -p backend-foundation exec -T neo4j cypher-shell \
  -u neo4j -p job_graph_dev --access-mode read --format verbose \
  -P '{domain_id: null, role_limit: 31}' \
  "EXPLAIN
  MATCH (role:JobRole {status: 'active'})
        -[belongs:BELONGS_TO]->(domain:Domain)
  WHERE \$domain_id IS NULL OR domain.id = \$domain_id
  RETURN role {
           .id, .canonical_name, .description, .status
         } AS role,
         domain { .id, .code, .name } AS domain,
         belongs.relation_key AS relation_key
  ORDER BY toLower(role.canonical_name), role.id
  LIMIT \$role_limit"
```

全局 Capability 查询：

```bash
docker compose -p backend-foundation exec -T neo4j cypher-shell \
  -u neo4j -p job_graph_dev --access-mode read --format verbose \
  -P "{job_role_ids: ['00000000-0000-0000-0000-000000000001'], relation_limit: 1201}" \
  "EXPLAIN
  UNWIND \$job_role_ids AS role_id
  MATCH (role:JobRole {id: role_id, status: 'active'})
  MATCH (role)-[requirement]->(capability:Capability {status: 'active'})
  WHERE type(requirement) IN ['REQUIRES', 'BONUS']
  MATCH (capability)-[belongs:BELONGS_TO]->(domain:Domain)
  RETURN role.id AS role_id,
         requirement.relation_key AS requirement_relation_key,
         type(requirement) AS requirement_type,
         requirement.importance AS importance,
         capability { .id, .canonical_name, .skill_type, .status } AS capability,
         domain { .id, .code, .name } AS domain,
         belongs.relation_key AS domain_relation_key
  ORDER BY toLower(capability.canonical_name), capability.id, role.id
  LIMIT \$relation_limit"
```

单岗位局部查询：

```bash
docker compose -p backend-foundation exec -T neo4j cypher-shell \
  -u neo4j -p job_graph_dev --access-mode read --format verbose \
  -P "{job_role_id: '00000000-0000-0000-0000-000000000001'}" \
  "EXPLAIN
  MATCH (role:JobRole {id: \$job_role_id, status: 'active'})
        -[roleBelongs:BELONGS_TO]->(domain:Domain)
  OPTIONAL MATCH (role)-[requirement]
        ->(capability:Capability {status: 'active'})
  WHERE requirement IS NULL OR type(requirement) IN ['REQUIRES', 'BONUS']
  OPTIONAL MATCH (capability)-[capabilityBelongs:BELONGS_TO]
        ->(capabilityDomain:Domain)
  RETURN role { .id, .canonical_name, .description, .status } AS role,
         domain { .id, .code, .name } AS domain,
         roleBelongs.relation_key AS relation_key,
         role.id AS role_id,
         requirement.relation_key AS requirement_relation_key,
         type(requirement) AS requirement_type,
         requirement.importance AS importance,
         capability { .id, .canonical_name, .skill_type, .status } AS capability,
         capabilityDomain { .id, .code, .name } AS capability_domain,
         capabilityBelongs.relation_key AS domain_relation_key
  ORDER BY toLower(capability.canonical_name), capability.id"
```

Expected: 三条命令都返回 `Plan=EXPLAIN`、`Statement=READ_ONLY`，没有 `Create`、`Merge`、`Set` 或 `Delete` operator。`EXPLAIN` 不创建测试节点。

- [x] **Step 7: 更新计划执行状态，提交并推送文档**

在本计划中把 Task 1-6 已完成步骤的 checkbox 改为 `[x]`，记录最终测试数和真实 EXPLAIN 结果；不改设计范围。

Run:

```bash
git add README.md docs/superpowers/plans/2026-08-06-graph-read-api.md
git commit -m "docs: document graph read api"
git push origin codex/graph-read-api
```

Expected: 文档提交后 feature branch 工作树干净，远端已包含 Batch F 全部提交。

Task 1-6 实际验收记录（2026-08-06）：

```text
baseline: 179 passed
focused graph read tests: 14 passed
full regression: 193 passed
Ruff: All checks passed!
Docker Compose config: passed
Alembic check: No new upgrade operations detected.
Migration/dependency diff: none
Neo4j 5.26.29 global role EXPLAIN: READ_ONLY
Neo4j 5.26.29 global capability EXPLAIN: READ_ONLY
Neo4j 5.26.29 job role EXPLAIN: READ_ONLY
Neo4j active JobRole at verification time: 0
```

worktree 缺少被 Git 忽略的 `.env` 时，只创建了指向主仓库 `.env` 的本地忽略 symlink。一次使用错误 Compose project name 的启动尝试创建了从未启动的容器和空 Volume；两者已按精确名称删除，既有 `backend-foundation` PostgreSQL、Neo4j、Redis 和文件 Volume 未删除。

## Task 7: Fast-forward 合并 main、主线复验、推送与清理

**Files:**

- No source changes expected.
- Preserve: PostgreSQL、Neo4j、Redis 和文件 Docker Volumes。
- Preserve remote branch: `origin/codex/graph-read-api`。

- [x] **Step 1: 在 feature worktree 做合并前最终确认**

Run:

```bash
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --check main...HEAD
```

Expected: worktree clean；提交序列只包含 Batch F 设计/计划、契约、全局查询、局部查询、API 和 README。

- [x] **Step 2: 在主仓库 fast-forward 合并**

回到主仓库：

```bash
cd ../1-1-ai-1-2-1
git switch main
git fetch origin
git merge --ff-only codex/graph-read-api
```

Expected: main 从 `8b409e7` fast-forward 到 Batch F 最终提交，没有 merge commit。

- [x] **Step 3: 在 main 重跑完整门禁**

Run:

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
cd ..
git diff --check
```

Expected: 与 feature branch 相同的全量测试数，Ruff、Compose、Alembic 和 diff check 全部通过。

- [x] **Step 4: 推送 main**

Run:

```bash
git push origin main
git status --short --branch
```

Expected: `origin/main` 指向 Batch F 最终提交，main 工作树干净且 ahead/behind 为 0。

- [x] **Step 5: 清理本地 feature worktree 和分支**

Run:

```bash
git worktree remove ../1-1-ai-1-2-1-graph-read-api
git branch -d codex/graph-read-api
git worktree list
git branch -r --list origin/codex/graph-read-api
```

Expected: 本地 feature worktree 和本地 feature branch 已删除；`origin/codex/graph-read-api` 仍保留。

不要执行：

```text
docker compose down -v
```

Task 7 实际验收记录（2026-08-06）：

```text
fast-forward: main 8b409e7 -> fb05562
main full regression: 193 passed
main Ruff: All checks passed!
main Docker Compose config: passed
main Alembic check: No new upgrade operations detected.
runtime restore: api/worker/scheduler running
GET /health/ready: ready
required dependencies: postgresql/redis/neo4j/file_volume = ok
optional algorithm_service: degraded
```

第一次 main 最终测试因既有运行服务长期连接占满 PostgreSQL 而返回 `TooManyConnectionsError`；临时停止 API/worker/scheduler 后连接释放，193 个测试全部通过。三个服务随后恢复，PostgreSQL 只剩 2 个应用 idle 连接，Ready 检查通过。该运行环境问题未修改 Batch F 代码，也未删除任何既有 Volume。

## 完成定义

Batch F 只有同时满足以下条件才完成：

1. `GET /api/v1/graph` 和 `GET /api/v1/graph/job-roles/{job_role_id}` 对 applicant、hr、admin 可用，未登录返回现有认证错误，GET 不需要 CSRF。
2. PostgreSQL 校验 current published GraphVersion、active Domain 和 active JobRole；Neo4j 承担正式图查询，不存在 PostgreSQL fallback。
3. 全局读取稳定限制岗位、唯一 Capability 和内部关系行，并准确返回 `truncated`。
4. 单岗位允许零技能，但 PostgreSQL 正式岗位在 Neo4j 缺失时返回 `GRAPH_PROJECTION_INCONSISTENT`。
5. edge ID 只接受发布时 relation key；驱动异常不泄露 URI、账号、密码、Cypher 或原始异常文本。
6. 无新 Migration、依赖、缓存、历史接口、递归遍历或前端实现。
7. focused tests、全量 pytest、Ruff、Compose config、Alembic check、git diff check 和真实 Neo4j EXPLAIN 全部通过。
8. feature branch 已逐阶段 commit/push，main 通过 fast-forward 合并、主线复验和 push；Docker Volumes 保留。
