# AI 评估结果汇总

## 本次范围

本次为可重复的基线评估。真实执行了 SQLite FTS5 关键词检索、工具注册与调用、检索层鲁棒性输入，以及基础指标函数校验。在线 LLM 已对 3 条规则样本发起真实请求，但均因 `APIConnectionError` 失败；错误与耗时已保存在原始结果中。 未使用默认 FastEmbed 模型。

## 测试集来源

本次测试集位于 `evaluation/datasets/`，版本为 `evaluation-datasets-v1`。所有样本均为人工编写的功能契约样本，不含用户课程或个人数据：

- `llm_tasks.jsonl`：3 条算术、格式遵循与确定性指令样本；仅用于小规模规则校验。
- `retrieval_tasks.jsonl`：3 条高等数学概念检索样本；相关片段由运行器写入隔离 SQLite 基准库后映射为真实 chunk id。
- `tool_tasks.jsonl`：2 条只读工具成功样本和 1 条路径越界拒绝样本。
- `robustness_tasks.jsonl`：空输入、空白输入、噪声、Prompt Injection 字符串的检索层安全样本。

这些样本用于验证框架和项目功能边界，不能解释为真实用户数据上的模型能力。RAG 质量、LLM 质量和 Agent 规划质量需后续从脱敏课程资源中抽样并由人工标注标准答案、相关 chunk 与工具轨迹。

## 工具

本轮使用：项目 `ToolRegistry`、SQLite FTS5、SQLAlchemy、LangChain OpenAI 客户端、Python `time.perf_counter`、`statistics`、JSONL/CSV 标准库。项目已有 `pytest` 可用于功能回归，但本报告的数值来自本次运行器。

当前缺少：FastEmbed、psutil、GPU 监控和 matplotlib。Embedding、向量检索、端到端 RAG、资源、GPU 和图表为 `unavailable`；LLM 正确性、TTFT、tokens/s、Token 和成本因 API 连接失败而为 `unavailable`。

## 执行摘要

- 记录总数：18
- 完成：11
- 失败：3
- 不可用模块记录：4

## 关键词检索结果

| 样本 | Recall@3 | Precision@3 | Hit Rate@3 | MRR | NDCG@3 | 平均延迟 ms | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| retrieval-001 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.6138 | 0.8877 |
| retrieval-002 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.4237 | 0.4772 |
| retrieval-003 | 1.0000 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.4084 | 0.4343 |

## LLM 规则基准结果

该组仅包含 3 条人工编写的确定性样本，用于测量本次配置下的基础正确性、指令和格式遵循，以及非 streaming 总延迟；不能外推为通用推理或 RAG 能力。

| 样本 | 正确性 | 指令遵循 | 格式遵循 | 总延迟 ms |
|---|---:|---:|---:|---:|
| llm-001 | unavailable | unavailable | unavailable | unavailable |
| llm-002 | unavailable | unavailable | unavailable | unavailable |
| llm-003 | unavailable | unavailable | unavailable | unavailable |

## 工具调用结果

| 样本 | 契约通过 | 工具成功 | 平均延迟 ms | 说明 |
|---|---:|---:|---:|---|
| tool-001 | 1.0000 | 1.0000 | 5.1751 | 符合预期 |
| tool-002 | 1.0000 | 1.0000 | 5.6471 | 符合预期 |
| tool-003 | 1.0000 | 0.0000 | 5.0888 | 符合预期 |

## 未完成指标

| 范围 | 指标 | 状态 | 原因 |
|---|---|---|---|
| LLM | 正确性、相关性、完整性、指令遵循、多轮一致性 | unavailable | 三次真实请求均为 APIConnectionError，且没有人工标注任务集 |
| Embedding / 向量检索 | 吞吐、Recall@K、MRR、NDCG | unavailable | 当前 Python 环境缺少 `fastembed` |
| RAG 生成 | Context Precision/Recall、Faithfulness、幻觉率、端到端延迟 | unavailable | FastEmbed 缺失且在线 LLM 连接失败，没有 RAG 标注集和 Judge 配置 |
| Agent | 任务完成率、工具选择正确率、循环检测 | unavailable | 当前 Agent 编排是确定性步骤，本轮没有 LLM 规划轨迹测试集 |
| 运行性能 | TTFT、tokens/s、Input/Output Token、成本 | unavailable | LLM 请求未成功，且本轮使用非 streaming 调用 |
| 资源 | CPU、内存、GPU、显存 | unavailable | 缺少 `psutil` / GPU 监控依赖 |

## 结论与下一步

本轮可确认关键词检索、只读工具调用和检索层异常输入能在隔离基准环境下真实运行；具体数值见上表和 `raw.jsonl`。在线 LLM 实验已真实发起但发生连接错误，因此不能判断哪个 LLM 最好、最快或最便宜。

下一步先修复模型 API 连通性，再安装 FastEmbed 和 psutil，随后建立脱敏人工标注的 RAG/Agent 测试集，以相同数据集运行模型、Prompt、Embedding 和 RAG 参数矩阵。

## 结果文件

- `raw.jsonl`：逐样本原始输入、输出、指标、错误和元数据。
- `summary.csv`：便于表格查看的摘要。
- `config.json`：数据集哈希、运行环境和使用工具。
