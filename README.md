# Personalized Adaptive Learning Agent

一个以真实学习记录为核心的个性化学习系统：Web SaaS 提供课程工作区、Today、学习计划、练习、错题、知识掌握度、RAG 资料库和 Learning Agent；Windows 桌面端提供本地学习能力，并可通过受保护的伴侣 API 接入同一学习空间。

产品闭环是：目标 → 计划 → 任务 → 练习 → Question Attempt → 错题/间隔复习 → Knowledge Mastery → Today 与下一轮计划。

![Learning workflow](docs/images/learning-workflow.svg)

## 产品概览

学习助手将课程、资料、练习与反馈放在同一条可追踪的流程中：

1. 创建课程与目标，设置可执行的学习节奏。
2. 资料检索 Agent 筛选学习资料；用户确认后导入课程资料库并建立 RAG 索引。
3. 出题 Agent 仅依据已索引资料生成练习题，避免无依据出题。
4. 任务编排 Agent 将目标拆分为每日学习任务；完成、延期与跳过都会更新进度。
5. 错题、复习与知识掌握度持续回流到 Today 页面，形成下一轮学习建议。

### Web 界面

- 课程工作区：目标、资料、知识点、练习、错题、笔记和分析在同一页面内切换。
- AI 学习助手：展示资料检索、导入、索引和后台任务的可见状态；写入学习数据前需要确认。
- 练习与复习：选择题可直接点击作答，提交后记录结果并进入错题/间隔复习流程。

> 说明：资料导入仅接受可解析的学习文件。网页来源会先尝试发现其中的 PDF；未发现可导入文件时，流程会明确暂停并提示上传本地资料，而不会生成没有依据的题目。

## 运行模式

- `docker-compose.saas.yml`：生产候选 Web/SaaS 部署，包含 API、Worker、PostgreSQL/pgvector、Redis、MinIO 和可选 HTTPS Caddy。
- `app.main`：本地 Windows 桌面应用，数据默认保存在用户数据目录；需要接入 Web Agent 时配置 `.env` 中的伴侣 API 参数。

首次部署 SaaS 前请阅读 [生产发布手册](docs/PRODUCTION_RELEASE.md)，不要直接使用示例密码或开发环境密钥。

## 功能

- 首页真实统计、今日任务完成
- 课程创建、编辑、详情、搜索、进度展示和归档
- 任意日期任务、周视图、学习目标、完成和删除
- 资料文件/目录后台导入、SHA-256 去重、预览、重命名、回收站与恢复
- 本地题库 CRUD、JSON 导入导出、随机练习、客观题判分与简答自评
- 错题自动收集、1/3/7/14/30 天间隔复习和状态历史
- 基于真实记录的学习分析图表与 CSV 导出
- 受限工具注册中心、JSON 参数校验、写操作确认和审计日志
- 后台任务中心、日志查看与导出
- 设置持久化、完整 ZIP 备份、哈希校验恢复
- Ctrl+K 全局搜索课程、任务、题目和资料

## SaaS 本地启动

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.saas.yml up -d --build
docker compose -f docker-compose.saas.yml run --rm migrate python -m alembic current
python scripts/smoke_test_saas.py --base-url http://127.0.0.1:8000
```

打开 `http://127.0.0.1:8000/web/`。正式环境请使用生产域名、真实密钥、HTTPS 和独立的数据库迁移角色，完整流程见 [生产发布手册](docs/PRODUCTION_RELEASE.md)。

## 桌面端安装与启动

```powershell
cd personal_learning_desktop
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m app.main
```

数据默认保存在用户目录下的 `.personal_learning_desktop`，其中包含 SQLite、受管 workspace 和日志。可通过 `LEARNING_DATA_DIR` 修改。

## 测试

```powershell
pytest -p no:cacheprovider
```

## 工具 CLI

```powershell
python -m app.tools.cli list
python -m app.tools.cli run filesystem.list_directory --json '{"path":"."}'
python -m app.tools.cli run database.backup --json '{"path":"backup.zip"}' --confirm
```

## Windows 构建

```powershell
python scripts/build_windows.py
python scripts/smoke_test_release.py app\PersonalLearningDesktop\PersonalLearningDesktop.exe
```

发布冒烟会在隔离的临时数据目录中运行两次程序，覆盖首次建库、创建课程、导入文本、创建任务、退出和重开后的持久化验证，不会改动真实用户数据。

构建产物：

- `app/PersonalLearningDesktop/PersonalLearningDesktop.exe`：standalone 可执行程序
- `dist/PersonalLearningDesktop-1.0.0-windows-x64.zip`：可分发压缩包
- `dist/PersonalLearningDesktop-1.0.0-windows-x64.zip.sha256`：压缩包完整性校验
- 压缩包内的 `release-manifest.json`：可执行文件 SHA-256 清单

正式发布前必须使用受信任的 Windows 代码签名证书；未签名的 PyInstaller 包可能被 Microsoft Defender 或 SmartScreen 阻止。设置 `WINDOWS_SIGN_CERT_PATH`（可选 `WINDOWS_SIGN_CERT_PASSWORD`、`WINDOWS_SIGNTOOL_PATH`）后运行：

```powershell
python scripts/build_windows.py --require-signature
python scripts/smoke_test_release.py app\PersonalLearningDesktop\PersonalLearningDesktop.exe
```

安装时解压 ZIP 并运行 `PersonalLearningDesktop.exe`。卸载时删除解压目录即可；用户数据库和资料位于独立的数据目录，不会随程序升级或卸载被覆盖。需要清除数据时，请在应用“系统设置”中使用带确认文本的重置功能。

参见 [ARCHITECTURE.md](ARCHITECTURE.md) 了解分层、线程与数据安全设计。
