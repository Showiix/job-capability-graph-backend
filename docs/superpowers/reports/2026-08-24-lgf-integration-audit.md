# LGF 匹配模型接入审计

## 审计结论

远端 `origin/main` 当前仍为 `4ca2704`，没有发现 LGF 新提交或可直接合并的模型服务代码。远端的 applicant matching、HR recruitment、graph 和 discovery 分支均已存在，但不包含 LGF 专用接口。

本次按已提供的“人岗匹配前端交付包”实现了可选的内部 LGF 适配：LGF 的 `POST /match` 结果作为 HR 匹配结果中的外部模型信号保存，不改变现有五维 `match_weights_v1` 的总分和排序。

## 接入边界

```text
候选简历 PDF/DOCX
  -> 本后端解析为 CandidateProfile/CandidateSkill
  -> 本后端五维确定性匹配
  -> 可选调用 LGF POST /match
  -> MatchResult.dimension_scores.lgf
```

LGF 不负责文件解析、姓名提取、权限、数据库持久化、审核或 Neo4j 发布。

## 配置

```dotenv
LGF_ENABLED=false
LGF_MATCH_URL=http://algorithm:8001/match
LGF_API_KEY=
LGF_TIMEOUT_SECONDS=15
```

API Key 只能通过部署环境注入，不能写入仓库、测试快照、日志或前端。用户在聊天中贴出的 Key 应立即撤销并重新生成。

## 当前输出

开启后，HR 结果中的 `dimension_scores` 增加：

```json
{
  "lgf": {
    "status": "ok",
    "score": 0.84,
    "match_level": "match",
    "error_code": null
  }
}
```

状态包括 `disabled`、`ok` 和 `degraded`。降级不会阻塞原有匹配。

## 已知契约风险

交付包的 `/match` 请求要求 `job_id` 命中它自己的 `jobs.json`。当前后端的招聘项目只有标题，没有 LGF 外部岗位 ID，因此暂时使用 `confirmed_requirement_snapshot.job_id`，没有时回退到项目标题。若标题与 LGF 岗位 ID 不一致，LGF 会降级，但不影响本后端原有匹配结果。

拿到最新版接口后，应优先确认：岗位 ID 是否仍由 LGF 内部岗位表决定、是否支持直接传岗位定义、是否支持批量候选人、分数范围和校准集、模型版本、鉴权、超时和错误契约。

## 验证

- LGF client 成功响应解析测试通过。
- LGF 非法响应降级测试通过。
- 原有 recruitment matching 和 scoring 测试通过，共 36 个测试通过。
- 未使用用户提供的 API Key。
