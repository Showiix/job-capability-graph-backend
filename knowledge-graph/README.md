# 知识图谱说明

本目录保存岗位-技能知识图谱相关文件。

## 结构

```text
knowledge-graph/
├── scripts/
│   └── load_jd_data.py
├── generated/
│   └── jd_graph_data.json
└── legacy-artifacts/
```

## 当前图谱产物

`generated/jd_graph_data.json` 是前端 3D 图谱消费的数据结构：

- `stars`：岗位类别节点
- `planets`：技能节点
- `metadata`：总 JD 数、岗位类别数、平台来源统计、默认展示岗位等

当前统计：

- 112 个岗位类别
- 1,120 个技能节点
- 59,430 条 JD

## 生成逻辑

`scripts/load_jd_data.py` 会递归读取 `merged_data` 下的 CSV，做以下处理：

- 去除平台文件名前缀，聚合同名岗位
- 提取职位标题、技能要求、技术标签中的技能关键词
- 为部分岗位补充稳定的核心技能映射
- 生成 3D 星图所需的岗位节点、技能轨道和默认热门新兴岗位

默认读取项目根目录下的 `data/merged_data`，并同步写入：

- `backend/backend/app/graph/jd_graph_data.json`
- `frontend/public/jd_graph_data.json`

如需改路径，可通过环境变量覆盖：

```bash
JD_MERGED_DATA_DIR=/path/to/merged_data python3 knowledge-graph/scripts/load_jd_data.py
```
