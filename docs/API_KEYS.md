# API Key 与生产密钥清单

所有供应商凭据只能保存在服务端。不要将它们写入浏览器前端、桌面端安装包、源代码仓库或客户端 JavaScript。

## 部署必须配置的生产密钥

以下不是第三方 API Key，但生产环境必须为每个环境随机生成，并保存在密钥管理服务中：

| 变量 | 用途 | 是否必需 |
| --- | --- | --- |
| `SECRET_KEY` | JWT 签名 | 是 |
| `POSTGRES_PASSWORD` | Alembic 数据库迁移所有者 | 是 |
| `APP_DB_PASSWORD` | API 与 worker 的运行时数据库角色 | 是 |
| `REDIS_PASSWORD` | Redis 认证 | 是 |
| `OBJECT_STORAGE_ACCESS_KEY` | MinIO/S3 访问账号 | 是 |
| `OBJECT_STORAGE_SECRET_KEY` | MinIO/S3 认证密钥 | 是 |

不同开发、测试、预发和生产环境必须使用不同的随机值。运行时数据库账号不能复用迁移所有者的密码。

## 大模型 API Key

只有开启云端生成能力时才需要配置：

```dotenv
LEARNING_AI_ENABLED=true
LEARNING_AI_PROVIDER=openai
LEARNING_AI_API_KEY=<仅服务端保存的供应商密钥>
LEARNING_AI_CHAT_MODEL=gpt-4.1-mini
```

也可使用 OpenAI 兼容服务：设置 `LEARNING_AI_PROVIDER=openai_compatible`、`LEARNING_AI_BASE_URL`、`LEARNING_AI_API_KEY` 和该供应商的模型名称。此 Key 用于带证据引用的 RAG 回答及其他调用聊天模型的 AI 工作流。关闭生成能力时，RAG 仍会返回 pgvector 检索出的已持久化证据（`evidence_only`），不需要大模型 Key。

## Embedding 模型与 Key

当前实现使用本地 FastEmbed 模型 `BAAI/bge-small-zh-v1.5`，输出固定为 512 维，因此**不需要 embedding API Key**：

```dotenv
LEARNING_AI_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
LEARNING_AI_EMBEDDING_DIMENSIONS=512
LEARNING_AI_EMBEDDING_LOCAL_FILES_ONLY=true
```

开启本地只读模式时，模型文件必须已存在于 `LEARNING_AI_EMBEDDING_MODEL_DIR`。首次下载需要出网，但不需要模型供应商的 Key。

当前 `FastEmbedEmbeddings` 适配器尚未实现 OpenAI、Cohere 等托管 embedding。不能只增加环境变量或填写 Key 就认为托管 embedding 已启用。接入托管 embedding 需要：编写供应商适配器、配置供应商 Key、发布匹配的 `vector(n)` 数据库迁移，以及对所有资料全量重建索引。当前 pgvector schema 只接受 512 维向量。

## 可选联网搜索

`TAVILY_API_KEY` 仅在启用网页搜索工作流时需要；本地资料上传、索引及 RAG 检索均不依赖它。

## 最小配置组合

- 仅证据 RAG SaaS：配置上述生产密钥；不需要大模型、embedding 或 Tavily Key。
- AI 生成式 RAG：生产密钥加上 `LEARNING_AI_API_KEY`，并设置 `LEARNING_AI_ENABLED=true`。
- 联网研究：额外配置 `TAVILY_API_KEY`。
- 托管 embedding：当前尚不可用，需先完成适配器、数据库迁移与重建索引。

完整变量清单见 `.env.example`；部署和迁移流程见 `docs/SAAS_REFACTOR.md`。
