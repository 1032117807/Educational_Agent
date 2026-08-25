# 多人 SaaS 重构

## 已落地的基础

- `server/` 是 FastAPI 服务端入口，保留桌面端以便渐进迁移。
- PostgreSQL URL、Redis 和对象存储配置在 `.env` 中管理。
- `organizations`、`users`、`organization_members`、`refresh_tokens` 已有 Alembic 迁移。
- 核心课程、资源、索引、切片和 AI 运行记录已新增可索引的 `tenant_id`。
- `/health/live`、`/health/ready`、`/health/config`、`/v1/auth/register`、`/v1/auth/login`、`/v1/me` 已定义。
- 课程、任务、题库、学习目标、知识点和练习会话已通过 `/v1` API 迁移；查询、外键校验和写入均从 JWT 组织上下文取得并强制使用 `tenant_id`。
- `g6_tenant_join_records` 为练习题关联、练习作答、复习作答和任务重复规则补齐租户字段与索引，便于后续执行数据库 RLS。
- 资源上传 API 把文件写入 S3/MinIO，随后创建 `index_resource` 后台任务；API 不直接执行解析或 embedding。
- `pgvector` 的 `document_embeddings` 表按租户和 embedding 版本隔离，并创建 HNSW 余弦索引。
- `rag_question` worker 先执行 pgvector 证据检索并持久化 `AIRun/AICitation`；生成模型调用可在此基础上单独启用和评估。

## 本地启动

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.saas.yml up -d --build
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<database>"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn server.main:app --reload
.\.venv\Scripts\python.exe -m server.run_worker
```

### 历史数据迁移

旧桌面数据库必须先归属到一个组织，才能把租户字段收紧为非空并启用 RLS。迁移工具默认只预览，不会写数据：

```powershell
\.\.venv\Scripts\python.exe scripts\backfill_legacy_tenant.py `
  --database-url "postgresql+psycopg://user:password@host:5432/learning" `
  --tenant-id "11111111-1111-4111-8111-111111111111" `
  --organization-name "Legacy workspace"
```

确认 `pending_rows` 与备份一致后，再加 `--apply` 执行。`--apply` 只更新 `tenant_id IS NULL` 的记录；已有租户数据不会被覆盖，重复执行应显示 `changed_rows: 0`。可用 `--owner-email` 把已有用户加入该组织，邮箱不存在时命令会拒绝执行。随后执行 `g8_postgres_rls` 时，历史 `ai_citations` 会按所属 `ai_runs.tenant_id` 自动回填，才会启用 RLS。

`g9_worker_job_rls` 为 `background_jobs` 增加了受控 worker 会话标记，使一个 worker 能跨组织领取队列任务；它不放开其他业务表。API 与 worker 使用的 PostgreSQL 运行账号必须不是表 owner，且不得拥有 `BYPASSRLS`；迁移应由单独的部署账号执行。否则 PostgreSQL 会绕过 RLS，租户隔离不成立。`docker-compose.saas.yml` 已将这两类账号分开：`POSTGRES_PASSWORD` 仅用于 `migrate` 容器，`APP_DB_USER` / `APP_DB_PASSWORD` 仅用于 API 与 worker。全新卷由初始化脚本创建运行角色；迁移容器随后运行 `scripts/grant_saas_runtime_role.py`，会在已有库中自动创建缺失的非 owner 运行角色、拒绝 superuser、建库/建角色、`BYPASSRLS` 或从高权限父角色继承权限的账号，并授予表/序列权限，因此可重复执行。

`g10_tenant_not_null` 在 RLS 校验完成后将所有 SaaS 业务表的 `tenant_id` 收紧为 `NOT NULL`。这是生产数据不变量：若迁移失败提示 NULL 行，必须先使用回填工具修复数据并复核，不应跳过该迁移或手工关闭约束。

在另一个终端验证 PostgreSQL/pgvector/RLS 迁移。该脚本会校验 vector 扩展、HNSW 索引、每个 SaaS 表的 `tenant_id NOT NULL` 与 RLS，以及 `APP_DB_USER` 没有高权限、直接或嵌套特权角色继承、数据库 owner 或 `public` 关系 owner 权限：

