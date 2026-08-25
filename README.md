# Personalized Adaptive Learning Agent

一个以真实学习记录为核心的个性化学习系统。Web SaaS 提供课程工作区、今日任务、学习计划、练习与错题、知识掌握度、RAG 资料库和 Learning Agent；Windows 桌面端提供本地学习能力，并可通过受保护的伴侣 API 接入同一学习空间。

产品闭环：目标 -> 计划 -> 任务 -> 练习 -> 作答记录 -> 错题与间隔复习 -> 知识掌握度 -> 今日建议。

![学习闭环](docs/images/learning-workflow.svg)

## 已验收的 Web 功能

- 注册、登录、刷新令牌和退出登录
- 课程、目标、知识点、任务和课程笔记的创建、编辑、完成与删除
- 今日任务、任务开始/完成/跳过、来源课程和知识点跳转
- 学习资料上传、SHA-256 去重、资料预览和后台索引
- 基于已索引资料的 RAG 证据检索
- 基于证据生成可审核的练习题草稿
- 单选题、多选题作答记录、结果判定、错题和间隔复习
- 学习分析、CSV 导出、后台任务状态和审计日志
- Agent 会话、工具权限、记忆确认和受控写入

## 真实运行页面

以下图片来自本地 Web 运行验收流程，使用隔离演示账号和演示资料，不包含个人学习数据。图片展示的是实际页面状态，不是静态设计稿。

### 资料上传、索引与 RAG 证据

![资料库、上传和索引](docs/images/runtime-rag-workflow.png)

### 基于证据生成 AI 练习题

![AI 题目草稿和证据引用](docs/images/runtime-practice-workflow.png)

> 演示资料必须先完成索引，题目生成只允许引用已索引证据；没有可用证据时，页面会暂停并要求补充资料，不会生成无依据的题目。

## SaaS 本地启动

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.saas.yml up -d --build
docker compose -f docker-compose.saas.yml run --rm migrate python -m alembic current
python scripts/smoke_test_saas.py --base-url http://127.0.0.1:8000
```

打开 <http://127.0.0.1:8000/web/>，先注册隔离账号再登录。`smoke_test_saas.py` 会实际覆盖登录、课程、目标、任务、练习、资源上传、RAG、AI 任务、Agent、笔记和分析接口。

生产环境请使用真实密钥、HTTPS、独立数据库、Redis 和对象存储，并阅读 [生产发布手册](docs/PRODUCTION_RELEASE.md)。

## Windows 桌面端

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m app.main
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

构建 Windows 发布包：

```powershell
python scripts/build_windows.py
python scripts/smoke_test_release.py app\PersonalLearningDesktop\PersonalLearningDesktop.exe
```

更多分层设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。
