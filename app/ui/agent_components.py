from __future__ import annotations

from datetime import datetime
from html import escape
from time import monotonic

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QKeyEvent, QPalette, QTextDocument
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPlainTextEdit, QTextBrowser


class AgentChatView(QTextBrowser):
    """将 Markdown 对话渲染为区分角色的消息卡片。"""

    def __init__(self) -> None:
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setObjectName("agentChat")
        self.document().setDocumentMargin(16)

    def append(self, text: str) -> None:  # type: ignore[override]
        role, content = self._split_role(text)
        if role is None:
            super().append(self._render_markdown(content))
            return
        css_class = "user" if role == "你" else "agent"
        label = "你" if role == "你" else "AI 学习助手"
        html = self._render_markdown(content)
        label_html = f'<div class="message-label">{label}</div>' if css_class == "user" else ""
        dark = self.palette().color(QPalette.Window).lightness() < 128
        if role == "你":
            background, border = ("#1D3A5F", "#3B82C4") if dark else ("#EAF2FF", "#B2CCFF")
        else:
            background, border = ("#182230", "#344054") if dark else ("#FFFFFF", "#E3E8EF")
        super().append(
            f'<table class="message {css_class}" width="100%" '
            f'style="background:{background}; border:1px solid {border}; border-radius:8px;">'
            f'<tr><td style="padding:10px 12px;">{label_html}'
            f"{html}</td></tr></table>"
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def doSetSource(
        self,
        url: QUrl,
        resource_type: QTextDocument.ResourceType = QTextDocument.ResourceType.UnknownResource,
    ) -> None:
        """Keep report action links from being treated as chat documents."""
        if url.scheme() == "report" and url.host() == "download":
            return
        super().doSetSource(url, resource_type)

    @staticmethod
    def _split_role(text: str) -> tuple[str | None, str]:
        normalized = text.strip()
        for role in ("你", "Agent", "AI 中心", "AI Center"):
            marker = f"**{role}**"
            if normalized.startswith(marker):
                return ("你" if role == "你" else "Agent", normalized[len(marker):].strip())
        return None, normalized

    @staticmethod
    def _render_markdown(markdown: str) -> str:
        document = QTextDocument()
        document.setMarkdown(markdown)
        html = document.toHtml()
        start = html.find("<body")
        if start == -1:
            return f"<p>{escape(markdown)}</p>"
        start = html.find(">", start) + 1
        end = html.rfind("</body>")
        return html[start:end]


class AgentChatInput(QPlainTextEdit):
    """Enter 发送、Shift+Enter 换行的对话输入框。"""

    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ExecutionTimeline(QListWidget):
    """按任务标识原地更新状态，避免同一任务产生重复事件行。"""

    _STATUS_LABELS = {
        "queued": "等待中",
        "pending": "等待中",
        "running": "执行中",
        "streaming": "正在响应",
        "completed": "已完成",
        "success": "已完成",
        "warning": "已完成，有提醒",
        "failed": "执行失败",
        "cancelled": "已取消",
        "timeout": "已超时",
        "fallback": "兼容模式",
    }
    _FRIENDLY_NAMES = {
        "agent.request": "接收请求",
        "agent.context": "读取学习数据",
        "agent.model": "生成回复",
        "agent.reasoning": "整理决策依据",
        "agent.error": "执行错误",
        "agent.decide": "分析请求",
        "learning_plan.generate": "生成学习计划",
        "learning_plan.confirm": "写入学习任务",
        "question_generation.generate": "生成练习题",
        "question_generation.retry": "重试生成题目",
        "learning_report.collect": "收集学习数据",
        "learning_report.generate": "生成学习报告",
        "learning_goal.create": "创建学习目标",
        "workflow": "学习闭环",
        "practice.open": "打开练习中心",
        "dispatch.学习计划 Agent": "分配给学习计划 Agent",
        "dispatch.出题 Agent": "分配给出题 Agent",
        "dispatch.报告 Agent": "分配给报告 Agent",
        "dispatch.总控 Agent": "启动总控工作流",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("executionTimeline")
        self._items: dict[str, QListWidgetItem] = {}
        self._started_at: dict[str, float] = {}

    def record(self, task_id: str, status: str, detail: str) -> None:
        item = self._items.get(task_id)
        if item is None:
            item = QListWidgetItem(self)
            self._items[task_id] = item
            self._started_at[task_id] = monotonic()
        elapsed = monotonic() - self._started_at[task_id]
        label = self._FRIENDLY_NAMES.get(task_id, task_id.replace("_", " "))
        status_label = self._STATUS_LABELS.get(status, status)
        item.setText(f"{status_label}  {label}  {elapsed:.1f}s")
        item.setData(Qt.UserRole, {
            "tool": label,
            "internal_name": task_id,
            "status": status_label,
            "raw_status": status,
            "detail": detail,
            "started_at": datetime.now().strftime("%H:%M:%S"),
            "elapsed_seconds": round(elapsed, 1),
        })
        self.setCurrentItem(item)

    def set_status_filter(self, status: str | None) -> None:
        """仅隐藏不匹配项，不丢弃该会话的执行记录。"""
        for item in self._items.values():
            event = item.data(Qt.UserRole) or {}
            item.setHidden(status is not None and event.get("raw_status") != status)
