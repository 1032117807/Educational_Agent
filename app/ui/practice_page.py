from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QDateTimeAxis,
    QLineSeries, QValueAxis,
)
from PySide6.QtCore import QDateTime, QObject, QRunnable, QThreadPool, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.services.domain import (
    AnalyticsService, JobService, MaintenanceService, QuestionService, ResourceService, ReviewService,
)
from app.tools.registry import ToolRegistry
from app.ui.pages import page_title, stat_card
from app.ui.icons import IconProvider


def _selected_id(table: QTableWidget) -> int | None:
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, 0)
    return int(item.data(Qt.UserRole)) if item else None


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


class PracticeDialog(QDialog):
    def __init__(
        self, service: QuestionService, parent: QWidget | None = None,
        resumed: tuple[object, list[object]] | None = None, immediate_feedback: bool = True
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.immediate_feedback = immediate_feedback
        self.setWindowTitle("快速练习")
        self.resize(700, 520)
        self.practice, self.questions = resumed or service.create_practice(10, seed=None)
        self.index = 0
        self.responses: dict[int, str] = service.saved_responses(self.practice.id)
        root = QVBoxLayout(self)
        self.progress = QLabel()
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet("font-size: 18px; font-weight: 600; padding: 16px;")
        self.response = QTextEdit()
        self.response.setPlaceholderText("输入答案；多选答案用英文逗号分隔")
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
        for button in (previous, submit, next_button, mark, finish):
            buttons.addWidget(button)
        root.addWidget(self.progress)
        root.addWidget(self.prompt)
        root.addWidget(self.response)
        root.addWidget(self.feedback)
        root.addLayout(buttons)
        self.show_question()

    def show_question(self) -> None:
        question = self.questions[self.index]
        self.progress.setText(f"第 {self.index + 1} / {len(self.questions)} 题 · {question.kind} · 难度 {question.difficulty}")
        visible_prompt = question.prompt
        if question.options:
            visible_prompt += "\n\n" + question.options
        self.prompt.setText(visible_prompt)
        self.response.setPlainText(self.responses.get(question.id, ""))
        self.feedback.clear()

    def submit(self) -> None:
        question = self.questions[self.index]
        response = self.response.toPlainText()
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
        self.accept()

    def save_current_draft(self) -> None:
        question = self.questions[self.index]
        response = self.response.toPlainText()
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
    def __init__(self, service: QuestionService) -> None:
        super().__init__()
        self.service = service
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
        knowledge_bar.addWidget(self.knowledge_course)
        knowledge_bar.addWidget(self.knowledge_name, 1)
        knowledge_bar.addWidget(self.knowledge_mastery)
        knowledge_bar.addWidget(add_knowledge)
        self.knowledge_table = QTableWidget(0, 3)
        self.knowledge_table.setHorizontalHeaderLabels(["课程", "知识点", "掌握度"])
        self.knowledge_table.horizontalHeader().setStretchLastSection(True)
        knowledge_layout.addLayout(knowledge_bar)
        knowledge_layout.addWidget(self.knowledge_table)
        tabs = QTabWidget()
        tabs.addTab(self.table, "题库管理")
        tabs.addTab(self.sessions, "练习记录")
        tabs.addTab(knowledge_page, "知识点")
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
                self.knowledge_table.setItem(row, column, QTableWidgetItem(text))

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
            ).exec()
            self.refresh()
        except ValueError as error:
            QMessageBox.information(self, "无法开始", str(error))

    def resume(self) -> None:
        resumed = self.service.resume_latest()
        if not resumed:
            QMessageBox.information(self, "继续练习", "没有未完成的练习。")
            return
        PracticeDialog(self.service, self, resumed).exec()
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


class ResultDialog(QDialog):
    def __init__(self, service: QuestionService, practice: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("练习结果")
        self.resize(850, 520)
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