```powershell
.\.venv\Scripts\python.exe scripts\verify_saas_integration.py
```

生产 Compose 最小环境变量如下。不要保留任何 `replace-with-*` 或 `change-me-*` 默认值：

```dotenv
APP_ENV=production
SECRET_KEY=<at-least-32-random-characters>
POSTGRES_PASSWORD=<migration-role-password>
APP_DB_USER=learning_app
APP_DB_PASSWORD=<non-owner-runtime-role-password>
OBJECT_STORAGE_ACCESS_KEY=<minio-or-s3-service-account>
OBJECT_STORAGE_SECRET_KEY=<service-account-secret>
CORS_ORIGINS=https://app.example.com
```

`worker` 需要可用 embedding 模型。Compose 默认设置 `LEARNING_AI_EMBEDDING_LOCAL_FILES_ONLY=false`，允许 FastEmbed 首次下载模型。生产环境有两种可选方式：

1. 本地模型：将模型目录作为镜像构建内容或只读挂载到 `LEARNING_AI_EMBEDDING_MODEL_DIR`，并设为 `true`。不需要 embedding API Key。
2. 托管 embedding：使用供应商的 embedding API 并配置对应 API Key。当前 `FastEmbedEmbeddings` 只实现本地模型；接入托管 embedding 前不要仅修改环境变量。

打开 `http://127.0.0.1:8000/docs` 查看 API 文档。生产环境必须由 CI 在应用发布前执行迁移；不能让 API 进程自动改表。
部署后可访问 `/health/config` 确认非敏感配置是否完整；响应不包含任何密钥值。

### Web 客户端

API 同域提供轻量 Web 客户端，地址为 `/web/`。当前覆盖注册/登录、组织身份显示、仪表盘、课程、任务、学习目标、知识点、题目创建、选题练习、逐题作答、待复习记录、资料上传、索引任务轮询、RAG 检索和团队成员管理。学习目标和知识点页面不会提交 tenant ID，服务端始终从 JWT 的组织上下文决定数据归属。浏览器 access/refresh token 都只放在 `sessionStorage`，关闭标签页即清除；access token 收到一次 `401` 时会使用 refresh token 轮换并重试，退出时会吊销 refresh token。RAG 始终持久化 pgvector 证据和引用；若 `LEARNING_AI_ENABLED=true` 且已配置 `LEARNING_AI_API_KEY`，worker 会基于这些证据生成带 `[编号]` 引用的回答。生成文本必须至少引用一条证据，且每个编号都属于本次检索结果；否则降级为 evidence-only 检索。团队页中只有 owner/admin 可添加、修改或移除成员；当前只允许添加已注册账号，因此不需要邮件服务 Key。生产环境建议将前端与 API 部署在同一主域；若拆分域名，必须用 `CORS_ORIGINS` 显式允许前端域名。若需要进一步降低 XSS 中 token 读取风险，可将 refresh token 迁移为同源 `HttpOnly; Secure; SameSite` cookie，再调整 CSRF 防护。若后续增加邮件邀请，再配置 SMTP 或 Resend/SendGrid API Key。

### 已迁移的学习 API

| 资源 | API |
|---|---|
| 课程 | `GET/POST /v1/courses` |
| 仪表盘 | `GET /v1/dashboard?start=YYYY-MM-DD&end=YYYY-MM-DD&course_id=<optional>` |
| 审计事件 | `GET /v1/audit-events` |
| 组织成员 | `GET /v1/organization/members`、`POST /v1/organization/members`、`PATCH/DELETE /v1/organization/members/{user_id}` |
| 学习任务 | `GET/POST /v1/tasks`、`POST /v1/tasks/{task_id}/complete` |
| 题库 | `GET/POST /v1/questions` |
| 学习目标 | `GET/POST /v1/goals` |
| 知识点 | `GET/POST /v1/knowledge-points` |
| 练习 | `POST /v1/practice-sessions`、`POST /v1/practice-sessions/{session_id}/questions/{question_id}/attempts`、`POST /v1/practice-sessions/{session_id}/complete` |
| 错题复习 | `GET /v1/reviews`、`POST /v1/reviews/{item_id}/attempts`、`GET /v1/reviews/{item_id}/attempts` |
| 学习记录 | `GET/POST /v1/study-sessions`、`POST /v1/study-sessions/{session_id}/finish` |
| 文件与 RAG | `GET/POST /v1/resources`、`POST /v1/rag/jobs`、`GET /v1/jobs/{job_id}` |
| RAG 运行详情 | `GET /v1/ai-runs/{run_id}` |

