# 正式图谱读取 API 设计

## 1. 目标

Batch F 为已经发布到 Neo4j 的正式岗位能力图谱提供稳定的后端读取接口，直接支撑后续全局图谱展示和岗位详情局部图谱。

本批只读取人工审核并由管理员正式发布的知识。PostgreSQL 继续保存主数据、正式状态和版本账本，Neo4j 负责图结构查询。接口不读取原始 JD、审核表单、算法候选或 LLM 中间结果。

## 2. 已确认的技术方案

采用“Neo4j 查询投影 + PostgreSQL 状态校验”方案：

1. PostgreSQL 查询 current published GraphVersion，作为当前投影水位和响应版本元数据。
2. PostgreSQL 校验 Domain、JobRole 是否为 active 正式主数据。
3. Neo4j 查询已发布的 Domain、JobRole、Capability 和正式关系。
4. Python 将 Neo4j 结果标准化为稳定的 nodes/edges 响应。

不采用 PostgreSQL 拼图方案，因为这会使 Neo4j 失去实际查询职责。不实现 Neo4j 失败后自动回退 PostgreSQL，因为两套读取逻辑会增加结果不一致风险。

current GraphVersion 表示最近一次成功发布的投影水位，不用于只筛选 `node.graph_version = current`。当前 GraphVersion 每次发布一个岗位，而 Neo4j 正式图谱会累积所有 active 已发布岗位；按 current 版本号过滤会错误排除更早发布但仍然 active 的岗位。

## 3. 接口范围

### 3.1 全局有限子图

```http
GET /api/v1/graph
```

查询参数：

| 参数 | 类型 | 默认值 | 限制 | 说明 |
| --- | --- | ---: | ---: | --- |
| domain_id | UUID | 无 | active Domain | 只返回该技术域内的岗位 |
| max_job_roles | integer | 30 | 1-50 | 最大岗位数量 |
| max_capabilities | integer | 120 | 1-200 | 最大技能数量 |

接口返回有限的 active Domain、JobRole、Capability 及其 `BELONGS_TO`、`REQUIRES`、`BONUS` 关系。

### 3.2 岗位能力子图

```http
GET /api/v1/graph/job-roles/{job_role_id}
```

返回目标岗位、岗位所属 Domain、全部必备和加分 Capability、Capability 所属 Domain，以及相应关系。当前岗位定义最多包含 20 个必备技能和 20 个加分技能，因此岗位子图不分页，也不递归遍历其他技能关系。

### 3.3 权限

两个接口均要求登录：

- applicant：允许读取。
- hr：允许读取。
- admin：允许读取。
- 未登录：返回认证错误。

两个接口均为 GET，不需要 CSRF Token。

## 4. 明确不实现

本批不实现：

- Capability 邻域接口。
- 技能前置关系和相关技能。
- Graph Version 历史图谱回放。
- Graph Version diff。
- `job_level` 筛选。
- 任意深度遍历。
- Redis 缓存。
- PostgreSQL 图查询回退。
- 前端 3D 渲染逻辑。

原因是当前正式投影尚未保存 job_level、PREREQUISITE_OF、RELATED_TO 和关系有效区间。本批不能为尚无可信数据的能力制造空接口。

## 5. 响应契约

两个接口使用统一结构：

```json
{
  "data": {
    "graph_version": {
      "id": "graph-version-uuid",
      "version_no": 3,
      "published_at": "2026-08-06T10:00:00Z"
    },
    "nodes": [
      {
        "id": "job-role-uuid",
        "type": "job_role",
        "name": "AI 自动化测试工程师",
        "properties": {
          "status": "active",
          "description": "建设 AI 产品自动化测试体系"
        }
      },
      {
        "id": "capability-uuid",
        "type": "capability",
        "name": "Python",
        "properties": {
          "status": "active",
          "skill_type": "language"
        }
      }
    ],
    "edges": [
      {
        "id": "sha256-relation-key",
        "type": "requires",
        "source": "job-role-uuid",
        "target": "capability-uuid",
        "properties": {
          "importance": 1.0
        }
      }
    ],
    "truncated": false
  }
}
```

节点类型固定为：

- `domain`
- `job_role`
- `capability`

关系类型固定为：

- `belongs_to`
- `requires`
- `bonus`

节点 ID 使用 PostgreSQL UUID。Edge ID 必须使用发布阶段写入的 SHA256 `relation_key`；缺少 relation_key 视为投影不一致，不临时合成新 ID。

响应不返回：

- Proposal Snapshot。
- Review Decision。
- Evidence 和原始 JD。
- Neo4j 内部查询、地址、账号或异常文本。
- PostgreSQL 内部审计账本。

## 6. 全局图查询流程

### 6.1 PostgreSQL 前置校验

1. 查询 `status=published AND is_current=true` 的 GraphVersion。
2. 不存在时返回 `GRAPH_VERSION_NOT_PUBLISHED`。
3. 传入 domain_id 时，验证该 Domain 存在且 `status=active`；否则返回 `GRAPH_DOMAIN_NOT_FOUND`。

### 6.2 Neo4j 查询

全局查询分为两个只读 Cypher，避免构造一条难以测试和维护的大查询：

