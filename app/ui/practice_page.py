from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QDateTimeAxis,
    QLineSeries, QValueAxis,
)
from PySide6.QtCore import QDateTime, QObject, QRunnable, QThreadPool, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.services.domain import (
    AnalyticsService, JobService, MaintenanceService, QuestionService, ResourceService, ReviewService,
)
from app.tools.registry import ToolRegistry
from app.ui.pages import page_title, stat_card
from app.ui.icons import IconProvider
from ai.chains import (
    KnowledgeDraftService,
    KnowledgeExtractionService,
    QuestionDraftService,
    QuestionGenerationService,
    SubjectiveGradingService,
    ErrorAnalysisService,
)
from ai.retrieval import KnowledgePointIndex
from app.ui.knowledge_extraction_widget import KnowledgeExtractionWidget
from app.ui.question_generation_widget import QuestionGenerationWidget
from app.ui.math_renderer import MathChoice, MathTextView


def _selected_id(table: QTableWidget) -> int | None:
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, 0)
    return int(item.data(Qt.UserRole)) if item else None


def render_math_text(text: str) -> str:
    """Turn common LaTeX emitted by question generators into readable Qt text."""
    value = text.replace("\\n", "\n")
    value = value.replace("\\(", "").replace("\\)", "")
    value = value.replace("\\[", "").replace("\\]", "")
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("\\,", " ").replace("\\!", "")

    def fraction(match: re.Match[str]) -> str:
        return f"({render_math_text(match.group(1))})/({render_math_text(match.group(2))})"

    def square_root(match: re.Match[str]) -> str:
        return f"√({render_math_text(match.group(1))})"

    def integral(match: re.Match[str]) -> str:
        lower = render_math_text(match.group(1).strip("{}"))
        upper = render_math_text(match.group(2).strip("{}"))
        return f"∫[{lower}, {upper}]"

    value = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", fraction, value)
    value = re.sub(r"\\sqrt\{([^{}]*)\}", square_root, value)
    value = re.sub(r"\\int_((?:\{[^{}]*\})|\S+)\^(\{[^{}]*\}|\S+)", integral, value)
    replacements = {
        r"\pi": "π", r"\theta": "θ", r"\alpha": "α", r"\beta": "β",
        r"\gamma": "γ", r"\delta": "δ", r"\sin": "sin", r"\cos": "cos",
        r"\tan": "tan", r"\ln": "ln", r"\log": "log", r"\cdot": "·",
        r"\times": "×", r"\leq": "≤", r"\geq": "≥", r"\neq": "≠",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = value.replace("{", "(").replace("}", ")")
    return re.sub(r"\\([A-Za-z]+)", r"\1", value)


class QuestionDialog(QDialog):
    def __init__(
        self, service: QuestionService, parent: QWidget | None = None, question: object | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("编辑题目")
        self.resize(560, 430)
        form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["单选", "多选", "判断", "填空", "简答"])
        self.prompt = QTextEdit()
        self.course = QComboBox()
        self.course.addItem("未关联", None)
        for item in service.list_courses():
            self.course.addItem(item.name, item.id)
        self.knowledge = QComboBox()
        self.knowledge.addItem("未关联", None)
        for item in service.list_knowledge():
            self.knowledge.addItem(item.name, item.id)
        self.answer = QTextEdit()
        self.options = QTextEdit()
        self.options.setPlaceholderText("选择题每行一个选项，例如 A. 北京")
        self.options.setMaximumHeight(90)
        self.explanation = QTextEdit()
        self.explanation.setMaximumHeight(80)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("逗号分隔")
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(3)
        form.addRow("题型", self.kind)
        form.addRow("课程", self.course)
        form.addRow("知识点", self.knowledge)
        form.addRow("题干 *", self.prompt)
        form.addRow("选项", self.options)
        form.addRow("标准答案 *", self.answer)
        form.addRow("解析", self.explanation)
        form.addRow("标签", self.tags)
        form.addRow("难度", self.difficulty)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if question:
            self.kind.setCurrentText(question.kind)
            course_index = self.course.findData(question.course_id)
            self.course.setCurrentIndex(max(0, course_index))
            knowledge_index = self.knowledge.findData(question.knowledge_point_id)
            self.knowledge.setCurrentIndex(max(0, knowledge_index))
            self.prompt.setPlainText(question.prompt)
            self.options.setPlainText(question.options)
            self.answer.setPlainText(question.answer)
            self.explanation.setPlainText(question.explanation)
            self.tags.setText(question.tags)
            self.difficulty.setValue(question.difficulty)


class SubjectiveGradingSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class SubjectiveGradingWorker(QRunnable):
    def __init__(self, *, grading_factory, jobs: JobService, job_id: int, attempt_id: int) -> None:
        super().__init__()
        self.grading_factory = grading_factory
        self.jobs = jobs
        self.job_id = job_id
        self.attempt_id = attempt_id
        self.signals = SubjectiveGradingSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if self.jobs.is_cancelled(self.job_id):
                self.signals.failed.emit("批改任务已取消")
                return
            self.jobs.update(self.job_id, "running", 10, "正在准备主观题批改")
            result = self.grading_factory().grade_attempt(self.attempt_id)
            self.jobs.update(
                self.job_id, "completed", 100,
                f"批改完成，得分 {result.total_score:.1f}/{result.max_score:.1f}",
            )
            self.signals.succeeded.emit(result)
        except Exception as exc:
            self.jobs.update(self.job_id, "failed", 100, "主观题批改失败", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class SubjectiveGradingDialog(QDialog):
    def __init__(self, result: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 主观题批改")
        self.resize(760, 620)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"总分：{result.total_score:.1f} / {result.max_score:.1f}"))
        root.addWidget(QLabel(f"置信度：{result.confidence:.0%}"))
        if result.needs_human_review:
            warning = QLabel("建议人工复核：当前批改置信度不足或证据不充分。")
            warning.setStyleSheet("color: #c0392b; font-weight: 600;")
            root.addWidget(warning)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines = ["【总体反馈】", result.feedback, "", "【引用依据】"]
        for citation in result.citations:
            lines.extend([
                f"[D{citation.number}] {citation.source_name} {citation.location_label}",
                citation.quote_text,
            ])
        text.setPlainText("\n".join(lines))
        root.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)


class ErrorAnalysisSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class ErrorAnalysisWorker(QRunnable):
    def __init__(self, *, analysis_factory, jobs: JobService, job_id: int, attempt_id: int) -> None:
        super().__init__()
        self.analysis_factory = analysis_factory
        self.jobs = jobs
        self.job_id = job_id
        self.attempt_id = attempt_id
        self.signals = ErrorAnalysisSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if self.jobs.is_cancelled(self.job_id):
                self.signals.failed.emit("错误分析任务已取消")
                return
            self.jobs.update(self.job_id, "running", 20, "正在分析答题错误原因")
            result = self.analysis_factory().analyze_attempt(self.attempt_id)
            self.jobs.update(self.job_id, "completed", 100, "错误原因分析完成")
            self.signals.succeeded.emit(result)
        except Exception as exc:
            self.jobs.update(self.job_id, "failed", 100, "错误原因分析失败", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ErrorAnalysisDialog(QDialog):
    def __init__(self, result: object, *, confirm_callback, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.confirm_callback = confirm_callback
        self.setWindowTitle("AI 错误原因分析")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"错误类型：{', '.join(result.error_types)}"))
        layout.addWidget(QLabel(f"严重程度：{result.severity}"))
        layout.addWidget(QLabel(f"置信度：{result.confidence:.0%}"))
        if result.needs_human_review:
            warning = QLabel("该结果需要人工复核，AI 不能自动写入错题记录。")
            warning.setStyleSheet("color: #c0392b; font-weight: 600;")
            layout.addWidget(warning)
        layout.addWidget(QLabel("错误原因"))
        self.reason = QPlainTextEdit()
        self.reason.setPlainText(result.explanation)
        layout.addWidget(self.reason)
        confirm = QPushButton("确认并写入错题")
        confirm.clicked.connect(self.confirm)
        layout.addWidget(confirm)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def confirm(self) -> None:
        reason = self.reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "内容为空", "请输入错误原因。")
            return
        try:
            self.confirm_callback(reason)
            QMessageBox.information(self, "保存成功", "错误原因已写入错题记录。")
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))