练习提交以 `(session_id, question_id, tenant_id)` 更新同一道题的最新答案；会话完成时服务端重新计算正确数与总用时，客户端不得直接提交汇总成绩。
仪表盘的日期窗口最多 90 天，返回学习时长、任务完成量、练习正确率、复习状态和按日学习时长；全部统计均限定于当前 JWT 的组织。
RAG 任务完成后可用 `ai_run_id` 查询回答、检索模式和按编号排列的引用摘录；AI run 与 citation 均按租户过滤，Web 页面会将回答中的 `[编号]` 与资料摘录一起呈现。
关键创建、完成、作答及复习操作会写入 `audit_events`；审计查询仅返回当前组织的事件，且不存储密码、JWT、API Key 或原始上传文件内容。
组织成员接口实时读取成员角色；只有 `owner/admin` 可以邀请已注册用户、修改或移除成员，普通 `member` 只能查看成员。不能移除自己、降级 owner 或移除 owner。当前邀请不发送邮件，未注册邮箱会被拒绝，正式上线可再接邮件邀请和 OAuth。

## 密钥与 API Key

| 配置 | 是否必需 | 用途 | 说明 |
|---|---|---|---|
| `SECRET_KEY` | 必需 | JWT 签名 | 用密码管理器生成 32 字节以上随机值；不是第三方 API Key。 |
| `DATABASE_URL` | 必需 | PostgreSQL | 数据库密码属于基础设施密钥。 |
| `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` | 生产必需 | S3/MinIO 文件存储 | MinIO 本地开发可用 Compose 中的管理员凭据；生产应使用最小权限服务账号。 |
| `LEARNING_AI_API_KEY` | 使用云端大模型时必需 | 问答、抽取、出题、批改、报告 | 使用 OpenAI 或兼容供应商的一把服务端 Key。前端和桌面端都不能保存它。 |
| Embedding API Key | 取决于实现 | 向量化 | 当前 `FastEmbed + BAAI/bge-small-zh-v1.5` 是本地模型，**不需要 API Key**；若改用 OpenAI/Cohere 等托管 embedding，才需要其 Key。 |
| `TAVILY_API_KEY` | 可选 | 联网检索 | 仅在启用研究/网页搜索时需要。 |
| Redis 密码 | 生产必需 | 队列、缓存、限流 | SaaS Compose 通过 `REDIS_URL` 使用认证连接；生产环境必须配置强密码。 |

不要把真实 Key 写进 Git、前端打包产物、桌面安装包、日志或数据库。当前本机 `.env` 若包含已泄露的密钥，应立刻到对应供应商控制台吊销后生成新 Key。

### 分布式限流

API 使用 Redis `INCR + EXPIRE` 进行多实例共享的固定窗口限流。默认普通 API 为每 IP 每 60 秒 120 次，`/v1/auth/*` 为每 IP 每 60 秒 10 次；Redis key 仅包含客户端 IP 的哈希，不保存原始地址。可以通过以下环境变量调整：

```dotenv
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
AUTH_RATE_LIMIT_REQUESTS=10
AUTH_RATE_LIMIT_WINDOW_SECONDS=60
CORS_ORIGINS=https://app.example.com
```

生产环境必须启用限流；Redis 连接失败时 API 返回 `503 rate limiter unavailable`，而不是静默跳过限流。若服务部署在反向代理后，代理必须只为受信任的上游设置 `X-Forwarded-For`。

### Web 前端跨域

