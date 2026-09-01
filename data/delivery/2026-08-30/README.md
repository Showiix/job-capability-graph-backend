# 小挑 2026-08-30 数据交付

该目录保存外部算法团队提供的版本化数据资产，不是数据库备份，也不应绕过现有
Catalog、Review、GraphVersion 和 Neo4j 发布流程直接写入生产。

## 文件

- `catalog_job_roles.json`：112 个岗位目录输入。
- `catalog_capabilities.json`：6031 个能力目录输入；短标识和实体类型污染仍需审核。
- `catalog_seed.sql`：空演示库一次性初始化 Catalog 与 published Graph 水位。
- `job_role_capabilities_map.json`：4368 条岗位能力聚合关系。
- `capability_updates_enriched.json`：524 个岗位、4007 条能力演化候选及 JD 证据。
- `phase1_time_lag_report.json`：GitHub 公开仓库信号到 JD 时间窗口的近似结果。
- `测试数据样例.json`：1 个新岗位和 1 个既有岗位演化样例。
- `三项准确率_测试集.json` 及 Markdown 报告：原团队评估产物。

## 使用

Catalog 文件继续使用现有 `/api/v1/catalog/imports` 审核导入流程。能力演化候选使用：

```bash
cd backend
uv run python -m scripts.import_capability_updates --actor <admin-username> --dry-run
uv run python -m scripts.import_capability_updates --actor <admin-username>
```

导入是幂等的；同一来源版本、岗位、能力和变化类型生成稳定 UUID，重复执行只跳过已存在
候选。所有变化默认进入 `pending`，不直接修改正式 Catalog 或 Neo4j。

全新演示环境如果岗位推荐提示 `GRAPH_VERSION_NOT_PUBLISHED`，先创建 admin，再在仓库根目录
对空库执行一次：

```bash
psql "postgresql://job_graph:job_graph_dev@127.0.0.1:5432/job_graph" \
  -v ON_ERROR_STOP=1 \
  -f data/delivery/2026-08-30/catalog_seed.sql
```

该 SQL 仅用于空演示库初始化；已有正式 Catalog/Graph 的环境不要执行。普通 Applicant 不需要
登录，也不负责执行初始化。

## 证据边界

- “JD 证据覆盖率 100%”只表示变化能力能在相关 JD 中找到证据，不等于变化方向已被独立验证。
- GitHub 同名仓库创建日是公开仓库信号时间，不是技术真正首发时间。
- 原三项准确率报告保留作来源记录；正式验收仍需真实 API、独立人工标签和冻结测试集。
- 原交付包中的真实简历、默认管理员密码、旧增量源码和初始化 SQL 未纳入仓库。