class PracticeDialog(QDialog):
    completed = Signal()
    def __init__(
        self, service: QuestionService, parent: QWidget | None = None,
        resumed: tuple[object, list[object]] | None = None, immediate_feedback: bool = True,
        *, jobs: JobService | None = None,
        grading_factory: Callable[[], SubjectiveGradingService] | None = None,
        analysis_factory: Callable[[], ErrorAnalysisService] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.immediate_feedback = immediate_feedback
        self.jobs = jobs
        self.grading_factory = grading_factory
        self.analysis_factory = analysis_factory
        self.error_worker = None
        self.grading_worker = None
        self.setWindowTitle("快速练习")
        self.resize(700, 520)
        self.practice, self.questions = resumed or service.create_practice(10, seed=None)
        self.index = 0
        self.responses: dict[int, str] = service.saved_responses(self.practice.id)
        root = QVBoxLayout(self)
        self.progress = QLabel()
        self.prompt = MathTextView(parent=self)
        self.prompt.setMinimumHeight(72)
        self.response = QTextEdit()
        self.response.setPlaceholderText("输入答案；多选答案用英文逗号分隔")
        self.choice_area = QWidget()
        self.choice_layout = QVBoxLayout(self.choice_area)
        self.choice_layout.setContentsMargins(0, 0, 0, 0)
        self.choice_buttons: list[MathChoice] = []
        self.choice_group = QButtonGroup(self)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        buttons = QHBoxLayout()
        previous = QPushButton("上一题")
        previous.clicked.connect(self.previous)
        submit = QPushButton("提交本题")
        submit.setProperty("primary", True)
        submit.clicked.connect(self.submit)
        next_button = QPushButton("下一题")
        next_button.clicked.connect(self.next)
        mark = QPushButton("标记/取消标记")
        mark.clicked.connect(self.mark)
        finish = QPushButton("结束练习")
        finish.clicked.connect(self.finish)
        self.ai_grade_button = QPushButton("AI 批改")
        self.ai_grade_button.clicked.connect(self.ai_grade)
        self.ai_grade_button.setEnabled(jobs is not None and grading_factory is not None)
        self.error_button = QPushButton("分析错误原因")
        self.error_button.clicked.connect(self.analyze_error)
        self.error_button.setEnabled(jobs is not None and analysis_factory is not None)
        for button in (previous, submit, next_button, mark, self.ai_grade_button, self.error_button, finish):
            buttons.addWidget(button)
        root.addWidget(self.progress)
        root.addWidget(self.prompt)
        root.addWidget(self.choice_area)
        root.addWidget(self.response)
        root.addWidget(self.feedback)
        root.addLayout(buttons)
        self.show_question()

    def show_question(self) -> None:
        question = self.questions[self.index]
        self.progress.setText(f"第 {self.index + 1} / {len(self.questions)} 题 · {question.kind} · 难度 {question.difficulty}")
        self.prompt.fallback.setText(render_math_text(question.prompt))
        self.prompt.set_math_text(question.prompt)
        self._render_choices(question)
        if self.choice_buttons:
            self.response.clear()
        else:
            self.response.setPlainText(self.responses.get(question.id, ""))
        self.feedback.clear()

    def _render_choices(self, question: object) -> None:
        while self.choice_layout.count():
            item = self.choice_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.choice_buttons = []
        self.choice_group = QButtonGroup(self)
        lines = [line.strip() for line in question.options.splitlines() if line.strip()]
        is_choice = question.kind in {"单选", "多选", "判断"} and bool(lines)
        self.choice_area.setVisible(is_choice)
        self.response.setVisible(not is_choice)
        if not is_choice:
            return
        selected = {part.strip().casefold() for part in self.responses.get(question.id, "").split(",")}
        for line in lines:
            match = re.match(r"\s*([A-Za-z])(?:[.、:：)|）])\s*(.*)", line)
            value = match.group(1).upper() if match else line
            button = MathChoice(
                line, multiple=question.kind == "多选",
                fallback_text=render_math_text(line), parent=self.choice_area,
            )
            button.control.setProperty("answer_value", value)
            button.control.setChecked(value.casefold() in selected)
            if isinstance(button.control, QRadioButton):
                self.choice_group.addButton(button.control)
            self.choice_buttons.append(button)
            self.choice_layout.addWidget(button)

    def _response_value(self) -> str:
        if not self.choice_buttons:
            return self.response.toPlainText()
        return ",".join(
            str(button.control.property("answer_value"))
            for button in self.choice_buttons if button.control.isChecked()
        )

    def submit(self) -> None:
        question = self.questions[self.index]
        response = self._response_value()
        if not response.strip():
            QMessageBox.warning(self, "答案为空", "请选择或输入答案后再提交。")
            return
        self.responses[question.id] = response
        if question.kind == "简答":
            result = QMessageBox.question(self, "简答题自评", f"标准答案：\n{question.answer}\n\n你的回答是否掌握？") == QMessageBox.Yes
            correct = self.service.submit(self.practice.id, question.id, response, self_grade=result)
        else:
            correct = self.service.submit(self.practice.id, question.id, response)
        if self.immediate_feedback:
            self.feedback.setText(("回答正确" if correct else f"回答错误；标准答案：{question.answer}") if correct is not None else "已记录自评")
        else:
            self.feedback.setText("答案已保存，提交整套练习后查看结果。")

    def ai_grade(self) -> None:
        question = self.questions[self.index]
        if question.kind != "简答题":
            QMessageBox.information(self, "无法批改", "AI 批改目前只支持简答题。")
            return
        if not self.response.toPlainText().strip():
            QMessageBox.warning(self, "答案为空", "请先输入答案并提交本题。")
            return
        self.save_current_draft()
        attempt_id = self.service.get_attempt_id(self.practice.id, question.id)
        if attempt_id is None or self.jobs is None or self.grading_factory is None:
            QMessageBox.warning(self, "无法批改", "请先提交本题，并确认 AI 服务已配置。")
            return
        job = self.jobs.create("subjective_grading", f"批改题目：{question.prompt[:80]}")
        self.ai_grade_button.setEnabled(False)
        self.feedback.setText("AI 正在批改，请稍候……")
        worker = SubjectiveGradingWorker(
            grading_factory=self.grading_factory, jobs=self.jobs,
            job_id=job.id, attempt_id=attempt_id,
        )
        worker.signals.succeeded.connect(lambda result: SubjectiveGradingDialog(result, self).exec())
        worker.signals.failed.connect(lambda message: self.show_grading_error(message))
        worker.signals.finished.connect(lambda: self.ai_grade_button.setEnabled(True))
        self.grading_worker = worker
        QThreadPool.globalInstance().start(worker)

    def show_grading_error(self, message: str) -> None:
        self.feedback.setText(f"AI 批改失败：{message}")
        QMessageBox.warning(self, "AI 批改失败", message)

    def analyze_error(self) -> None:
        if self.jobs is None or self.analysis_factory is None:
            QMessageBox.warning(self, "AI 不可用", "当前未配置错误分析服务。")
            return
        question = self.questions[self.index]
        attempt_id = self.service.get_attempt_id(self.practice.id, question.id)
        if attempt_id is None:
            QMessageBox.warning(self, "无法分析", "请先提交当前题目。")
            return
        job = self.jobs.create("error_analysis", f"分析题目错误：{question.prompt[:80]}")
        self.error_button.setEnabled(False)
        worker = ErrorAnalysisWorker(
            analysis_factory=self.analysis_factory,
            jobs=self.jobs,
            job_id=job.id,
            attempt_id=attempt_id,
        )
        worker.signals.succeeded.connect(self.show_error_analysis)
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(self, "错误分析失败", message)
        )
        worker.signals.finished.connect(lambda: self.error_button.setEnabled(True))
        self.error_worker = worker
        QThreadPool.globalInstance().start(worker)

    def show_error_analysis(self, result: object) -> None:
        ErrorAnalysisDialog(
            result,
            confirm_callback=lambda reason: self.analysis_factory().confirm(
                result.id,
                error_reason=reason,
            ),
            parent=self,
        ).exec()

    def previous(self) -> None:
        self.save_current_draft()
        if self.index > 0:
            self.index -= 1
            self.show_question()

    def next(self) -> None:
        self.save_current_draft()
        if self.index < len(self.questions) - 1:
            self.index += 1
            self.show_question()

    def finish(self) -> None:
        self.save_current_draft()
        result = self.service.finish(self.practice.id, 0)
        ResultDialog(self.service, result, self).exec()
        self.completed.emit()
        self.accept()

    def save_current_draft(self) -> None:
        question = self.questions[self.index]
        response = self._response_value()
        self.responses[question.id] = response
        self.service.save_draft(self.practice.id, question.id, response)

    def mark(self) -> None:
        question = self.questions[self.index]
        marked = self.service.toggle_mark(self.practice.id, question.id)
        self.feedback.setText("已标记本题" if marked else "已取消标记")

    def reject(self) -> None:
        self.save_current_draft()
        super().reject()


