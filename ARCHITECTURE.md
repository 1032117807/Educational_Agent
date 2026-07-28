# 架构与数据安全

## 分层

界面只调用 Service。业务 Service 使用 Repository 或 SQLAlchemy Session；SQL 不出现在 UI 中。

```text
Qt Widgets UI
  ├─ LearningService
  ├─ ResourceService
  ├─ QuestionService / ReviewService
  ├─ AnalyticsService
  ├─ MaintenanceService / JobService
  └─ ToolRegistry
        ↓
Repository / SQLAlchemy 2
        ↓
SQLite + 受管 workspace
```

页面与领域服务按功能拆分：

- `app/ui/*_page.py`：首页、课程、资料、计划、练习、复习、分析、工具与设置页面。
- `app/services/resources.py`：受管资料与安全路径。
- `app/services/assessment.py`：题库、练习与复习调度。
- `app/services/analytics.py`：统计查询和导出。
- `app/services/maintenance.py`：备份恢复、搜索、维护和后台任务。
- `domain.py`、`pages.py`、`advanced_pages.py` 仅保留兼容导出，旧导入路径仍然有效。

## 本地数据与安全

- SQLite、日志、备份临时文件与 workspace 位于应用数据目录。
- 导入资料会复制到 workspace，并以 SHA-256 去重。
- 所有工具路径在 `resolve()` 后再次验证仍属于 workspace。
- 删除资料先进入 `.trash`，可恢复。
- SQLite 备份使用在线 backup API，ZIP 包含 manifest 和数据库哈希。
- 恢复前自动生成当前数据的安全备份，校验失败不会覆盖数据库。

## 线程

文件和目录导入由 `QThreadPool + QRunnable` 执行。Worker 只通过 Signal 通知 UI，并将状态写入后台任务表。应用启动会把遗留的 `running` 任务改为 `interrupted`。

主窗口关闭时先请求取消后台任务、等待线程池退出，再释放 SQLAlchemy 连接池，确保 Windows 上数据库文件可立即备份、替换或删除。

## 第一阶段边界

应用完全离线。AI、RAG、向量数据库、多 Agent 与 MCP 均未接入；工具中心使用内部 ToolRegistry，不是 MCP Server。
