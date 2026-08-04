from __future__ import annotations

from collections.abc import Callable
import json

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai.agents import AgentDecision, LearningPlanAgentService, PlanPreview
from app.services.domain import JobService


class AgentWorkerSignals(QObject):
    decision = Signal(object)
    preview = Signal(object)
    result = Signal(int)
    failed = Signal(str)
    finished = Signal()


class AgentWorker(QRunnable):
    def __init__(
        self,
        *,
        factory: Callable[[], LearningPlanAgentService],
        operation: str,
        message: str = "",
        history: list[dict[str, str]] | None = None,
        goal_id: int | None = None,
        daily_minutes: int = 60,
        draft_id: int | None = None,
    ) -> None:
        super().__init__()
        self.factory = factory
        self.operation = operation
        self.message = message
        self.history = history or []
        self.goal_id = goal_id
        self.daily_minutes = daily_minutes
        self.draft_id = draft_id
        self.signals = AgentWorkerSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            service = self.factory()
            if self.operation == "chat":
                self.signals.decision.emit(service.respond(self.message, self.history))
            elif self.operation == "generate":
                self.signals.preview.emit(service.generate_plan(
                    goal_id=self.goal_id or 0,
                    daily_minutes=self.daily_minutes,
                ))
            elif self.operation == "confirm":
                self.signals.result.emit(service.confirm_plan(self.draft_id or 0))
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class LearningAgentPage(QWidget):
    def __init__(
        self,
        *,
        jobs: JobService,
        agent_factory: Callable[[], LearningPlanAgentService],
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.agent_factory = agent_factory
        self.pool = QThreadPool.globalInstance()
        self.worker: AgentWorker | None = None
        self.history: list[dict[str, str]] = []
        self.pending_goal_id: int | None = None
        self.pending_daily_minutes = 60
        self.pending_draft_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addWidget(QLabel("学习计划 Agent"))
        root.addWidget(QLabel("对话查看学习状态、生成计划草稿，并在确认后写入学习任务。"))

        splitter = QSplitter(Qt.Horizontal)
        conversation = QWidget()
        conversation_layout = QVBoxLayout(conversation)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.append("**学习计划 Agent**\n告诉我你的目标，或直接说“帮我安排本周学习计划”。")
        conversation_layout.addWidget(self.chat, 1)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("例如：根据我最薄弱的知识点，安排每天 60 分钟的学习计划")
        self.input.setMaximumHeight(100)
        send_row = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self.send_message)
        self.input.setTabChangesFocus(True)
        send_row.addWidget(self.input, 1)
        send_row.addWidget(self.send_button)
        conversation_layout.addLayout(send_row)
        splitter.addWidget(conversation)

        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        activity_layout.addWidget(QLabel("执行记录"))
        self.activity = QListWidget()
        activity_layout.addWidget(self.activity, 1)
        self.confirm_plan_button = QPushButton("确认生成计划草稿")
        self.confirm_plan_button.setEnabled(False)
        self.confirm_plan_button.clicked.connect(self.generate_plan)
        self.commit_plan_button = QPushButton("确认写入学习任务")
        self.commit_plan_button.setEnabled(False)
        self.commit_plan_button.clicked.connect(self.commit_plan)
        activity_layout.addWidget(self.confirm_plan_button)
        activity_layout.addWidget(self.commit_plan_button)
        splitter.addWidget(activity)
        splitter.setSizes([760, 320])
        root.addWidget(splitter, 1)

    def refresh(self) -> None:
        return

    def send_message(self) -> None:
        message = self.input.toPlainText().strip()
        if not message or self.worker is not None:
            return
        self.input.clear()
        self.chat.append(f"\n**你**\n{message}")
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="chat",
            message=message,
            history=self.history,
        ))
        self.history.append({"role": "user", "content": message})

    def _start_worker(self, worker: AgentWorker) -> None:
        self.worker = worker
        self.send_button.setEnabled(False)
        worker.signals.decision.connect(self.receive_decision)
        worker.signals.preview.connect(self.receive_preview)
        worker.signals.result.connect(self.receive_result)
        worker.signals.failed.connect(self.receive_error)
        worker.signals.finished.connect(self.worker_finished)
        self.activity.addItem(f"开始：{worker.operation}")
        self.pool.start(worker)

    def receive_decision(self, decision: AgentDecision) -> None:
        self.chat.append(f"\n**Agent**\n{decision.reply}")
        self.history.append({"role": "assistant", "content": decision.reply})
        self.activity.addItem(f"判断动作：{decision.action}")
        if decision.action == "generate_plan":
            self.pending_goal_id = decision.goal_id
            self.pending_daily_minutes = decision.daily_minutes
            self.confirm_plan_button.setEnabled(True)
            self.chat.append("\n计划会先生成草稿，不会立即写入任务。请确认后继续。")

    def generate_plan(self) -> None:
        if self.pending_goal_id is None or self.worker is not None:
            return
        self.confirm_plan_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="generate",
            goal_id=self.pending_goal_id,
            daily_minutes=self.pending_daily_minutes,
        ))

    def receive_preview(self, preview: PlanPreview) -> None:
        self.pending_draft_id = preview.draft_id
        lines = [f"**计划草稿 #{preview.draft_id}**", preview.summary, ""]
        lines.extend(
            f"- {item['date']} {item['title']}（{item['duration_minutes']} 分钟）"
            for item in preview.tasks
        )
        if preview.risks:
            lines.extend(["", "风险：", *[f"- {risk}" for risk in preview.risks]])
        self.chat.append("\n" + "\n".join(lines))
        self.commit_plan_button.setEnabled(True)
        self.activity.addItem(f"已生成草稿 #{preview.draft_id}，等待写入确认")

    def commit_plan(self) -> None:
        if self.pending_draft_id is None or self.worker is not None:
            return
        self.commit_plan_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="confirm",
            draft_id=self.pending_draft_id,
        ))

    def receive_result(self, count: int) -> None:
        self.chat.append(f"\n**Agent**\n已确认并写入 {count} 个学习任务。")
        self.activity.addItem(f"已写入 {count} 个学习任务")
        self.pending_draft_id = None

    def receive_error(self, message: str) -> None:
        self.chat.append(f"\n**Agent**\n执行失败：{message}")
        self.activity.addItem("执行失败")
        self.confirm_plan_button.setEnabled(False)
        self.commit_plan_button.setEnabled(False)
        QMessageBox.warning(self, "Agent 执行失败", message)

    def worker_finished(self) -> None:
        self.worker = None
        self.send_button.setEnabled(True)