class PracticePage(QWidget):
    report_requested = Signal()
    def __init__(
        self,
        service: QuestionService,
        *,
        resources: ResourceService | None = None,
        jobs: JobService | None = None,
        extraction_factory: Callable[[], KnowledgeExtractionService] | None = None,
        knowledge_index_factory: Callable[[], KnowledgePointIndex] | None = None,
        question_generation_factory: Callable[
            [], QuestionGenerationService
        ] | None = None,
        grading_factory: Callable[[], SubjectiveGradingService] | None = None,
        analysis_factory: Callable[[], ErrorAnalysisService] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.grading_factory = grading_factory
        self.analysis_factory = analysis_factory
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("练习中心", "管理本地题库并开始可恢复、可判分的练习"))
        actions = QHBoxLayout()
        for text, slot in [
            ("新建题目", self.create), ("编辑题目", self.edit), ("归档题目", self.archive),
            ("JSON/CSV 导入", self.import_questions), ("JSON 导出", self.export_json),
            ("继续未完成", self.resume), ("开始快速练习", self.start),
        ]:
            button = QPushButton(text)
            button.clicked.connect(slot)
            if text == "开始快速练习":
                button.setProperty("primary", True)
            actions.addWidget(button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索题干")
        self.search.textChanged.connect(self.refresh)
        self.kind = QComboBox()
        self.kind.addItems(["全部题型", "单选", "多选", "判断", "填空", "简答"])
        self.kind.currentTextChanged.connect(self.refresh)
        actions.addStretch()
        actions.addWidget(self.search)
        actions.addWidget(self.kind)
        root.addLayout(actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["题干", "题型", "难度", "标准答案"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit)
        self.sessions = QTableWidget(0, 5)
        self.sessions.setHorizontalHeaderLabels(["开始时间", "状态", "题数", "答对", "正确率"])
        self.sessions.horizontalHeader().setStretchLastSection(True)
        self.sessions.doubleClicked.connect(self.show_result)
        knowledge_page = QWidget()
        knowledge_layout = QVBoxLayout(knowledge_page)
        knowledge_bar = QHBoxLayout()
        self.knowledge_course = QComboBox()
        for course in self.service.list_courses():
            self.knowledge_course.addItem(course.name, course.id)
        self.knowledge_name = QLineEdit()
        self.knowledge_name.setPlaceholderText("知识点名称")
        self.knowledge_mastery = QSpinBox()
        self.knowledge_mastery.setRange(0, 100)
        self.knowledge_mastery.setSuffix("%")
        add_knowledge = QPushButton("添加知识点")
        add_knowledge.clicked.connect(self.create_knowledge)
        edit_knowledge = QPushButton("编辑")
        edit_knowledge.clicked.connect(self.edit_knowledge)
        merge_knowledge = QPushButton("合并")
        merge_knowledge.clicked.connect(self.merge_knowledge)
        delete_knowledge = QPushButton("删除")
        delete_knowledge.clicked.connect(self.delete_knowledge)
        knowledge_bar.addWidget(self.knowledge_course)
        knowledge_bar.addWidget(self.knowledge_name, 1)
        knowledge_bar.addWidget(self.knowledge_mastery)
        knowledge_bar.addWidget(add_knowledge)
        knowledge_bar.addWidget(edit_knowledge)
        knowledge_bar.addWidget(merge_knowledge)
        knowledge_bar.addWidget(delete_knowledge)
        self.knowledge_table = QTableWidget(0, 3)
        self.knowledge_table.setHorizontalHeaderLabels(["课程", "知识点", "掌握度"])
        self.knowledge_table.horizontalHeader().setStretchLastSection(True)
        knowledge_layout.addLayout(knowledge_bar)
        knowledge_layout.addWidget(self.knowledge_table)
        self.knowledge_extraction_widget = None
        if resources and jobs and extraction_factory and knowledge_index_factory:
            self.knowledge_extraction_widget = KnowledgeExtractionWidget(
                resources=resources,
                jobs=jobs,
                draft_service=KnowledgeDraftService(
                    service.database,
                    knowledge_index_factory=knowledge_index_factory,
                ),
                extraction_factory=extraction_factory,
                index_factory=knowledge_index_factory,
            )
            self.knowledge_extraction_widget.knowledge_changed.connect(self.refresh)
            self.knowledge_extraction_widget.knowledge_accepted.connect(
                self.open_question_generator_for_knowledge
            )
            knowledge_layout.addWidget(self.knowledge_extraction_widget, 1)
        tabs = QTabWidget()
        tabs.addTab(self.table, "题库管理")
        tabs.addTab(self.sessions, "练习记录")
        tabs.addTab(knowledge_page, "知识点")
        self.question_generation_widget = None
        if resources and jobs and question_generation_factory:
            self.question_generation_widget = QuestionGenerationWidget(
                resources=resources,
                jobs=jobs,
                draft_service=QuestionDraftService(service.database),
                generation_factory=question_generation_factory,
            )
            self.question_generation_widget.questions_changed.connect(self.refresh)
            self.question_generation_widget.practice_requested.connect(
                self.start_practice_for_question
            )
            tabs.addTab(self.question_generation_widget, "AI 出题")
        self.tabs = tabs
        root.addWidget(tabs)
        self.refresh()

    def refresh(self) -> None:
        kind = "" if self.kind.currentText() == "全部题型" else self.kind.currentText()
        items = self.service.list_questions(self.search.text(), kind)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            prompt = QTableWidgetItem(item.prompt)
            prompt.setData(Qt.UserRole, item.id)
            for column, value in enumerate((prompt, QTableWidgetItem(item.kind), QTableWidgetItem(str(item.difficulty)), QTableWidgetItem(item.answer))):
                self.table.setItem(row, column, value)
        sessions = self.service.list_sessions()
        self.sessions.setRowCount(len(sessions))
        for row, item in enumerate(sessions):
            started = QTableWidgetItem(item.started_at.strftime("%Y-%m-%d %H:%M"))
            started.setData(Qt.UserRole, item.id)
            accuracy = f"{item.correct * 100 / item.total:.1f}%" if item.total and item.status == "completed" else "-"
            for column, value in enumerate((
                started, QTableWidgetItem(item.status), QTableWidgetItem(str(item.total)),
                QTableWidgetItem(str(item.correct)), QTableWidgetItem(accuracy)
            )):
                self.sessions.setItem(row, column, value)
        courses = {course.id: course.name for course in self.service.list_courses()}
        knowledge = self.service.list_knowledge()
        self.knowledge_table.setRowCount(len(knowledge))
        for row, item in enumerate(knowledge):
            for column, text in enumerate((
                courses.get(item.course_id, "未知课程"), item.name, f"{item.mastery}%"
            )):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.UserRole, item.id)
                self.knowledge_table.setItem(row, column, cell)
        if self.knowledge_extraction_widget is not None:
            self.knowledge_extraction_widget.refresh_scopes()
        if self.question_generation_widget is not None:
            self.question_generation_widget.refresh_scopes()

    def show_pending_knowledge_drafts(self, course_id: int) -> None:
        if self.knowledge_extraction_widget is None:
            return
        self.tabs.setCurrentIndex(2)
        self.knowledge_extraction_widget.show_pending_for_course(course_id)

    def open_question_generator_for_knowledge(
        self, course_id: int, _point_id: int, knowledge_name: str
    ) -> None:
        if self.question_generation_widget is None:
            return
        self.tabs.setCurrentWidget(self.question_generation_widget)
        self.question_generation_widget.prefill_for_knowledge(course_id, knowledge_name)

    def start_practice_for_question(self, question_id: int) -> None:
        self.start_practice_for_questions([question_id])

    def start_practice_for_questions(self, question_ids: list[int] | tuple[int, ...]) -> bool:
        try:
            prepared = self.service.create_practice_for_questions(list(question_ids))
        except ValueError as exc:
            QMessageBox.warning(self, "无法开始练习", str(exc))
            return False
        dialog = PracticeDialog(
            self.service,
            self,
            prepared,
            jobs=self.jobs,
            grading_factory=self.grading_factory,
            analysis_factory=self.analysis_factory,
        )
        completed = [False]
        dialog.completed.connect(lambda: completed.__setitem__(0, True))
        dialog.completed.connect(self.report_requested.emit)
        dialog.exec()
        self.refresh()
        return completed[0]

    def create(self) -> None:
        dialog = QuestionDialog(self.service, self)
        if dialog.exec():
            try:
                self.service.save_question(
                    dialog.prompt.toPlainText(), dialog.answer.toPlainText(),
                    dialog.kind.currentText(), dialog.difficulty.value(),
                    course_id=dialog.course.currentData(),
                    options=dialog.options.toPlainText(),
                    explanation=dialog.explanation.toPlainText(), tags=dialog.tags.text(),
                    knowledge_point_id=dialog.knowledge.currentData()
                )
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "保存失败", str(error))

    def archive(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is not None and QMessageBox.question(self, "归档题目", "确认归档选中题目？") == QMessageBox.Yes:
            self.service.archive(item_id)
            self.refresh()

    def edit(self, _index: object | None = None) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        question = self.service.get_question(item_id)
        if not question:
            return
        dialog = QuestionDialog(self.service, self, question)
        if dialog.exec():
            try:
                self.service.save_question(
                    dialog.prompt.toPlainText(), dialog.answer.toPlainText(),
                    dialog.kind.currentText(), dialog.difficulty.value(), question_id=item_id,
                    course_id=dialog.course.currentData(),
                    options=dialog.options.toPlainText(), explanation=dialog.explanation.toPlainText(),
                    tags=dialog.tags.text(), knowledge_point_id=dialog.knowledge.currentData()
                )
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "保存失败", str(error))

    def import_questions(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "导入题库", filter="题库文件 (*.json *.csv)")
        if filename:
            try:
                path = Path(filename)
                count, errors = self.service.import_csv(path) if path.suffix.lower() == ".csv" else self.service.import_json(path)
                self.refresh()
                QMessageBox.information(self, "导入完成", f"成功 {count} 条，失败 {len(errors)} 条。")
            except (OSError, ValueError, json.JSONDecodeError) as error:
                QMessageBox.warning(self, "导入失败", str(error))

    def export_json(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "导出题库", "questions.json", "JSON (*.json)")
        if filename:
            count = self.service.export_json(Path(filename))
            QMessageBox.information(self, "导出完成", f"已导出 {count} 道题。")

    def start(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("练习配置")
        form = QFormLayout(dialog)
        course = QComboBox()
        course.addItem("全部课程", None)
        for item in self.service.list_courses():
            course.addItem(item.name, item.id)
        kind = QComboBox()
        kind.addItems(["全部题型", "单选", "多选", "判断", "填空", "简答"])
        difficulty = QComboBox()
        difficulty.addItem("全部难度", None)
        for value in range(1, 6):
            difficulty.addItem(str(value), value)
        count = QSpinBox()
        count.setRange(1, 200)
        count.setValue(10)
        seed = QSpinBox()
        seed.setRange(0, 2_147_483_647)
        seed.setSpecialValueText("随机")
        feedback = QComboBox()
        feedback.addItems(["即时显示答案", "提交后显示答案"])
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("课程", course)
        form.addRow("题型", kind)
        form.addRow("难度", difficulty)
        form.addRow("题目数量", count)
        form.addRow("随机种子", seed)
        form.addRow("答案显示", feedback)
        form.addRow(buttons)
        if not dialog.exec():
            return
        try:
            kinds = None if kind.currentText() == "全部题型" else [kind.currentText()]
            prepared = self.service.create_practice(
                count.value(), course.currentData(), kinds, difficulty.currentData(),
                seed.value() or None
            )
            PracticeDialog(
                self.service, self, prepared, feedback.currentText() == "即时显示答案"
                , jobs=self.jobs, grading_factory=self.grading_factory,
                analysis_factory=self.analysis_factory
            ).exec()
            self.refresh()
        except ValueError as error:
            QMessageBox.information(self, "无法开始", str(error))

    def resume(self) -> None:
        resumed = self.service.resume_latest()
        if not resumed:
            QMessageBox.information(self, "继续练习", "没有未完成的练习。")
            return
        PracticeDialog(
            self.service, self, resumed,
            jobs=self.jobs, grading_factory=self.grading_factory
            , analysis_factory=self.analysis_factory
        ).exec()
        self.refresh()

    def show_result(self, _index: object | None = None) -> None:
        session_id = _selected_id(self.sessions)
        if session_id is None:
            return
        sessions = {item.id: item for item in self.service.list_sessions()}
        item = sessions.get(session_id)
        if item:
            ResultDialog(self.service, item, self).exec()

    def create_knowledge(self) -> None:
        course_id = self.knowledge_course.currentData()
        if course_id is None:
            QMessageBox.information(self, "知识点", "请先创建并选择课程。")
            return
        try:
            self.service.save_knowledge(
                course_id, self.knowledge_name.text(), self.knowledge_mastery.value()
            )
            self.knowledge_name.clear()
            self.refresh()
        except ValueError as error:
            QMessageBox.warning(self, "无法保存", str(error))


    def _selected_knowledge(self):
        row = self.knowledge_table.currentRow()
        item = self.knowledge_table.item(row, 1) if row >= 0 else None
        knowledge_id = item.data(Qt.UserRole) if item is not None else None
        return next((point for point in self.service.list_knowledge() if point.id == knowledge_id), None)

    def edit_knowledge(self) -> None:
        point = self._selected_knowledge()
        if point is None:
            QMessageBox.information(self, "知识点", "请先选择一个知识点。")
            return
        name, accepted = QInputDialog.getText(self, "编辑知识点", "名称", text=point.name)
        if not accepted or not name.strip():
            return
        mastery, accepted = QInputDialog.getInt(
            self, "编辑掌握度", "掌握度", point.mastery, 0, 100
        )
        if not accepted:
            return
        self.service.save_knowledge(point.course_id, name, mastery, point.note, point.id)
        self.refresh()

    def delete_knowledge(self) -> None:
        point = self._selected_knowledge()
        if point is None:
            QMessageBox.information(self, "知识点", "请先选择一个知识点。")
            return
        if QMessageBox.question(
            self, "删除知识点", "删除后关联题目将变为未关联，是否继续？"
        ) != QMessageBox.Yes:
            return
        self.service.delete_knowledge(point.id)
        self.refresh()

    def merge_knowledge(self) -> None:
        source = self._selected_knowledge()
        if source is None:
            QMessageBox.information(self, "合并知识点", "请先选择要合并的知识点。")
            return
        candidates = [
            point for point in self.service.list_knowledge(source.course_id)
            if point.id != source.id
        ]
        if not candidates:
            QMessageBox.information(self, "合并知识点", "该课程没有可合并的目标知识点。")
            return
        names = [point.name for point in candidates]
        target_name, accepted = QInputDialog.getItem(
            self, "合并知识点", "合并到", names, 0, False
        )
        if not accepted:
            return
        target = next(point for point in candidates if point.name == target_name)
        if QMessageBox.question(
            self, "确认合并", f"“{source.name}”的关联题目将迁移到“{target.name}”。"
        ) != QMessageBox.Yes:
            return
        self.service.merge_knowledge(source.id, target.id)
        self.refresh()


class ResultDialog(QDialog):
    def __init__(self, service: QuestionService, practice: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("练习结果")
        self.resize(850, 520)
        # Repair sessions created before objective auto-grading was added.
        # finish() is idempotent and only fills missing objective results.
        practice = service.finish(practice.id, practice.duration_seconds)
        root = QVBoxLayout(self)
        accuracy = practice.correct * 100 / practice.total if practice.total else 0
        heading = QLabel(f"得分：{practice.correct} / {practice.total}    正确率：{accuracy:.1f}%")
        heading.setProperty("title", True)
        root.addWidget(heading)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["题目", "你的答案", "标准答案", "结果", "解析"])
        table.horizontalHeader().setStretchLastSection(True)
        rows = service.session_results(practice.id)
        table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            result = "正确" if item["correct"] is True else ("错误" if item["correct"] is False else "未判分")
            for column, text in enumerate((
                item["prompt"], item["response"], item["answer"], result, item["explanation"]
            )):
                table.setItem(row, column, QTableWidgetItem(str(text)))
        root.addWidget(table)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)




