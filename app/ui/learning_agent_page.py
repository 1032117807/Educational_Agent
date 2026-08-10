from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import traceback
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai.agents import AgentDecision, GeneratedPractice, GeneratedReport, LearningPlanAgentService, PlanPreview
from app.services.domain import JobService
from app.services.agent_sessions import AgentSessionService
from app.services.agent_skills import AgentSkillCatalog
from app.services.agent_memory import AgentMemoryService
from app.services.agent_workflows import AgentWorkflowService, WorkflowOutcome
from app.services.report_export import export_report
from app.services.cancellation import CancellationToken, OperationCancelled
from app.ui.agent_components import AgentChatInput, AgentChatView, ExecutionTimeline
from app.ui.skill_manager import SkillManagerDialog


class AgentWorkerSignals(QObject):
    decision = Signal(object)
    preview = Signal(object)
    practice = Signal(object)
    report = Signal(object)
    result = Signal(object)
    tool_event = Signal(str, str, str)
    agent_stage = Signal(str, str, str)
    text_delta = Signal(str)
    failed = Signal(str)
    failed_detail = Signal(str, str)
    finished = Signal(object)


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
        research_request: str = "",
        candidate_id: int | None = None,
        question_count: int = 5,
        question_difficulty: int = 3,
        goal_title: str = "",
        goal_target_date=None,
        goal_weekly_minutes: int = 420,
        goal_target_score: float | None = None,
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
        self.research_request = research_request
        self.candidate_id = candidate_id
        self.question_count = question_count
        self.question_difficulty = question_difficulty
        self.goal_title = goal_title
        self.goal_target_date = goal_target_date
        self.goal_weekly_minutes = goal_weekly_minutes
        self.goal_target_score = goal_target_score
        self.signals = AgentWorkerSignals()
        self.cancelled = False
        self.cancellation = CancellationToken()
        self.setAutoDelete(False)

    def cancel(self, reason: str = "Cancelled by user") -> None:
        """Mark the request cancelled; blocking providers finish cooperatively."""
        self.cancelled = True
        self.cancellation.cancel(reason)

    def retry_clone(self) -> "AgentWorker":
        """用相同输入创建新任务，避免复用已完成的 QRunnable。"""
        return AgentWorker(
            factory=self.factory, operation=self.operation, message=self.message,
            history=self.history, goal_id=self.goal_id, daily_minutes=self.daily_minutes,
            draft_id=self.draft_id, tool_name=self.tool_name,
            tool_arguments=self.tool_arguments, confirmed=self.confirmed,
            course_id=self.course_id, question_request=self.question_request,
            research_request=self.research_request, candidate_id=self.candidate_id,
            question_count=self.question_count, question_difficulty=self.question_difficulty,
            goal_title=self.goal_title, goal_target_date=self.goal_target_date,
            goal_weekly_minutes=self.goal_weekly_minutes,
            goal_target_score=self.goal_target_score,
        )

    def run(self) -> None:
        try:
            service = self.factory()
            if self.operation == "chat":
                self.signals.agent_stage.emit("agent.request", "running", "正在接收用户请求")
                self.signals.agent_stage.emit("agent.context", "running", "正在读取课程、目标、知识点和最近学习记录")
                self.signals.agent_stage.emit("agent.model", "running", "正在等待 Agent 决策")
                self.signals.tool_event.emit("agent.decide", "running", "分析对话意图")
                decision = asyncio.run(service.respond_async(
                    self.message,
                    self.history,
                    cancellation=self.cancellation,
                    progress=self.signals.agent_stage.emit,
                    on_text=self.signals.text_delta.emit,
                ))
                if self.cancelled:
                    return
                self.signals.decision.emit(decision)
                self.signals.agent_stage.emit("agent.model", "completed", f"Decision: {decision.action}")
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
                self.signals.agent_stage.emit(
                    self.tool_name or "tool",
                    "running",
                    "Tool input:\n" + json.dumps(self.tool_arguments, ensure_ascii=False, indent=2),
                )
                self.signals.tool_event.emit(self.tool_name or "tool", "running", "执行通用工具")
                tool_name = self.tool_name or "tool"
                try:
                    result = service.execute_tool(
                        tool_name,
                        self.tool_arguments,
                        confirmed=self.confirmed,
                        cancellation=self.cancellation,
                    )
                except Exception as exc:
                    self.signals.agent_stage.emit(tool_name, "failed", f"Tool error:\n{exc}")
                    raise
                output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
                self.signals.agent_stage.emit(
                    tool_name,
                    "completed",
                    "Tool output:\n" + output[:6000],
                )
                self.signals.result.emit(result)
                self.signals.tool_event.emit(self.tool_name or "tool", "completed", "工具已执行")
            elif self.operation == "generate_questions":
                self.signals.agent_stage.emit("question_generation.generate", "running", "正在生成练习题")
                self.signals.tool_event.emit("question_generation.generate", "running", self.question_request[:80])
                self.signals.practice.emit(service.generate_questions(
                    course_id=self.course_id or 0,
                    request=self.question_request,
                    count=self.question_count,
                    difficulty=self.question_difficulty,
                    progress=self.signals.agent_stage.emit,
                ))
                self.signals.tool_event.emit("question_drafts.accept", "completed", "题目已入库并交给练习中心")
            elif self.operation == "generate_report":
                self.signals.agent_stage.emit("learning_report.collect", "running", "正在收集学习数据")
                self.signals.tool_event.emit("learning_report.generate", "running", "Generating a seven-day learning report")
                self.signals.report.emit(service.generate_report())
                self.signals.agent_stage.emit("learning_report.generate", "completed", "学习报告已生成")
                self.signals.tool_event.emit("learning_report.generate", "completed", "Report generated")
            elif self.operation == "research_collect":
                self.signals.agent_stage.emit("research.search", "running", "Searching and assessing public course resources")
                self.signals.result.emit(service.collect_research(
                    course_id=self.course_id or 0, request=self.research_request,
                ))
                self.signals.agent_stage.emit("research.search", "completed", "Candidates assessed; import requires confirmation")
            elif self.operation == "research_import":
                self.signals.agent_stage.emit("research.import", "running", "Downloading confirmed resource and indexing it for RAG")
                self.signals.result.emit(service.import_research_candidate(
                    self.candidate_id or 0, confirmed=self.confirmed,
                ))
                self.signals.agent_stage.emit("research.import", "completed", "Resource imported and indexed")
            elif self.operation == "create_goal":
                self.signals.tool_event.emit("learning_goal.create", "running", "Creating a learning goal")
                self.signals.result.emit(service.create_goal(
                    title=self.goal_title,
                    target_date=self.goal_target_date,
                    weekly_minutes=self.goal_weekly_minutes,
                    target_score=self.goal_target_score,
                    course_id=self.course_id,
                ))
                self.signals.tool_event.emit("learning_goal.create", "completed", "Learning goal created")
        except OperationCancelled as exc:
            self.signals.agent_stage.emit(self.operation, "cancelled", str(exc))
        except Exception as exc:
            self.signals.tool_event.emit(self.operation, "failed", str(exc))
            self.signals.failed_detail.emit(str(exc), traceback.format_exc())
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit(self)


