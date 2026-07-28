# 个性化学习助手

使用 PySide6 Qt Widgets 构建、完全离线运行的本地学习桌面应用。第一阶段不接入 AI、RAG、向量数据库、多 Agent 或 MCP。

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

## 安装与启动

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
python scripts/smoke_test_release.py app\PersonalLearningDesktop.dist\main.exe
```

发布冒烟会在隔离的临时数据目录中运行两次程序，覆盖首次建库、创建课程、导入文本、创建任务、退出和重开后的持久化验证，不会改动真实用户数据。

构建产物：

- `app/PersonalLearningDesktop.dist/main.exe`：standalone 可执行程序
- `dist/PersonalLearningDesktop-1.0.0-windows-x64.zip`：可分发压缩包

安装时解压 ZIP 并运行 `main.exe`。卸载时删除解压目录即可；用户数据库和资料位于独立的数据目录，不会随程序升级或卸载被覆盖。需要清除数据时，请在应用“系统设置”中使用带确认文本的重置功能。

参见 [ARCHITECTURE.md](ARCHITECTURE.md) 了解分层、线程与数据安全设计。