1. 查询岗位及岗位所属 Domain，稳定排序后读取 `max_job_roles + 1` 项，用额外一项判断岗位是否截断。
2. 根据已选 JobRole ID 查询 `REQUIRES/BONUS` Capability、Capability Domain 和对应关系。

第二步设置内部关系行安全上限 `max_job_roles * 40 + 1`。其中 40 来自当前岗位定义最多 20 个必备技能和 20 个加分技能；该参数不暴露给调用方。读取额外一行用于判断溢出，超过上限时只返回边端点均存在的有限子图，并设置 `truncated=true`。

### 6.3 标准化

Python 层执行：

1. 根据 `(node_type, id)` 去重节点。
2. 根据 relation_key 去重关系。
3. 按节点类型、名称、UUID 稳定排序节点。
4. 按关系类型、source、target、relation_key 稳定排序关系。
5. 限制唯一 Capability 数量为 max_capabilities。
6. 删除 source 或 target 未包含在返回节点中的关系。
7. 岗位溢出、技能溢出或内部关系行溢出时返回 `truncated=true`。

指定有效 Domain 但没有岗位时，返回空 nodes/edges 和 `truncated=false`，不视为错误。未指定 Domain、已有 current GraphVersion 但 Neo4j 完全没有 active JobRole 时，返回 `GRAPH_PROJECTION_INCONSISTENT`。

## 7. 岗位子图查询流程

1. PostgreSQL 查询目标 JobRole。
2. JobRole 不存在或不是 active 时返回 `GRAPH_JOB_ROLE_NOT_FOUND`。
3. 查询 current published GraphVersion；不存在时返回 `GRAPH_VERSION_NOT_PUBLISHED`。
4. Neo4j 按 PostgreSQL JobRole UUID 查询岗位、岗位 Domain、全部 `REQUIRES/BONUS` Capability 和 Capability Domain。
5. Neo4j 找不到该岗位时返回 `GRAPH_PROJECTION_INCONSISTENT`。
6. 标准化、去重、稳定排序后返回，不设置业务分页。

若岗位存在但没有任何技能关系，仍返回岗位和岗位 Domain；这允许前端展示空能力岗位，同时暴露真实数据状态。

## 8. 错误处理

| 错误码 | HTTP | 条件 |
| --- | ---: | --- |
| GRAPH_VERSION_NOT_PUBLISHED | 404 | 没有 current published GraphVersion |
| GRAPH_DOMAIN_NOT_FOUND | 404 | domain_id 不存在或不是 active |
| GRAPH_JOB_ROLE_NOT_FOUND | 404 | JobRole 不存在或不是 active |
| GRAPH_PROJECTION_INCONSISTENT | 503 | PostgreSQL 正式事实在 Neo4j 中缺失或关系缺少稳定 ID |
| GRAPH_READ_FAILED | 503 | Neo4j 连接或查询失败 |

Neo4j 驱动异常统一转换为 `GRAPH_READ_FAILED`，API 不返回原始异常消息。内部日志只记录异常类型，不记录密码或完整连接串。

## 9. 代码边界

新增：

```text
backend/app/graph/query.py
backend/tests/test_graph_query.py
backend/tests/test_graph_read_api.py
```

修改：

```text
backend/app/graph/router.py
backend/app/graph/schemas.py
backend/app/api/router.py
README.md
```

`query.py` 只负责正式状态校验、Neo4j 只读查询、结果标准化和稳定错误转换。现有 `graph/service.py` 继续只负责 GraphVersion 创建与发布，不继续扩大职责。

不新增第三方依赖，不增加数据库表，不创建 Alembic Migration。

## 10. 测试与验收

### 10.1 Query Service

使用 Fake Async Driver 覆盖：

- 全局图节点和关系映射。
- Domain 筛选参数。
- 节点和 relation_key 去重。
- 岗位和技能截断。
- dangling edge 清除。
- 岗位局部图 required/bonus 映射。
- PostgreSQL 无 current GraphVersion。
- PostgreSQL 无目标 Domain 或 JobRole。
- Neo4j 缺少正式投影。
- Neo4j 异常脱敏。

### 10.2 API

覆盖：

- applicant、hr、admin 均可读取。
- 未登录返回认证错误。
- GET 不要求 CSRF。
- 参数范围由 FastAPI 校验。
- 稳定的 404 和 503 错误码。
- 响应中不包含 Evidence、原始 JD、Proposal Snapshot 和内部连接信息。

### 10.3 完整门禁

完成前执行：

```text
docker compose config -q
uv run pytest -q
uv run ruff check .
uv run alembic check
git diff --check
```

另外连接本地 Neo4j 5，对全局图和岗位子图 Cypher 执行只读 `EXPLAIN`。不向真实 Neo4j 写测试节点，不删除 PostgreSQL、Neo4j 或文件 Volume。

## 11. 完成定义

满足以下条件即认为 Batch F 完成：

1. 两个 authenticated Graph Read API 可用。
2. 返回结构能直接供前端构建全局图和岗位局部图。
3. 全局图有确定性限制与 truncated 标记。
4. PostgreSQL 与 Neo4j 投影不一致时返回稳定错误。
5. 全量测试、Ruff、Compose、Alembic 和真实 Neo4j EXPLAIN 全部通过。
6. README 提供可执行 curl 和当前功能边界。
