# 算法岗位定义接入完成报告

## 1. 目标

将算法同学离线生成的 `new_job_definitions.json` 接入现有后端，使算法岗位定义进入统一的人工审核和图谱发布流程。算法结果是候选事实，不直接修改标准技能库，也不直接写入 Neo4j。

## 2. 系统边界

本次接入复用现有 `GraphChangeCandidate -> ReviewDecision -> GraphVersion` 主链：

```text
new_job_definitions.json
-> 格式校验
-> 标准技能精确映射
-> GraphChangeCandidate(pending)
-> HR/Admin 审核
-> GraphVersion
-> PostgreSQL + Neo4j 发布
```

未接入算法脚本运行环境。算法仍可独立离线运行，后端只消费其稳定 JSON 结果。

## 3. API

```http
POST /api/v1/algorithm-results/job-definitions
Content-Type: multipart/form-data
Cookie: session=...
X-CSRF-Token: ...
```

权限：仅 `admin`。

表单字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | JSON 文件 | 算法生成的 `new_job_definitions.json`，最大 5 MB |

调用示例：

```bash
curl -sS -b /tmp/job-graph-cookies.txt \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -F 'file=@new_job_definitions.json;type=application/json' \
  http://127.0.0.1:8000/api/v1/algorithm-results/job-definitions
```

## 4. 输入契约

顶层必须包含非空 `definitions` 数组。每条定义至少需要：

```json
{
  "cluster_id": 1,
  "岗位名称": "大模型应用工程师",
  "核心职责": ["建设企业级 RAG 应用"],
  "必备技能": [
    {"skill": "Python", "support_pct_corrected": 0.8},
    {"skill": "RAG", "support_pct_corrected": 0.6}
  ],
  "加分技能": [{"skill": "Docker", "support_pct_corrected": 0.4}],
  "典型行业应用场景": [{"industry": "企业服务"}]
}
```

后端同时保留 `source_traceability`、`人工优化`、`_audit`、文件 SHA-256、算法生成时间和来源路径，供审核追溯。

## 5. 映射与审核规则

1. 技能只通过 active Capability 的标准名称或 active Alias 精确映射。
2. 未识别技能写入 `source_snapshot`，不自动创建 Capability。
3. 必备技能必须至少有两个映射到同一技术域，否则该岗位被跳过并返回原因。
4. 跨技术域的已映射必备技能降为加分技能，保证现有图谱发布约束可满足。
5. 导入结果统一创建为 `pending` 的 `create_job_role` 提案。
6. 相同文件 SHA-256 重复上传时复用已有提案，不重复写入。
7. 人工审核通过后才能创建并发布 GraphVersion。

## 6. 响应

```json
{
  "data": {
    "file_sha256": "...",
    "total_definitions": 189,
    "created_count": 120,
    "reused_count": 0,
    "skipped_count": 69,
    "proposal_ids": ["..."],
    "skipped": [],
    "review_queue_url": "/api/v1/review-proposals?status=pending"
  }
}
```

常见错误码：

| 错误码 | 含义 |
|---|---|
| `ALGORITHM_RESULT_EMPTY` | 文件为空 |
| `ALGORITHM_RESULT_TOO_LARGE` | 文件超过 5 MB |
| `ALGORITHM_RESULT_TYPE_UNSUPPORTED` | 文件不是 `.json` |
| `ALGORITHM_RESULT_INVALID` | JSON 或字段结构不合法 |
| `ALGORITHM_RESULT_NOT_IMPORTABLE` | 没有岗位满足最低标准技能映射要求 |

## 7. 验证结果

- Ruff lint：通过。
- Ruff format check：通过。
- 纯逻辑测试：2 passed。
- 真实 `new_job_definitions.json`：成功校验 189 条岗位定义。
- OpenAPI：确认注册 `POST /api/v1/algorithm-results/job-definitions`。
- PostgreSQL JSONB 幂等查询：方言编译通过。
- 数据库集成测试已编写；本机 `job_graph_test` 凭据与当前 PostgreSQL 实例不匹配，尚未执行成功。

## 8. 后续范围

本次只接入新岗位定义。`capability_graph_updates.json` 包含既有岗位技能边更新，而当前审核和发布模型只支持 `create_job_role`；后续需要先扩展受审核的 `update_job_role_capabilities` 变更类型，再接入该文件。
