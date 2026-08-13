# AI 评估结果汇总

## 本次范围

本次为离线、可重复的基线评估。真实执行了 SQLite FTS5 关键词检索、工具注册与调用、检索层鲁棒性输入，以及基础指标函数校验。未调用在线 LLM，未使用默认 FastEmbed 模型。

## 测试集来源

本次测试集位于 `evaluation/datasets/`，版本为 `evaluation-datasets-v1`。所有样本均为人工编写的功能契约样本，不含用户课程或个人数据：

- `retrieval_tasks.jsonl`：3 条高等数学概念检索样本；相关片段由运行器写入隔离 SQLite 基准库后映射为真实 chunk id。
- `tool_tasks.jsonl`：2 条只读工具成功样本和 1 条路径越界拒绝样本。
- `robustness_tasks.jsonl`：空输入、空白输入、噪声、Prompt Injection 字符串的检索层安全样本。

这些样本用于验证框架和项目功能边界，不能解释为真实用户数据上的模型能力。RAG 质量、LLM 质量和 Agent 规划质量需后续从脱敏课程资源中抽样并由人工标注标准答案、相关 chunk 与工具轨迹。

## 工具

本轮使用：项目 `ToolRegistry`、SQLite FTS5、SQLAlchemy、Python `time.perf_counter`、`statistics`、JSONL/CSV 标准库。项目已有 `pytest` 可用于功能回归，但本报告的数值来自本次运行器。

未安装或未启用：FastEmbed、psutil、在线 LLM API、GPU 监控、matplotlib。因此 Embedding、向量检索、端到端 RAG、TTFT、tokens/s、成本、GPU 和图表均为 `unavailable`。

## 执行摘要

- 记录总数：15
- 完成：11
- 失败：0
- 不可用模块记录：4

## 关键词检索结果

| 样本 | Recall@3 | Precision@3 | Hit Rate@3 | MRR | NDCG@3 | 平均延迟 ms | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| retrieval-001 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.6083 | 0.8660 |
| retrieval-002 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.5071 | 0.5950 |
| retrieval-003 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.4780 | 0.5208 |

## 工具调用结果

| 样本 | 契约通过 | 工具成功 | 平均延迟 ms | 说明 |
|---|---:|---:|---:|---|
| tool-001 | 1.0000 | 1.0000 | 5.8745 | 符合预期 |
| tool-002 | 1.0000 | 1.0000 | 4.9764 | 符合预期 |
| tool-003 | 1.0000 | 0.0000 | 4.5332 | 符合预期 |

## 未完成指标

| 范围 | 指标 | 状态 | 原因 |
|---|---|---|---|
| LLM | 正确性、相关性、完整性、指令遵循、多轮一致性 | unavailable | 未配置在线/本地可运行 LLM 与人工标注任务集 |
| Embedding / 向量检索 | 吞吐、Recall@K、MRR、NDCG | unavailable | 当前 Python 环境缺少 `fastembed` |
| RAG 生成 | Context Precision/Recall、Faithfulness、幻觉率、端到端延迟 | unavailable | 没有可用 LLM、RAG 标注集和 Judge 配置 |
| Agent | 任务完成率、工具选择正确率、循环检测 | unavailable | 当前 Agent 编排是确定性步骤，本轮没有 LLM 规划轨迹测试集 |
| 运行性能 | TTFT、tokens/s、Input/Output Token、成本 | unavailable | 未运行返回 streaming/usage 的模型接口 |
| 资源 | CPU、内存、GPU、显存 | unavailable | 缺少 `psutil` / GPU 监控依赖 |

## 结论与下一步

本轮可确认关键词检索、只读工具调用和检索层异常输入能在隔离基准环境下真实运行；具体数值见上表和 `raw.jsonl`。不能根据本轮结果判断哪个 LLM 最好、最快或最便宜，因为没有实际 LLM 实验。

下一步应安装可选依赖并配置模型后，建立脱敏人工标注的 RAG/Agent 测试集，再以相同数据集运行模型、Prompt、Embedding 和 RAG 参数矩阵。

## 结果文件

- `raw.jsonl`：逐样本原始输入、输出、指标、错误和元数据。
- `summary.csv`：便于表格查看的摘要。
- `config.json`：数据集哈希、运行环境和使用工具。
