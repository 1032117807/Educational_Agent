from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai.agents import AgentDecision, GeneratedPractice, LearningPlanAgentService, PlanPreview
from app.services.domain import JobService


class AgentWorkerSignals(QObject):
    decision = Signal(object)
    preview = Signal(object)
    practice = Signal(object)
    result = Signal(object)
    tool_event = Signal(str, str, str)
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
        tool_name: str | None = None,
        tool_arguments: dict | None = None,
        confirmed: bool = False,
        course_id: int | None = None,
        question_request: str = "",
        question_count: int = 5,
        question_difficulty: int = 3,
    ) -> None:
        super().__init__()
        self.factory = factory
        self.operation = operation
        self.message = message
        self.history = history or []
        self.goal_id = goal_id
        self.daily_minutes = daily_minutes
        self.draft_id = draft_id
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments or {}
        self.confirmed = confirmed
        self.course_id = course_id
        self.question_request = question_request
        self.question_count = question_count
        self.question_difficulty = question_difficulty
        self.signals = AgentWorkerSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            service = self.factory()
            if self.operation == "chat":
                self.signals.tool_event.emit("agent.decide", "running", "分析对话意图")
                self.signals.decision.emit(service.respond(self.message, self.history))
                self.signals.tool_event.emit("agent.decide", "completed", "已得到执行决策")
            elif self.operation == "generate":
                self.signals.tool_event.emit("learning_plan.generate", "running", "生成计划草稿")
                self.signals.preview.emit(service.generate_plan(
                    goal_id=self.goal_id or 0,
                    daily_minutes=self.daily_minutes,
                ))
                self.signals.tool_event.emit("learning_plan.generate", "completed", "计划草稿已生成")
            elif self.operation == "confirm":
                self.signals.tool_event.emit("learning_plan.confirm", "running", "写入学习任务")
                self.signals.result.emit(service.confirm_plan(self.draft_id or 0))
                self.signals.tool_event.emit("learning_plan.confirm", "completed", "学习任务已写入")
            elif self.operation == "tool":
                self.signals.tool_event.emit(self.tool_name or "tool", "running", "执行通用工具")
                self.signals.result.emit(service.execute_tool(
                    self.tool_name or "", self.tool_arguments, confirmed=self.confirmed
                ))
                self.signals.tool_event.emit(self.tool_name or "tool", "completed", "工具已执行")
            elif self.operation == "generate_questions":
                self.signals.tool_event.emit("question_generation.generate", "running", self.question_request[:80])
                self.signals.practice.emit(service.generate_questions(
                    course_id=self.course_id or 0,
                    request=self.question_request,
                    count=self.question_count,
                    difficulty=self.question_difficulty,
                    progress=self.signals.tool_event.emit,
                ))
                self.signals.tool_event.emit("question_drafts.accept", "completed", "题目已入库并交给练习中心")
        except Exception as exc:
            self.signals.tool_event.emit(self.operation, "failed", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class LearningAgentPage(QWidget):
    navigate_requested = Signal(str)
    practice_requested = Signal(object)
    new_window_requested = Signal()

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
        self.pending_tool: tuple[str, dict] | None = None
        self.pending_question_generation: tuple[int, str, int, int] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        shortcuts = QHBoxLayout()
        for label, route in (
            ("资料问答", "resources"), ("题目与练习", "practice"),
            ("学习计划", "plan"), ("学习报告", "analytics"), ("错题复习", "review"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, item=route: self.navigate_requested.emit(item))
            shortcuts.addWidget(button)
        shortcuts.addStretch()
        new_window = QPushButton("新建 Agent 窗口")
        new_window.clicked.connect(self.new_window_requested.emit)
        shortcuts.addWidget(new_window)
        root.addLayout(shortcuts)
        for index in range(shortcuts.count()):
            widget = shortcuts.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        session_actions = QHBoxLayout()
        session_actions.addStretch()
        self.new_session_button = QPushButton("+ 新建会话")
        self.new_session_button.setToolTip("在左侧导航中新建独立的 Agent 会话")
        self.new_session_button.clicked.connect(self.new_window_requested.emit)
        session_actions.addWidget(self.new_session_button)
        root.addLayout(session_actions)
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
        self.activity.currentItemChanged.connect(self.show_tool_detail)
        activity_layout.addWidget(self.activity, 1)
        self.tool_detail = QPlainTextEdit()
        self.tool_detail.setReadOnly(True)
        self.tool_detail.setMaximumHeight(130)
        self.tool_detail.setPlaceholderText("选择一次工具调用以查看参数、结果或错误信息")
        activity_layout.addWidget(self.tool_detail)
        self.confirm_plan_button = QPushButton("确认生成计划草稿")
        self.confirm_plan_button.setEnabled(False)
        self.confirm_plan_button.clicked.connect(self.generate_plan)
        self.commit_plan_button = QPushButton("确认写入学习任务")
        self.commit_plan_button.setEnabled(False)
        self.commit_plan_button.clicked.connect(self.commit_plan)
        self.confirm_tool_button = QPushButton("确认执行操作")
        self.confirm_tool_button.setEnabled(False)
        self.confirm_tool_button.clicked.connect(self.commit_tool)
        activity_layout.addWidget(self.confirm_plan_button)
        activity_layout.addWidget(self.commit_plan_button)
        activity_layout.addWidget(self.confirm_tool_button)
        splitter.addWidget(activity)
        splitter.setSizes([760, 320])
        root.addWidget(splitter, 1)
        for label in self.findChildren(QLabel):
            if "Agent" in label.text():
                label.setText("AI 中心")

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
        worker.signals.practice.connect(self.receive_practice)
        worker.signals.result.connect(self.receive_result)
        worker.signals.tool_event.connect(self.record_tool_event)
        worker.signals.failed.connect(self.receive_error)
        worker.signals.finished.connect(self.worker_finished)
        self.activity.addItem(f"开始：{worker.operation}")
        self.pool.start(worker)

    def record_tool_event(self, tool_name: str, status: str, detail: str) -> None:
        labels = {"running": "运行中", "completed": "完成", "failed": "失败"}
        self.activity.addItem(f"{labels.get(status, status)}  {tool_name}\n{detail}")

    def record_tool_event(self, tool_name: str, status: str, detail: str) -> None:
        labels = {
            "queued": "等待", "running": "运行中", "completed": "完成", "failed": "失败",
        }
        item = QListWidgetItem(f"{labels.get(status, status)}  {tool_name}")
        item.setData(Qt.UserRole, {"tool": tool_name, "status": status, "detail": detail})
        self.activity.addItem(item)
        self.activity.setCurrentItem(item)

    def show_tool_detail(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.tool_detail.clear()
            return
        event = current.data(Qt.UserRole) or {}
        self.tool_detail.setPlainText(
            f"工具：{event.get('tool', '')}\n"
            f"状态：{event.get('status', '')}\n\n"
            f"{event.get('detail', '')}"
        )

    def receive_decision(self, decision: AgentDecision) -> None:
        self.chat.append(f"\n**Agent**\n{decision.reply}")
        self.history.append({"role": "assistant", "content": decision.reply})
        self.activity.addItem(f"判断动作：{decision.action}")
        if decision.action == "generate_plan":
            self.pending_goal_id = decision.goal_id
            self.pending_daily_minutes = decision.daily_minutes
            self.confirm_plan_button.setEnabled(True)
            self.chat.append("\n计划会先生成草稿，不会立即写入任务。请确认后继续。")

        elif decision.action == "navigate" and decision.route:
            self.navigate_requested.emit(decision.route)
            self.activity.addItem(f"已跳转到：{decision.route}")
        elif decision.action == "tool" and decision.tool_name:
            self.pending_tool = (decision.tool_name, decision.tool_arguments)
            self.confirm_tool_button.setEnabled(True)
            self.chat.append(
                f"\n需要执行项目操作：`{decision.tool_name}`，请确认后执行。"
            )

        elif decision.action == "generate_questions":
            if not decision.course_id or not decision.question_request:
                self.chat.append("\n请补充课程和题目要求。")
                return
            self.pending_question_generation = (
                decision.course_id,
                decision.question_request,
                decision.question_count,
                decision.question_difficulty,
            )

    def receive_practice(self, generated: GeneratedPractice) -> None:
        self.chat.append(
            f"\n**Agent**\n已生成 {len(generated.question_ids)} 道题目，正在交给练习中心。"
        )
        self.activity.addItem("题目已生成，交给练习中心")
        self.record_tool_event("practice.open", "completed", "已打开生成题目的练习会话")
        self.practice_requested.emit(generated.question_ids)

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

    def commit_tool(self) -> None:
        if self.pending_tool is None or self.worker is not None:
            return
        name, arguments = self.pending_tool
        self.confirm_tool_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="tool",
            tool_name=name,
            tool_arguments=arguments,
            confirmed=True,
        ))

    def receive_result(self, result: object) -> None:
        count = result
        self.chat.append(f"\n**Agent**\n已确认并写入 {count} 个学习任务。")
        self.activity.addItem(f"已写入 {count} 个学习任务")
        self.pending_draft_id = None
        self.pending_tool = None

    def receive_error(self, message: str) -> None:
        self.chat.append(f"\n**Agent**\n执行失败：{message}")
        self.activity.addItem("执行失败")
        self.confirm_plan_button.setEnabled(False)
        self.commit_plan_button.setEnabled(False)
        self.confirm_tool_button.setEnabled(False)
        QMessageBox.warning(self, "Agent 执行失败", message)

    def worker_finished(self) -> None:
        self.worker = None
        if self.pending_question_generation is not None:
            course_id, request, count, difficulty = self.pending_question_generation
            self.pending_question_generation = None
            self._start_worker(AgentWorker(
                factory=self.agent_factory,
                operation="generate_questions",
                course_id=course_id,
                question_request=request,
                question_count=count,
                question_difficulty=difficulty,
            ))
            return
        self.send_button.setEnabled(True)