class WorkflowWorkerSignals(QObject):
    outcome = Signal(object)
    tool_event = Signal(str, str, str)
    failed = Signal(str)
    finished = Signal()


class WorkflowWorker(QRunnable):
    def __init__(self, *, factory: Callable[[], AgentWorkflowService], workflow_id: int) -> None:
        super().__init__()
        self.factory = factory
        self.workflow_id = workflow_id
        self.signals = WorkflowWorkerSignals()
        self.cancellation = CancellationToken()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            service = self.factory()
            workflow = service.get(self.workflow_id)
            specialist = AgentWorkflowService.agent_for_step(workflow.current_step)
            self.signals.tool_event.emit(
                f"handoff.{specialist}", "running",
                f"总控 Agent 正在分配任务给 {specialist}\n"
                f"输入摘要：课程 #{workflow.course_id}；请求：{workflow.request[:120]}"
            )
            outcome = service.continue_workflow(
                self.workflow_id, self.signals.tool_event.emit, self.cancellation
            )
            self.signals.outcome.emit(outcome)
            self.signals.tool_event.emit(
                f"handoff.{specialist}", "completed",
                f"{specialist} 已完成并交回总控 Agent\n"
                f"输出：{outcome.summary}\n"
                f"产物：{json.dumps(outcome.payload, ensure_ascii=False)[:800]}"
            )
        except Exception as exc:
            self.signals.tool_event.emit("workflow", "failed", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()

    def cancel(self, reason: str = "Cancelled by user") -> None:
        self.cancellation.cancel(reason)


class LearningAgentPage(QWidget):
    navigate_requested = Signal(str)
    practice_requested = Signal(object)
    workflow_practice_requested = Signal(int, object)
    knowledge_review_requested = Signal(int)
    new_window_requested = Signal()
    session_title_changed = Signal(int, str)

    def __init__(
        self,
        *,
        jobs: JobService,
        agent_factory: Callable[[], LearningPlanAgentService],
        workflow_factory: Callable[[], AgentWorkflowService],
        session_service: AgentSessionService,
        session_id: int,
        skill_catalog: AgentSkillCatalog | None = None,
        memory_service: AgentMemoryService | None = None,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.agent_factory = agent_factory
        self.workflow_factory = workflow_factory
        self.session_service = session_service
        self.session_id = session_id
        self.skill_catalog = skill_catalog or AgentSkillCatalog()
        self.memory_service = memory_service
        self.pool = QThreadPool.globalInstance()
        self.worker: AgentWorker | None = None
        self.workflow_worker: WorkflowWorker | None = None
        self.history: list[dict[str, str]] = []
        self.pending_goal_id: int | None = None
        self.pending_daily_minutes = 60
        self.pending_draft_id: int | None = None
        self.pending_tool: tuple[str, dict] | None = None
        self.pending_research_candidates: list[dict[str, object]] = []
        self.pending_create_goal: tuple[str, date, int, float | None, int | None] | None = None
        self.pending_question_generation: tuple[int, str, int, int] | None = None
        self.pending_memory: tuple[str, str, dict, int | None] | None = None
        self.pending_workflow_id: int | None = None
        self.workflow_state: tuple[str, str] | None = None
        self.last_failed_worker: AgentWorker | None = None
        self._live_stages: list[str] = []
        self._live_trace_persisted = False
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
        self.skills_button = QPushButton("Skills")
        self.skills_button.setToolTip("管理 Agent 的启用能力和权限范围")
        self.skills_button.clicked.connect(self.open_skill_manager)
        session_actions.addWidget(self.skills_button)
        self.memories_button = QPushButton("记忆")
        self.memories_button.setToolTip("查看或删除已确认的 Agent 记忆")
        self.memories_button.clicked.connect(self.show_memories)
        session_actions.addWidget(self.memories_button)
        root.addLayout(session_actions)
        root.addWidget(QLabel("学习计划 Agent"))
        root.addWidget(QLabel("对话查看学习状态、生成计划草稿，并在确认后写入学习任务。"))

        splitter = QSplitter(Qt.Horizontal)
        conversation = QWidget()
        conversation_layout = QVBoxLayout(conversation)
        self.chat = AgentChatView()
        self.chat.anchorClicked.connect(self.download_report)
        self.live_status = QLabel()
        self.live_status.setObjectName("agentLiveStatus")
        self.live_status.setWordWrap(True)
        self.live_status.hide()
        self.stream_output = QPlainTextEdit()
        self.stream_output.setObjectName("agentStreamOutput")
        self.stream_output.setReadOnly(True)
        self.stream_output.setMaximumHeight(150)
        self.stream_output.setPlaceholderText("AI 回复和工具调用会实时显示在这里")
        self.stream_output.hide()
        self.chat.append("**学习计划 Agent**\n告诉我你的目标，或直接说“帮我安排本周学习计划”。")
        conversation_layout.addWidget(self.live_status)
        conversation_layout.addWidget(self.stream_output)
        conversation_layout.addWidget(self.chat, 1)
        self.inline_approval = QWidget()
        inline_layout = QHBoxLayout(self.inline_approval)
        inline_layout.setContentsMargins(0, 0, 0, 0)
        self.inline_approval_title = QLabel()
        inline_layout.addWidget(self.inline_approval_title)
        self.inline_approval_buttons = QHBoxLayout()
        inline_layout.addLayout(self.inline_approval_buttons, 1)
        self.inline_approval.hide()
        conversation_layout.addWidget(self.inline_approval)
        self.input = AgentChatInput()
        self.input.setObjectName("agentInput")
        self.input.setPlaceholderText("例如：根据我最薄弱的知识点，安排每天 60 分钟的学习计划")
        self.input.setMaximumHeight(100)
        send_row = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self.send_message)
        self.input.send_requested.connect(self.send_message)
        self.stop_button = QPushButton("停止等待")
        self.stop_button.setToolTip("停止接收本次 Agent 请求的后续结果")
        self.stop_button.clicked.connect(self.cancel_active_request)
        self.stop_button.hide()
        send_row.addWidget(self.input, 1)
        send_row.addWidget(self.send_button)
        send_row.addWidget(self.stop_button)
        conversation_layout.addLayout(send_row)
        splitter.addWidget(conversation)

        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        activity_layout.addWidget(QLabel("执行记录"))
        self.activity = ExecutionTimeline()
        self.activity.currentItemChanged.connect(self.show_tool_detail)
        activity_header = QHBoxLayout()
        activity_title = QLabel("当前任务")
        activity_title.setObjectName("agentPanelTitle")
        activity_header.addWidget(activity_title)
        activity_header.addStretch()
        self.activity_filter = QComboBox()
        self.activity_filter.addItem("全部", None)
        self.activity_filter.addItem("执行中", "running")
        self.activity_filter.addItem("已完成", "completed")
        self.activity_filter.addItem("失败", "failed")
        self.activity_filter.currentIndexChanged.connect(
            lambda _: self.activity.set_status_filter(self.activity_filter.currentData())
        )
        activity_header.addWidget(self.activity_filter)
        self.developer_mode = QCheckBox("开发详情")
        self.developer_mode.toggled.connect(lambda _: self.show_tool_detail(self.activity.currentItem(), None))
        activity_header.addWidget(self.developer_mode)
        self.activity_collapse_button = QPushButton("收起")
        self.activity_collapse_button.clicked.connect(self.toggle_execution_panel)
        activity_header.addWidget(self.activity_collapse_button)
        activity_layout.addLayout(activity_header)
        activity_layout.addWidget(self.activity, 1)
        self.tool_detail = QPlainTextEdit()
        self.tool_detail.setReadOnly(True)
        self.tool_detail.setMaximumHeight(130)
        self.tool_detail.setPlaceholderText("选择一次工具调用以查看参数、结果或错误信息")
        activity_layout.addWidget(self.tool_detail)
        self.handoffs_button = QPushButton("View handoff history")
        self.handoffs_button.clicked.connect(self.show_handoff_history)
        activity_layout.addWidget(self.handoffs_button)
        self.confirm_plan_button = QPushButton("确认生成计划草稿")
        self.confirm_plan_button.setEnabled(False)
        self.confirm_plan_button.clicked.connect(self.generate_plan)
        self.commit_plan_button = QPushButton("确认写入学习任务")
        self.commit_plan_button.setEnabled(False)
        self.commit_plan_button.clicked.connect(self.commit_plan)
        self.confirm_tool_button = QPushButton("确认执行操作")
        self.confirm_tool_button.setEnabled(False)
        self._clear_inline_approval()
        self.confirm_tool_button.clicked.connect(self.commit_tool)
        self.workflow_continue_button = QPushButton("继续工作流步骤")
        self.workflow_continue_button.clicked.connect(self.continue_workflow)
        self.workflow_retry_button = QPushButton("重试当前步骤")
        self.workflow_retry_button.clicked.connect(self.retry_workflow_step)
        self.workflow_practice_button = QPushButton("开始生成的练习")
        self.workflow_practice_button.clicked.connect(self.start_workflow_practice)
        self.workflow_review_button = QPushButton("查看知识点草稿")
        self.workflow_review_button.clicked.connect(self.open_knowledge_review)
        self.workflow_review_confirm_button = QPushButton("确认人工审核完成")
        self.workflow_review_confirm_button.clicked.connect(self.confirm_knowledge_review)
        self.workflow_cancel_button = QPushButton("取消工作流")
        self.workflow_cancel_button.clicked.connect(self.cancel_workflow)
        for button in (self.workflow_continue_button, self.workflow_retry_button, self.workflow_practice_button, self.workflow_review_button, self.workflow_review_confirm_button, self.workflow_cancel_button):
            button.setEnabled(False)
        activity_layout.addWidget(self.confirm_plan_button)
        activity_layout.addWidget(self.commit_plan_button)
        activity_layout.addWidget(self.confirm_tool_button)
        activity_layout.addWidget(self.workflow_continue_button)
        activity_layout.addWidget(self.workflow_retry_button)
        activity_layout.addWidget(self.workflow_practice_button)
        activity_layout.addWidget(self.workflow_review_button)
        activity_layout.addWidget(self.workflow_review_confirm_button)
        activity_layout.addWidget(self.workflow_cancel_button)
        for button in (
            self.handoffs_button, self.confirm_plan_button, self.commit_plan_button,
            self.confirm_tool_button, self.workflow_continue_button,
            self.workflow_retry_button, self.workflow_practice_button,
            self.workflow_review_button, self.workflow_review_confirm_button,
            self.workflow_cancel_button,
        ):
            button.hide()
        splitter.addWidget(activity)
        splitter.setSizes([760, 320])
        root.addWidget(splitter, 1)
        self._restore_session()
        for label in self.findChildren(QLabel):
            if "Agent" in label.text():
                label.setText("AI 中心")

    def refresh(self) -> None:
        return

    def open_skill_manager(self) -> None:
        SkillManagerDialog(self.skill_catalog, self).exec()

    def show_memories(self) -> None:
        if self.memory_service is None:
            QMessageBox.warning(self, "记忆不可用", "当前会话没有连接记忆服务。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Agent 记忆")
        dialog.resize(760, 440)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["ID", "范围", "课程", "类别", "内容", "更新时间"])
        table.setSelectionBehavior(QTableWidget.SelectRows)
        memories = self.memory_service.list_all_memories()
        table.setRowCount(len(memories))
        for row, item in enumerate(memories):
            try:
                content = json.loads(item.content_json or "{}")
            except json.JSONDecodeError:
                content = {"raw": item.content_json}
            values = (
                str(item.id), item.scope, str(item.course_id or "全局"), item.category,
                json.dumps(content, ensure_ascii=False), str(item.updated_at),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        actions = QHBoxLayout()
        delete = QPushButton("删除选中记忆")
        close = QPushButton("关闭")
        actions.addWidget(delete)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)

        def delete_selected() -> None:
            row = table.currentRow()
            if row < 0 or QMessageBox.question(
                dialog, "删除记忆", "删除后 Agent 将不再使用这条记忆，确认？"
            ) != QMessageBox.Yes:
                return
            memory_id = int(table.item(row, 0).text())
            self.memory_service.delete_memory(memory_id)
            table.removeRow(row)

        delete.clicked.connect(delete_selected)
        close.clicked.connect(dialog.accept)
        dialog.exec()

    def _restore_session(self) -> None:
        _, messages, calls = self.session_service.load(self.session_id)
        self.chat.clear()
        self.history = []
        for message in messages:
            name = "You" if message.role == "user" else "Agent"
            self.chat.append(f"**{name}**\n{message.content}")
            if message.role in {"user", "assistant"}:
                self.history.append({"role": message.role, "content": message.content})
        if not messages:
            self.chat.append("**AI Center**\nStart a conversation to create a learning plan or practice set.")
        for call in calls:
            self._add_tool_item(call.tool_name, call.status, call.detail)
        workflow = self.workflow_factory().latest_for_session(self.session_id)
        if workflow is not None:
            self.pending_workflow_id = workflow.id
            self._set_workflow_buttons(workflow.status, workflow.current_step)
            self._add_tool_item(
                f"workflow.{workflow.current_step}", workflow.status,
                workflow.error_message or "已恢复未完成工作流",
            )

    def show_handoff_history(self) -> None:
        handoffs = self.session_service.list_handoffs(self.session_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("Agent handoff history")
        dialog.resize(680, 460)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines: list[str] = []
        for item in handoffs:
            try:
                payload = json.loads(item.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {"raw": item.payload_json}
            lines.append(self._format_handoff(item.id, item.kind, item.target_id, item.created_at, payload))
        details.setPlainText("\n".join(lines) or "No handoffs have been recorded in this session.")
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    @staticmethod
    def _format_handoff(item_id: int, kind: str, target_id: int | None, created_at, payload: dict) -> str:
        if kind == "agent_handoff":
            return (
                f"#{item_id}  {payload.get('from_agent', '总控 Agent')} -> "
                f"{payload.get('to_agent', '未知 Agent')}  {created_at}\n"
                f"步骤：{payload.get('step', '-')} -> {payload.get('next_step', '-')}\n"
                f"输入摘要：{payload.get('input_summary', '')}\n"
                f"输出：{payload.get('output_summary', '')}\n"
                f"产物：{json.dumps(payload.get('artifact', {}), ensure_ascii=False)}\n"
            )
        return (
            f"#{item_id}  {kind}  target={target_id or '-'}  {created_at}\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        )

    def _set_workflow_buttons(self, status: str, step: str) -> None:
        self.workflow_state = (status, step)
        active = status not in {"completed", "cancelled"}
        self.workflow_continue_button.setEnabled(active and status in {"waiting_confirmation", "waiting_report"} and step != "practice")
        self.workflow_retry_button.setEnabled(active and status == "failed")
        self.workflow_practice_button.setEnabled(active and status == "waiting_confirmation" and step == "practice")
        reviewing = active and status == "waiting_review" and step == "review"
        self.workflow_review_button.setEnabled(reviewing)
        self.workflow_review_confirm_button.setEnabled(reviewing)
        self.workflow_cancel_button.setEnabled(active)
        self._refresh_inline_approval()

    def _clear_inline_approval(self) -> None:
        while self.inline_approval_buttons.count():
            item = self.inline_approval_buttons.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.inline_approval.hide()

    def _add_inline_action(self, label: str, callback: Callable[[], None]) -> None:
        button = QPushButton(label)
        button.clicked.connect(callback)
        self.inline_approval_buttons.addWidget(button)

    def _refresh_inline_approval(self) -> None:
        self._clear_inline_approval()
        if self.worker is not None or self.workflow_worker is not None:
            return
        if self.last_failed_worker is not None:
            self.inline_approval_title.setText("执行失败，可重试或取消。")
            self._add_inline_action("重试", self.retry_last_operation)
            self._add_inline_action("取消", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.pending_tool is not None:
            name, arguments = self.pending_tool
            self.inline_approval_title.setText(
                f"需要确认：{name}\n{json.dumps(arguments, ensure_ascii=False)[:240]}"
            )
            self._add_inline_action("确认执行", self.commit_tool)
            self._add_inline_action("拒绝", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.pending_research_candidates:
            self.inline_approval_title.setText("Confirmed candidates are ready to import into the local RAG library.")
            for item in self.pending_research_candidates:
                candidate_id = int(item["candidate_id"])
                self._add_inline_action(
                    f"Import #{candidate_id}",
                    # QPushButton.clicked emits a bool.  Keep it separate so
                    # it cannot overwrite the candidate id captured here.
                    lambda _checked=False, value=candidate_id: self.import_research_candidate(value),
                )
            self.inline_approval.show()
            return
        if self.pending_create_goal is not None:
            title, target_date, weekly_minutes, target_score, course_id = self.pending_create_goal
            self.inline_approval_title.setText(
                f"需要确认创建目标：{title}\n截止 {target_date}，每周 {weekly_minutes} 分钟"
            )
            self._add_inline_action("确认创建目标", self.commit_goal)
            self._add_inline_action("取消", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.pending_goal_id is not None:
            self.inline_approval_title.setText("需要确认：生成学习计划草稿")
            self._add_inline_action("确认生成", self.generate_plan)
            self._add_inline_action("取消", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.pending_draft_id is not None:
            self.inline_approval_title.setText("草稿已生成，需要确认是否写入学习任务")
            self._add_inline_action("确认写入", self.commit_plan)
            self._add_inline_action("取消", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.pending_memory is not None:
            scope, category, content, course_id = self.pending_memory
            self.inline_approval_title.setText(
                f"需要确认保存记忆：{category}\n"
                f"{json.dumps(content, ensure_ascii=False)}"
            )
            self._add_inline_action("确认保存记忆", self.commit_memory)
            self._add_inline_action("不保存", self.cancel_pending_approval)
            self.inline_approval.show()
            return
        if self.workflow_state is not None:
            status, step = self.workflow_state
            if status == "failed":
                self.inline_approval_title.setText("工作流步骤失败，需要确认是否重试")
                self._add_inline_action("重试当前步骤", self.retry_workflow_step)
            elif status == "waiting_review" and step == "review":
                self.inline_approval_title.setText("知识点草稿需要人工审核")
                self._add_inline_action("查看草稿", self.open_knowledge_review)
                self._add_inline_action("确认审核完成", self.confirm_knowledge_review)
            elif status == "waiting_confirmation" and step == "practice":
                self.inline_approval_title.setText("题目已生成，需要确认进入练习")
                self._add_inline_action("开始练习", self.start_workflow_practice)
            elif status in {"waiting_confirmation", "waiting_report"} and step != "practice":
                self.inline_approval_title.setText("工作流已暂停，需要确认继续下一步")
                self._add_inline_action("继续", self.continue_workflow)
            elif status not in {"completed", "cancelled", "running"}:
                self.inline_approval_title.setText("工作流需要人工操作")
            else:
                return
            self._add_inline_action("取消工作流", self.cancel_workflow)
            self.inline_approval.show()

    def cancel_pending_approval(self) -> None:
        self.pending_goal_id = None
        self.pending_draft_id = None
        self.pending_tool = None
        self.pending_research_candidates = []
        self.pending_create_goal = None
        self.pending_memory = None
        self.last_failed_worker = None
        self._clear_inline_approval()
        self.chat.append("\n**Agent**\n已取消本次待确认操作。")

    def _append_message(self, role: str, content: str) -> None:
        self.session_service.append_message(self.session_id, role, content)
        self.history.append({"role": role, "content": content})

    def _add_tool_item(self, tool_name: str, status: str, detail: str) -> None:
        labels = {"queued": "Queued", "running": "Running", "completed": "Completed", "failed": "Failed"}
        item = QListWidgetItem(f"{labels.get(status, status)}  {tool_name}")
        item.setData(Qt.UserRole, {"tool": tool_name, "status": status, "detail": detail})
        self.activity.addItem(item)
        self.activity.setCurrentItem(item)

    def send_message(self) -> None:
        message = self.input.toPlainText().strip()
        if not message or self.worker is not None:
            return
        self.input.clear()
        self._append_message("user", message)
        if len([item for item in self.history if item["role"] == "user"]) == 1:
            title = message.replace("\n", " ").strip()[:28]
            self.session_service.rename(self.session_id, title)
            self.session_title_changed.emit(self.session_id, title)
        self.chat.append(f"\n**你**\n{message}")
        self._start_live_trace()
        self._prepare_stream_output()
        self.chat.ensureCursorVisible()
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="chat",
            message=message,
            history=self.history,
        ))

    def cancel_active_request(self) -> None:
        """停止等待当前请求，避免后续结果继续写入对话。"""
        if self.worker is None:
            return
        self.worker.cancel()
        self.stop_button.setEnabled(False)
        self.chat.append("\n**Agent**\n已请求停止本次响应，正在结束当前调用。")
        self.record_agent_stage("agent.request", "cancelled", "用户停止等待本次响应")

    def toggle_execution_panel(self) -> None:
        visible = self.activity.isVisible()
        self.activity.setVisible(not visible)
        self.tool_detail.setVisible(not visible)
        self.activity_collapse_button.setText("展开" if visible else "收起")

    def _start_worker(self, worker: AgentWorker) -> None:
        self.last_failed_worker = None
        self.worker = worker
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.stop_button.show()
        worker.signals.decision.connect(self.receive_decision)
        worker.signals.preview.connect(self.receive_preview)
        worker.signals.practice.connect(self.receive_practice)
        worker.signals.report.connect(self.receive_report)
        worker.signals.result.connect(self.receive_result)
        worker.signals.tool_event.connect(self.record_tool_event)
        worker.signals.agent_stage.connect(self.record_agent_stage)
        worker.signals.text_delta.connect(self.append_stream_text)
        worker.signals.failed_detail.connect(self.record_failure_detail)
        worker.signals.failed.connect(self.receive_error)
        worker.signals.finished.connect(self.worker_finished)
        self.activity.addItem(f"开始：{worker.operation}")
        self.pool.start(worker)
        QTimer.singleShot(120_000, lambda expected=worker: self._timeout_worker(expected))

    def _timeout_worker(self, expected: AgentWorker) -> None:
        if self.worker is not expected:
            return
        expected.cancel("Request timed out after 120 seconds")
        self.record_agent_stage("agent.request", "timeout", "请求超过 120 秒，已停止接收后续结果")
        self.chat.append("\n**Agent**\n本次请求超时，已停止等待。可以重试。")

    def continue_workflow(self) -> None:
        if self.pending_workflow_id is None or self.workflow_worker is not None:
            return
        self._clear_inline_approval()
        worker = WorkflowWorker(factory=self.workflow_factory, workflow_id=self.pending_workflow_id)
        self.workflow_worker = worker
        self.send_button.setEnabled(False)
        self._set_workflow_buttons("running", "")
        worker.signals.tool_event.connect(self.record_tool_event)
        worker.signals.outcome.connect(self.receive_workflow_outcome)
        worker.signals.failed.connect(self.receive_workflow_error)
        worker.signals.finished.connect(self.workflow_finished)
        self.pool.start(worker)

    def retry_workflow_step(self) -> None:
        """Retry only the durable workflow step that failed."""
        if self.pending_workflow_id is None or self.workflow_worker is not None:
            return
        workflow = self.workflow_factory().get(self.pending_workflow_id)
        if workflow.status != "failed":
            return
        self.session_service.record_handoff(
            self.session_id,
            "agent_step_retry",
            target_id=workflow.id,
            payload={
                "from_agent": "总控 Agent",
                "to_agent": AgentWorkflowService.agent_for_step(workflow.current_step),
                "step": workflow.current_step,
                "reason": workflow.error_message,
            },
        )
        self.chat.append(
            f"\n**Agent**\n正在单独重试：{AgentWorkflowService.agent_for_step(workflow.current_step)}"
        )
        self.continue_workflow()

    def receive_workflow_outcome(self, outcome: WorkflowOutcome) -> None:
        self.pending_workflow_id = outcome.workflow_id
        self.session_service.record_handoff(
            self.session_id, "workflow_step", target_id=outcome.workflow_id,
            payload={"step": outcome.step, "status": outcome.status, "payload": outcome.payload},
        )
        workflow = self.workflow_factory().get(outcome.workflow_id)
        completed_step = "report" if outcome.status == "completed" else self._previous_workflow_step(outcome.step)
        specialist = AgentWorkflowService.agent_for_step(completed_step)
        artifact = {
            key: value for key, value in outcome.payload.items()
            if key.endswith("_id") or key.endswith("_ids") or key.endswith("_count")
        }
        self.record_tool_event(
            f"handoff.{specialist}", "completed",
            f"总控 Agent -> {specialist}\n"
            f"输入摘要：课程 #{workflow.course_id}；请求：{workflow.request[:120]}\n"
            f"输出：{outcome.summary}\n"
            f"产物：{json.dumps(artifact, ensure_ascii=False)}",
        )
        self.chat.append(f"\n**Agent**\n{outcome.summary}")
        self._append_message("assistant", outcome.summary)
        self._set_workflow_buttons(outcome.status, outcome.step)
        if outcome.status == "completed":
            snapshot_id = outcome.payload.get("report_snapshot_id")
            self.session_service.record_handoff(
                self.session_id, "report", target_id=snapshot_id,
                payload={"workflow_id": outcome.workflow_id},
            )
            if snapshot_id:
                self.chat.append(
                    f'<a href="report://download/{snapshot_id}">Download Markdown report</a>'
                )
            self.navigate_requested.emit("analytics")

    @staticmethod
    def _previous_workflow_step(next_step: str) -> str:
        return {
            "extract": "analyze",
            "review": "extract",
            "questions": "review",
            "practice": "questions",
            "report": "practice",
        }.get(next_step, next_step)

    def receive_workflow_error(self, message: str) -> None:
        self.chat.append(f"\n**Agent**\nWorkflow step failed: {message}")
        self._append_message("assistant", f"Workflow step failed: {message}")
        if self.pending_workflow_id is not None:
            workflow = self.workflow_factory().get(self.pending_workflow_id)
            self._set_workflow_buttons(workflow.status, workflow.current_step)

    def workflow_finished(self) -> None:
        self.workflow_worker = None
        self.send_button.setEnabled(True)
        self._refresh_inline_approval()

    def start_workflow_practice(self) -> None:
        if self.pending_workflow_id is None or self.workflow_worker is not None:
            return
        self._clear_inline_approval()
        service = self.workflow_factory()
        try:
            question_ids = service.question_ids(self.pending_workflow_id)
            if not question_ids:
                raise ValueError("No generated questions are available")
            self.session_service.record_handoff(
                self.session_id, "practice", target_id=self.pending_workflow_id,
                payload={"question_ids": question_ids},
            )
            self.workflow_practice_requested.emit(self.pending_workflow_id, question_ids)
        except ValueError as exc:
            self.receive_workflow_error(str(exc))

    def open_knowledge_review(self) -> None:
        if self.pending_workflow_id is None:
            return
        workflow = self.workflow_factory().get(self.pending_workflow_id)
        self.knowledge_review_requested.emit(workflow.course_id)

    def confirm_knowledge_review(self) -> None:
        if self.pending_workflow_id is None:
            return
        self._clear_inline_approval()
        try:
            outcome = self.workflow_factory().confirm_knowledge_review(self.pending_workflow_id)
            self.session_service.record_handoff(
                self.session_id, "knowledge_review", target_id=outcome.workflow_id,
                payload=outcome.payload,
            )
            self.receive_workflow_outcome(outcome)
        except ValueError as exc:
            self.receive_workflow_error(str(exc))

    def cancel_workflow(self) -> None:
        if self.pending_workflow_id is None:
            return
        self._clear_inline_approval()
        try:
            if self.workflow_worker is not None:
                self.workflow_worker.cancel()
            workflow = self.workflow_factory().cancel(self.pending_workflow_id)
            self.session_service.record_handoff(
                self.session_id, "workflow_cancelled", target_id=workflow.id,
                payload={"step": workflow.current_step},
            )
            self._set_workflow_buttons(workflow.status, workflow.current_step)
            self.chat.append("\n**Agent**\nWorkflow cancelled.")
            self._append_message("assistant", "Workflow cancelled.")
        except ValueError as exc:
            self.receive_workflow_error(str(exc))

    def prepare_for_shutdown(self) -> None:
        """Request cooperative cancellation before the database is closed."""
        if self.workflow_worker is None or self.pending_workflow_id is None:
            return
        self.workflow_worker.cancel("Application is closing")
        try:
            self.workflow_factory().cancel(self.pending_workflow_id)
        except ValueError:
            return

    def finish_workflow_practice(self, workflow_id: int) -> None:
        if workflow_id != self.pending_workflow_id:
            return
        try:
            outcome = self.workflow_factory().mark_practice_complete(workflow_id)
            self.receive_workflow_outcome(outcome)
        except ValueError as exc:
            self.receive_workflow_error(str(exc))

    def generate_report_after_practice(self) -> None:
        """Generate the report only after the user actually finishes practice."""
        if self.worker is not None:
            return
        self.session_service.record_handoff(
            self.session_id,
            "practice_completed",
            payload={"next_agent": "报告 Agent", "reason": "练习已完成，读取最新作答结果"},
        )
        self.chat.append("\n**Agent**\n练习已完成，正在根据你的作答结果生成学习报告。")
        self._start_live_trace()
        self._prepare_stream_output()
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="generate_report",
        ))

    def record_agent_stage(self, stage_name: str, status: str, detail: str) -> None:
        """Render transient live state without exposing hidden chain-of-thought."""
        self._append_live_stage(stage_name, status)
        self.tool_detail.setPlainText(
            f"Stage: {stage_name}\nStatus: {status}\n\n{detail}"
        )
        self.activity.record(stage_name, status, detail)

    def append_stream_text(self, text: str) -> None:
        """Append safe model output fragments on the GUI thread."""
        if not text:
            return
        self.stream_output.insertPlainText(text)
        self.stream_output.verticalScrollBar().setValue(
            self.stream_output.verticalScrollBar().maximum()
        )

    def _start_live_trace(self) -> None:
        self._live_stages = []
        self._live_trace_persisted = False
        self.live_status.setText("AI 正在准备执行...")
        self.live_status.show()

    def _prepare_stream_output(self) -> None:
        self.stream_output.clear()
        self.stream_output.show()

    def _append_live_stage(self, stage_name: str, status: str) -> None:
        names = {
            "agent.request": "接收请求",
            "agent.context": "读取学习数据",
            "agent.model": "分析并生成回复",
            "agent.reasoning": "整理决策依据",
            "agent.decide": "判断下一步操作",
            "learning_plan.generate": "生成学习计划",
            "learning_plan.confirm": "写入学习任务",
            "question_generation.generate": "生成练习题",
            "question_generation.retry": "重试生成题目",
            "learning_report.collect": "收集学习数据",
            "learning_report.generate": "生成学习报告",
            "learning_goal.create": "创建学习目标",
        }
        name = names.get(stage_name)
        if name and name not in self._live_stages:
            self._live_stages.append(name)
        if status in {"failed", "cancelled", "timeout"}:
            suffix = "执行已停止" if status != "failed" else "执行失败"
        elif status == "completed":
            suffix = "正在收尾"
        else:
            suffix = "执行中"
        trail = " -> ".join(self._live_stages[-5:]) or "准备执行"
        self.live_status.setText(f"AI {suffix}: {trail}")
        self.live_status.show()

    def _finish_live_trace(self) -> None:
        if self._live_stages and not self._live_trace_persisted:
            steps = "\n".join(
                f"{index}. {stage}" for index, stage in enumerate(self._live_stages, start=1)
            )
            transcript = f"**执行思考摘要**\n{steps}"
            self.chat.append(f"\n**Agent**\n{transcript}")
            self._append_message("assistant", transcript)
            self._live_trace_persisted = True
        if self.live_status.isVisible():
            self.live_status.setText("AI 已完成本次操作")
            QTimer.singleShot(2500, self.live_status.hide)
        QTimer.singleShot(2500, self.stream_output.hide)

    def record_tool_event(self, tool_name: str, status: str, detail: str) -> None:
        self.session_service.record_tool_call(self.session_id, tool_name, status, detail)
        self.activity.record(tool_name, status, detail)
        if self.worker is not None and status in {"queued", "running", "completed", "failed"}:
            label = "调用" if status in {"queued", "running"} else "完成"
            self.append_stream_text(f"\n[{label}工具] {tool_name}\n")

    def show_tool_detail(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.tool_detail.clear()
            return
        event = current.data(Qt.UserRole) or {}
        detail = event.get("detail", "")
        if not self.developer_mode.isChecked():
            detail = detail.split("\n\n", 1)[0]
        internal = event.get("internal_name", "")
        internal_line = (
            f"\nInternal event: {internal}"
            if self.developer_mode.isChecked() and internal else ""
        )
        self.tool_detail.setPlainText(
            f"任务: {event.get('tool', '')}\n"
            f"状态: {event.get('status', '')}{internal_line}\n\n{detail}"
        )
        return
        self.tool_detail.setPlainText(
            f"工具：{event.get('tool', '')}\n"
            f"状态：{event.get('status', '')}\n\n"
            f"{event.get('detail', '')}"
        )

    def receive_decision(self, decision: AgentDecision) -> None:
        reasoning = [item.strip() for item in decision.reasoning_summary if item.strip()]
        message = decision.reply
        if reasoning:
            summary = "\n".join(f"- {item}" for item in reasoning)
            message += f"\n\n**决策依据**\n{summary}"
            self.record_agent_stage("agent.reasoning", "completed", summary)
        if decision.action != "generate_report":
            self.chat.append(f"\n**Agent**\n{message}")
            self._append_message("assistant", message)
        self.activity.addItem(f"判断动作：{decision.action}")
        specialist = {
            "generate_plan": "学习计划 Agent",
            "generate_questions": "出题 Agent",
            "generate_report": "报告 Agent",
            "start_workflow": "总控 Agent",
        }.get(decision.action)
        if specialist is not None:
            input_summary = self.history[-1]["content"][:160] if self.history else ""
            dispatch_detail = (
                f"总控 Agent -> {specialist}\n"
                f"输入摘要：{input_summary}\n"
                f"动作：{decision.action}\n"
                f"回复摘要：{decision.reply[:240]}"
            )
            self.session_service.record_handoff(
                self.session_id,
                "agent_assignment",
                payload={
                    "from_agent": "总控 Agent",
                    "to_agent": specialist,
                    "action": decision.action,
                    "input_summary": input_summary,
                },
            )
            self.record_tool_event(f"dispatch.{specialist}", "completed", dispatch_detail)
        if decision.action == "create_goal":
            if not decision.goal_title.strip():
                self.chat.append("\n**Agent**\n请告诉我目标名称，例如：通过高等数学期末考试。")
                return
            self.pending_create_goal = (
                decision.goal_title.strip(),
                decision.goal_target_date or date.today() + timedelta(days=30),
                decision.goal_weekly_minutes,
                decision.goal_target_score,
                decision.course_id,
            )
        elif decision.action == "generate_plan":
            self.pending_goal_id = decision.goal_id
            self.pending_daily_minutes = decision.daily_minutes
            self.confirm_plan_button.setEnabled(True)
            self.chat.append("\n计划会先生成草稿，不会立即写入任务。请确认后继续。")

        elif decision.action == "remember":
            if not decision.memory_category:
                self.chat.append("\n**Agent**\n没有识别出要保存的记忆类别。")
                return
            try:
                content = json.loads(decision.memory_content_json or "{}")
            except json.JSONDecodeError:
                content = {}
            if not isinstance(content, dict) or not content:
                self.chat.append("\n**Agent**\n记忆内容为空，暂不保存。")
                return
            self.pending_memory = (
                decision.memory_scope, decision.memory_category, content, decision.course_id
            )
            self.chat.append("\n**Agent**\n我只会在你确认后保存这条记忆。")

        elif decision.action == "navigate" and decision.route:
            self.session_service.record_handoff(
                self.session_id, "navigate", payload={"route": decision.route}
            )
            self.navigate_requested.emit(decision.route)
            self.activity.addItem(f"已跳转到：{decision.route}")
        elif decision.action == "tool" and decision.tool_name:
            self.pending_tool = (decision.tool_name, decision.tool_arguments)
            risk = "requires confirmation" if decision.tool_name in {
                "mcp.write_workspace_file", "mcp.run_python_in_sandbox"
            } else "read-only"
            self.record_tool_event(
                decision.tool_name,
                "queued",
                f"Risk: {risk}\nInput:\n{json.dumps(decision.tool_arguments, ensure_ascii=False, indent=2)}",
            )
            if decision.tool_name in {"mcp.search_web", "mcp.fetch_public_url"}:
                self.chat.append(f"\n**Agent**\n正在执行只读联网查询：`{decision.tool_name}`")
                self._start_worker(AgentWorker(
                    factory=self.agent_factory, operation="tool", tool_name=decision.tool_name,
                    tool_arguments=decision.tool_arguments, confirmed=False,
                ))
            else:
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
        elif decision.action == "generate_report":
            self._start_worker(AgentWorker(factory=self.agent_factory, operation="generate_report"))
        elif decision.action == "research_collect":
            if not decision.course_id:
                self.chat.append("\n**Agent**\nPlease specify the course before researching resources.")
                return
            self._start_worker(AgentWorker(
                factory=self.agent_factory,
                operation="research_collect",
                course_id=decision.course_id,
                research_request=decision.research_request or self.history[-1]["content"],
            ))
        elif decision.action == "start_workflow":
            if not decision.course_id:
                self.chat.append("\n**Agent**\n请先选择课程，再启动学习闭环。")
                return
            try:
                workflow = self.workflow_factory().create(
                    session_id=self.session_id,
                    course_id=decision.course_id,
                    request=decision.question_request or decision.reply,
                )
                self.pending_workflow_id = workflow.id
                self.session_service.record_handoff(
                    self.session_id, "workflow_created", target_id=workflow.id,
                    payload={"course_id": decision.course_id, "step": workflow.current_step},
                )
                self.chat.append("\n**Agent**\n学习闭环已创建。请确认第一步：分析课程资料。")
                self._append_message("assistant", "学习闭环已创建。请确认第一步：分析课程资料。")
                self._set_workflow_buttons(workflow.status, workflow.current_step)
            except ValueError as exc:
                self.receive_workflow_error(str(exc))

        self._refresh_inline_approval()

    def commit_memory(self) -> None:
        if self.pending_memory is None or self.memory_service is None:
            return
        scope, category, content, course_id = self.pending_memory
        try:
            self.memory_service.remember(
                scope=scope, category=category, content=content,
                course_id=course_id, confirmed=True,
            )
            self.pending_memory = None
            self.chat.append("\n**Agent**\n已保存到确认记忆。你可以在“记忆”中查看或删除。")
        except (PermissionError, ValueError) as exc:
            self.chat.append(f"\n**Agent**\n记忆保存失败：{exc}")
        self._refresh_inline_approval()

    def receive_practice(self, generated: GeneratedPractice) -> None:
        self.session_service.record_handoff(
            self.session_id, "practice",
            payload={"question_ids": list(generated.question_ids), "request": generated.request},
        )
        self._append_message("assistant", f"Generated {len(generated.question_ids)} questions and handed them to practice.")
        self.chat.append(
            f"\n**Agent**\n已生成 {len(generated.question_ids)} 道题目，正在交给练习中心。"
        )
        self.activity.addItem("题目已生成，交给练习中心")
        self.record_tool_event("practice.open", "completed", "已打开生成题目的练习会话")
        self.practice_requested.emit(generated.question_ids)

    def receive_report(self, report: GeneratedReport) -> None:
        self.session_service.record_handoff(
            self.session_id, "report", target_id=report.snapshot_id,
            payload={"start_date": str(report.start_date), "end_date": str(report.end_date)},
        )
        summary = f"学习报告已生成（{report.start_date} 至 {report.end_date}）。"
        report_message = (
            f"{summary}\n\n{report.markdown}\n\n"
            f"[下载学习报告（Markdown / HTML / Word / PDF）]"
            f"(report://download/{report.snapshot_id})"
        )
        self._append_message("assistant", report_message)
        self.chat.append(f"\n**Agent**\n{report_message}")

    def download_report(self, url: QUrl) -> None:
        if url.scheme() != "report" or url.host() != "download":
            return
        try:
            snapshot_id = int(url.path().strip("/"))
        except ValueError:
            return
        reports = self.workflow_factory().report_factory().list_snapshots()
        report = next((item for item in reports if item.id == snapshot_id), None)
        if report is None:
            QMessageBox.warning(self, "Learning report", "Report was not found. Generate it again.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Download AI learning report",
            f"learning-report-{report.start_date}-{report.end_date}.md",
            "Markdown (*.md);;HTML (*.html);;Word document (*.docx);;PDF (*.pdf)",
        )
        if not filename:
            return
        try:
            export_report(report.markdown, Path(filename))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Download failed", str(exc))

    def commit_goal(self) -> None:
        if self.pending_create_goal is None or self.worker is not None:
            return
        self._clear_inline_approval()
        title, target_date, weekly_minutes, target_score, course_id = self.pending_create_goal
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="create_goal",
            goal_title=title,
            goal_target_date=target_date,
            goal_weekly_minutes=weekly_minutes,
            goal_target_score=target_score,
            course_id=course_id,
        ))

    def generate_plan(self) -> None:
        if self.pending_goal_id is None or self.worker is not None:
            return
        self._clear_inline_approval()
        self.confirm_plan_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="generate",
            goal_id=self.pending_goal_id,
            daily_minutes=self.pending_daily_minutes,
        ))

    def receive_preview(self, preview: PlanPreview) -> None:
        self.pending_draft_id = preview.draft_id
        self.session_service.record_handoff(
            self.session_id, "plan_draft", target_id=preview.draft_id,
            payload={"summary": preview.summary, "tasks": list(preview.tasks)},
        )
        lines = [f"**计划草稿 #{preview.draft_id}**", preview.summary, ""]
        lines.extend(
            f"- {item['date']} {item['title']}（{item['duration_minutes']} 分钟）"
            for item in preview.tasks
        )
        if preview.risks:
            lines.extend(["", "风险：", *[f"- {risk}" for risk in preview.risks]])
        self.chat.append("\n" + "\n".join(lines))
        self._append_message("assistant", "\n".join(lines))
        self.commit_plan_button.setEnabled(True)
        self.activity.addItem(f"已生成草稿 #{preview.draft_id}，等待写入确认")

    def commit_plan(self) -> None:
        if self.pending_draft_id is None or self.worker is not None:
            return
        self._clear_inline_approval()
        self.commit_plan_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="confirm",
            draft_id=self.pending_draft_id,
        ))

    def commit_tool(self) -> None:
        if self.pending_tool is None or self.worker is not None:
            return
        self._clear_inline_approval()
        name, arguments = self.pending_tool
        message = (
            f"Tool: {name}\n\n"
            f"Input:\n{json.dumps(arguments, ensure_ascii=False, indent=2)}\n\n"
            "Continue only if this operation matches your intent."
        )
        if QMessageBox.question(self, "Confirm agent tool", message) != QMessageBox.Yes:
            self.confirm_tool_button.setEnabled(True)
            self.record_tool_event(name, "failed", "User declined the tool call")
            return
        self.confirm_tool_button.setEnabled(False)
        self._start_worker(AgentWorker(
            factory=self.agent_factory,
            operation="tool",
            tool_name=name,
            tool_arguments=arguments,
            confirmed=True,
        ))

    def receive_result(self, result: object) -> None:
        operation = self.worker.operation if self.worker is not None else "confirm"
        if operation == "research_collect":
            candidates = result if isinstance(result, list) else []
            accepted = [item for item in candidates if isinstance(item, dict) and item.get("status") == "pending"]
            lines = ["**Research candidates**", "Only accepted candidates can be imported; each import needs a click confirmation."]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- #{item.get('candidate_id')} [{item.get('title', 'Source')}]({item.get('url', '')}) "
                    f"— relevance {item.get('relevance_score', 0)}, quality {item.get('quality_score', 0)}\n"
                    f"  {item.get('reason', '')}"
                )
            message = "\n".join(lines)
            self._append_message("assistant", message)
            self.chat.append(f"\n**Agent**\n{message}")
            self.pending_research_candidates = accepted
            self._refresh_inline_approval()
            return
        if operation == "research_import":
            item = result if isinstance(result, dict) else {}
            message = f"Imported `{item.get('resource_name', '')}` as resource #{item.get('resource_id', '')} and completed RAG indexing."
            self._append_message("assistant", message)
            self.chat.append(f"\n**Agent**\n{message}")
            return
        if operation == "create_goal":
            goal = result if isinstance(result, dict) else {"goal_id": result}
            message = (
                f"目标已创建：{goal.get('title', '')}\n"
                f"截止日期：{goal.get('target_date', '')}\n"
                f"每周学习：{goal.get('weekly_minutes', '')} 分钟"
            )
            self.session_service.record_handoff(
                self.session_id, "goal_created", target_id=goal.get("goal_id"), payload=goal,
            )
            self._append_message("assistant", message)
            self.chat.append(f"\n**Agent**\n{message}")
            self.pending_create_goal = None
            return
        if operation != "confirm":
            tool_name = self.pending_tool[0] if self.pending_tool else "tool"
            detail = self._format_tool_result(result, tool_name)
            self.session_service.record_handoff(
                self.session_id, "tool_result", payload={"tool": tool_name, "result": result},
            )
            reply = f"Tool `{tool_name}` completed.\n\n{detail}"
            self._append_message("assistant", reply)
            self.chat.append(f"\n**Agent**\n{reply}")
            self.record_tool_event(tool_name, "completed", detail)
            self.pending_tool = None
            return

        count = result
        if operation == "confirm":
            self.session_service.record_handoff(
                self.session_id, "plan_committed", target_id=self.pending_draft_id,
                payload={"task_count": count},
            )
            self._append_message("assistant", f"Confirmed and wrote {count} learning tasks.")
        else:
            self.session_service.record_handoff(
                self.session_id, "tool_result", payload={"result": result},
            )
            self._append_message("assistant", "Confirmed project operation completed.")
        self.chat.append(f"\n**Agent**\n已确认并写入 {count} 个学习任务。")
        self.activity.addItem(f"已写入 {count} 个学习任务")
        self.pending_draft_id = None
        self.pending_tool = None

    def import_research_candidate(self, candidate_id: int) -> None:
        if self.worker is not None:
            return
        if QMessageBox.question(
            self, "Confirm resource import",
            f"Download candidate #{candidate_id}, save it to the local resource library, and create its RAG index?",
        ) != QMessageBox.Yes:
            return
        self.pending_research_candidates = [
            item for item in self.pending_research_candidates
            if int(item["candidate_id"]) != candidate_id
        ]
        self._clear_inline_approval()
        self._start_worker(AgentWorker(
            factory=self.agent_factory, operation="research_import",
            candidate_id=candidate_id, confirmed=True,
        ))

    @staticmethod
    def _format_tool_result(result: object, tool_name: str = "") -> str:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                text = "\n".join(str(item) for item in content)
            else:
                text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        else:
            text = str(result)
        if tool_name.endswith("search_web"):
            try:
                sources = json.loads(text)
            except json.JSONDecodeError:
                sources = []
            if isinstance(sources, list) and sources and isinstance(sources[0], dict):
                text = "\n\n".join(
                    f"[{item.get('title', 'Source')}]({item.get('url', '')})\n"
                    f"{item.get('description', '')}"
                    for item in sources
                )
        return text[:4000] + ("\n... output truncated" if len(text) > 4000 else "")

    def receive_error(self, message: str) -> None:
        self.last_failed_worker = self.worker
        self._append_message("assistant", f"Execution failed: {message}")
        self.chat.append(f"\n**Agent**\n执行失败：{message}")
        self.activity.addItem("执行失败")
        self.confirm_plan_button.setEnabled(False)
        self.commit_plan_button.setEnabled(False)
        self.confirm_tool_button.setEnabled(False)
        QMessageBox.warning(self, "Agent 执行失败", message)

    def retry_last_operation(self) -> None:
        if self.last_failed_worker is None or self.worker is not None:
            return
        self._clear_inline_approval()
        self._start_worker(self.last_failed_worker.retry_clone())

    def record_failure_detail(self, message: str, stack: str) -> None:
        """保留开发排障所需的完整堆栈，普通界面只显示简短错误。"""
        self.session_service.record_tool_call(
            self.session_id, "agent.error", "failed", message,
            output_data={"traceback": stack},
        )
        self.activity.record("agent.error", "failed", message + "\n\n" + stack)

    def worker_finished(self, finished_worker: AgentWorker) -> None:
        if self.worker is not finished_worker:
            return
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
        self.stop_button.hide()
        self._finish_live_trace()
        self._refresh_inline_approval()