浏览器前端通过 `CORS_ORIGINS` 指定允许调用 API 的域名，例如 `https://app.example.com,https://staging.example.com`。生产环境禁止使用 `*`，并只允许 `Authorization`、`Content-Type` 请求头和 `GET/POST/PATCH/DELETE/OPTIONS` 方法。CORS 不是 API Key，也不应当替代 JWT 鉴权。

### 最小生产变量集

```dotenv
APP_ENV=production
SECRET_KEY=<至少32字符的随机值>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<database>
REDIS_URL=redis://:<password>@<host>:6379/0
OBJECT_STORAGE_ENDPOINT=https://<s3-or-minio-endpoint>
OBJECT_STORAGE_BUCKET=learning
OBJECT_STORAGE_ACCESS_KEY=<storage-access-key>
OBJECT_STORAGE_SECRET_KEY=<storage-secret-key>
LEARNING_AI_ENABLED=true
LEARNING_AI_PROVIDER=openai
LEARNING_AI_API_KEY=<llm-provider-key>
LEARNING_AI_BASE_URL=<optional-openai-compatible-url>
LEARNING_AI_CHAT_MODEL=<chat-model-name>
LEARNING_AI_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
LEARNING_AI_EMBEDDING_LOCAL_FILES_ONLY=true
LEARNING_AI_EMBEDDING_MODEL_DIR=/opt/models/bge-small-zh-v1.5
LEARNING_AI_EMBEDDING_DIMENSIONS=512
```

本地 embedding 方案没有 embedding API Key，但运行节点必须有模型文件和足够 CPU/RAM。若使用托管 embedding，请额外配置供应商的 embedding API Key，并将 `LEARNING_AI_EMBEDDING_LOCAL_FILES_ONLY=false`。
当前 `document_embeddings` 的 pgvector schema 是 `vector(512)`，因此只能使用 512 维 embedding；切换 384/768/1536 等维度需要先发布新的数据库迁移，并对全部资料重新建索引。回填工具只需要 PostgreSQL 数据库凭证，不需要大模型或 embedding API Key。

## 历史迁移路线与运营项

以下路线已经落地到当前代码和迁移链：业务表租户隔离、S3/MinIO 对象存储、Redis worker、pgvector 检索、越权回归测试、分布式限流，以及 `tenant_id NOT NULL` 与数据库 RLS。历史数据回填仍必须按部署手册先预览、备份、审核 `pending_rows`，再执行迁移。

正式运营还需要在真实环境完成 OAuth/邮件验证（如果产品需要）、备份恢复演练、监控告警、HTTPS 域名和 Windows 代码签名；这些不是本地单测可以替代的验收项。

## 当前验收状态

### CI Infrastructure Gate

`.github/workflows/saas-integration.yml` starts the full Compose stack on GitHub Actions with production-mode, non-secret CI values. It waits for `/health/ready` and runs `scripts/verify_saas_integration.py` to validate pgvector, RLS, tenant constraints, and the non-owner runtime database role. No LLM or embedding API key is required for this gate.

Production Redis requires a URL-safe `REDIS_PASSWORD` (letters, numbers, `.`, `_`, `~`, `-` only) and a `REDIS_URL` containing the same password. Compose starts Redis with `--requirepass`; the API and worker connect through the authenticated URL. Redis is used for shared rate limiting and must not be exposed without authentication.


- FastAPI 导入检查：通过。
- 身份、JWT、任务队列、对象 key 和索引 worker 单测：通过。
- 现有向量、混合检索、引用 RAG 和 ingestion 回归：通过。
- 本机已完成 Docker Compose PostgreSQL/pgvector、Redis、MinIO、API/worker 的真实集成验证，并通过 `scripts/verify_saas_integration.py` 与 `scripts/smoke_test_saas.py`。这不替代正式环境的域名、真实密钥、备份恢复演练、监控和代码签名验收。
- 仍需在正式环境完成的发布门槛：配置真实 HTTPS 域名与证书、执行并保留恢复测试、接入监控告警、配置邮件/OAuth（如产品需要），以及使用受信任证书签署 Windows 安装包。详见 `docs/PRODUCTION_RELEASE.md`。
