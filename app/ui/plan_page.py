from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.learning import LearningService
from app.services.domain import JobService
from ai.chains import PlanGenerationService
from app.ui.ai_plan_widget import AIPlanWidget
from collections.abc import Callable


from app.ui.components import page_title, stat_card

class PlanPage(QWidget):
    def __init__(self, service: LearningService, *, jobs: JobService | None = None, plan_factory: Callable[[], PlanGenerationService] | None = None) -> None:
        super().__init__()
        self.service = service
        self.ai_plan_widget = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("学习计划", "安排今日任务并保持可执行的学习节奏"))
        add = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("输入任务名称")
        self.duration = QSpinBox()
        self.duration.setRange(5, 480)
        self.duration.setValue(30)
        self.duration.setSuffix(" 分钟")
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDate(date.today())
        self.day.dateChanged.connect(self.refresh)
        self.priority = QComboBox()
        self.priority.addItems(["高", "中", "低"])
        self.course = QComboBox()
        self.course.addItem("未关联课程", None)
        for course in self.service.list_courses():
            self.course.addItem(course.name, course.id)
        button = QPushButton("添加今日任务")
        button.setProperty("primary", True)
        button.clicked.connect(self.create)
        add.addWidget(self.title, 1)
        add.addWidget(self.duration)
        add.addWidget(self.day)
        add.addWidget(self.priority)
        add.addWidget(self.course)
        add.addWidget(button)
        distribute = QPushButton("平均分配任务")
        distribute.clicked.connect(self.distribute)
        add.addWidget(distribute)
        recurring = QPushButton("重复任务")
        recurring.clicked.connect(self.recurring)
        add.addWidget(recurring)
        root.addLayout(add)
        tabs = QTabWidget()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["任务", "日期", "时长", "优先级", "状态", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.table, "今日")
        self.week_table = QTableWidget(0, 4)
        self.week_table.setHorizontalHeaderLabels(["日期", "任务", "时长", "状态"])
        self.week_table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.week_table, "本周")
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_filters = QHBoxLayout()
        self.list_search = QLineEdit()
        self.list_search.setPlaceholderText("搜索任务")
        self.list_search.textChanged.connect(self.refresh)
        self.list_priority = QComboBox()
        self.list_priority.addItems(["全部优先级", "高", "中", "低"])
        self.list_priority.currentTextChanged.connect(self.refresh)
        self.list_status = QComboBox()
        self.list_status.addItems(["全部状态", "待完成", "已完成"])
        self.list_status.currentTextChanged.connect(self.refresh)
        list_filters.addWidget(self.list_search, 1)
        list_filters.addWidget(self.list_priority)
        list_filters.addWidget(self.list_status)
        self.list_table = QTableWidget(0, 5)
        self.list_table.setHorizontalHeaderLabels(["日期", "任务", "课程", "优先级", "状态"])
        self.list_table.horizontalHeader().setStretchLastSection(True)
        list_layout.addLayout(list_filters)
        list_layout.addWidget(self.list_table)
        tabs.addTab(list_page, "列表")
        goals = QWidget()
        goals_layout = QVBoxLayout(goals)
        goal_bar = QHBoxLayout()
        self.goal_title = QLineEdit()
        self.goal_title.setPlaceholderText("目标名称")
        self.goal_date = QDateEdit()
        self.goal_date.setCalendarPopup(True)
        self.goal_date.setDate(date.today())
        self.goal_weekly = QSpinBox()
        self.goal_weekly.setRange(30, 10080)
        self.goal_weekly.setValue(420)
        self.goal_weekly.setSuffix(" 分钟/周")
        goal_button = QPushButton("新建目标")
        goal_button.clicked.connect(self.create_goal)
        goal_bar.addWidget(self.goal_title, 1)
        goal_bar.addWidget(self.goal_date)
        goal_bar.addWidget(self.goal_weekly)
        goal_bar.addWidget(goal_button)
        self.goals_table = QTableWidget(0, 5)
        self.goals_table.setHorizontalHeaderLabels(["目标", "截止日期", "每周时间", "进度", "操作"])
        self.goals_table.horizontalHeader().setStretchLastSection(True)
        goals_layout.addLayout(goal_bar)
        goals_layout.addWidget(self.goals_table)
        tabs.addTab(goals, "学习目标")
        if jobs is not None and plan_factory is not None:
            self.ai_plan_widget = AIPlanWidget(learning=service, jobs=jobs, factory=plan_factory)
            self.ai_plan_widget.tasks_changed.connect(self.refresh)
            tabs.addTab(self.ai_plan_widget, "AI 学习计划")
        root.addWidget(tabs)
        self.refresh()

    def create(self) -> None:
        try:
            self.service.create_task(
                self.title.text(), self.duration.value(), self.priority.currentText(),
                self.day.date().toPython(), course_id=self.course.currentData()
            )
            self.title.clear()
            self.refresh()
        except ValueError as error:
            QMessageBox.warning(self, "无法添加", str(error))

    def refresh(self) -> None:
        selected_day = self.day.date().toPython()
        tasks = self.service.list_tasks(selected_day, selected_day)
        self.table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            for col, text in enumerate((
                task.title, task.planned_date.isoformat(), f"{task.duration_minutes} 分钟",
                task.priority, "已完成" if task.completed else "待完成"
            )):
                self.table.setItem(row, col, QTableWidgetItem(text))
            operations = QWidget()
            buttons = QHBoxLayout(operations)
            buttons.setContentsMargins(0, 0, 0, 0)
            complete = QPushButton("完成")
            complete.setEnabled(not task.completed)
            complete.clicked.connect(lambda _=False, item_id=task.id: self.complete(item_id))
            delete = QPushButton("删除")
            delete.clicked.connect(lambda _=False, item_id=task.id: self.delete(item_id))
            edit = QPushButton("编辑")
            edit.clicked.connect(lambda _=False, item_id=task.id: self.edit_task(item_id))
            buttons.addWidget(edit)
            buttons.addWidget(complete)
            buttons.addWidget(delete)
            self.table.setCellWidget(row, 5, operations)
        monday = date.today() - timedelta(days=date.today().weekday())
        weekly = self.service.list_tasks(monday, monday + timedelta(days=6))
        self.week_table.setRowCount(len(weekly))
        for row, task in enumerate(weekly):
            for col, text in enumerate((
                task.planned_date.strftime("%m-%d"), task.title,
                f"{task.duration_minutes} 分钟", "已完成" if task.completed else "待完成"
            )):
                self.week_table.setItem(row, col, QTableWidgetItem(text))
        all_tasks = self.service.list_tasks(
            date.today() - timedelta(days=365), date.today() + timedelta(days=3650)
        )
        query = self.list_search.text().strip().casefold()
        priority_filter = self.list_priority.currentText()
        status_filter = self.list_status.currentText()
        filtered = [
            task for task in all_tasks
            if (not query or query in task.title.casefold())
            and (priority_filter == "全部优先级" or task.priority == priority_filter)
            and (status_filter == "全部状态"
                 or (status_filter == "已完成" and task.completed)
                 or (status_filter == "待完成" and not task.completed))
        ]
        course_names = {course.id: course.name for course in self.service.list_courses()}
        self.list_table.setRowCount(len(filtered))
        for row, task in enumerate(filtered):
            for col, text in enumerate((
                task.planned_date.isoformat(), task.title,
                course_names.get(task.course_id, "未关联"), task.priority,
                "已完成" if task.completed else "待完成",
            )):
                self.list_table.setItem(row, col, QTableWidgetItem(text))
        goals = self.service.list_goals()
        self.goals_table.setRowCount(len(goals))
        for row, goal in enumerate(goals):
            for col, text in enumerate((
                goal.title, goal.target_date.isoformat(), f"{goal.weekly_minutes} 分钟", f"{goal.progress}%"
            )):
                self.goals_table.setItem(row, col, QTableWidgetItem(text))
            operations = QWidget()
            layout = QHBoxLayout(operations)
            layout.setContentsMargins(0, 0, 0, 0)
            edit = QPushButton("编辑")
            edit.clicked.connect(lambda _=False, item_id=goal.id: self.edit_goal(item_id))
            archive = QPushButton("归档")
            archive.clicked.connect(lambda _=False, item_id=goal.id: self.archive_goal(item_id))
            layout.addWidget(edit)
            layout.addWidget(archive)
            self.goals_table.setCellWidget(row, 4, operations)

    def complete(self, task_id: int) -> None:
        self.service.complete_task(task_id)
        self.refresh()

    def delete(self, task_id: int) -> None:
        if QMessageBox.question(self, "删除任务", "确认删除这个任务？") == QMessageBox.Yes:
            self.service.delete_task(task_id)
            self.refresh()

    def edit_task(self, task_id: int) -> None:
        task = self.service.get_task(task_id)
        if not task:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑任务")
        form = QFormLayout(dialog)
        title = QLineEdit(task.title)
        day = QDateEdit()
        day.setCalendarPopup(True)
        day.setDate(task.planned_date)
        duration = QSpinBox()
        duration.setRange(5, 480)
        duration.setValue(task.duration_minutes)
        priority = QComboBox()
        priority.addItems(["高", "中", "低"])
        priority.setCurrentText(task.priority)
        course = QComboBox()
        course.addItem("未关联课程", None)
        for item in self.service.list_courses():
            course.addItem(item.name, item.id)
        course.setCurrentIndex(max(0, course.findData(task.course_id)))
        note = QTextEdit(task.note)
        note.setMaximumHeight(100)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("任务", title)
        form.addRow("日期", day)
        form.addRow("时长", duration)
        form.addRow("优先级", priority)
        form.addRow("课程", course)
        form.addRow("备注", note)
        form.addRow(buttons)
        if dialog.exec():
            try:
                self.service.update_task(
                    task_id, title.text(), duration.value(), priority.currentText(),
                    day.date().toPython(), note=note.toPlainText(), course_id=course.currentData()
                )
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "无法保存", str(error))

    def create_goal(self) -> None:
        try:
            self.service.create_goal(
                self.goal_title.text(), self.goal_date.date().toPython(), self.goal_weekly.value()
            )
            self.goal_title.clear()
            self.refresh()
        except ValueError as error:
            QMessageBox.warning(self, "无法创建目标", str(error))

    def edit_goal(self, goal_id: int) -> None:
        goal = self.service.get_goal(goal_id)
        if not goal:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑学习目标")
        form = QFormLayout(dialog)
        title = QLineEdit(goal.title)
        target = QDateEdit()
        target.setCalendarPopup(True)
        target.setDate(goal.target_date)
        weekly = QSpinBox()
        weekly.setRange(30, 10080)
        weekly.setValue(goal.weekly_minutes)
        progress = QSpinBox()
        progress.setRange(0, 100)
        progress.setValue(goal.progress)
        progress.setSuffix("%")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("目标", title)
        form.addRow("截止日期", target)
        form.addRow("每周分钟", weekly)
        form.addRow("进度", progress)
        form.addRow(buttons)
        if dialog.exec():
            self.service.update_study_goal(
                goal_id, title.text(), target.date().toPython(), weekly.value(), progress.value()
            )
            self.refresh()

    def archive_goal(self, goal_id: int) -> None:
        if QMessageBox.question(self, "归档目标", "确认归档这个学习目标？") == QMessageBox.Yes:
            self.service.archive_goal(goal_id)
            self.refresh()

    def distribute(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("平均分配任务")
        form = QFormLayout(dialog)
        prefix = QLineEdit()
        prefix.setPlaceholderText("例如：高数章节练习")
        start = QDateEdit()
        start.setCalendarPopup(True)
        start.setDate(date.today())
        end = QDateEdit()
        end.setCalendarPopup(True)
        end.setDate(date.today() + timedelta(days=6))
        count = QSpinBox()
        count.setRange(1, 1000)
        count.setValue(10)
        duration = QSpinBox()
        duration.setRange(5, 480)
        duration.setValue(30)
        duration.setSuffix(" 分钟/项")
        daily = QSpinBox()
        daily.setRange(5, 1440)
        daily.setValue(120)
        daily.setSuffix(" 分钟/天")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("任务名称", prefix)
        form.addRow("开始日期", start)
        form.addRow("结束日期", end)
        form.addRow("任务数量", count)
        form.addRow("单项时长", duration)
        form.addRow("每日上限", daily)
        form.addRow(buttons)
        if not dialog.exec():
            return
        try:
            schedule = self.service.distribute_schedule(
                start.date().toPython(), end.date().toPython(), count.value(),
                duration.value(), daily.value()
            )
            per_day: dict[date, int] = {}
            for day in schedule:
                per_day[day] = per_day.get(day, 0) + 1
            preview = "\n".join(f"{day.isoformat()}：{items} 项 / {items * duration.value()} 分钟" for day, items in per_day.items())
            if QMessageBox.question(
                self, "确认任务草稿", f"{preview}\n\n确认后将创建 {len(schedule)} 个任务。"
            ) == QMessageBox.Yes:
                self.service.create_distributed_tasks(
                    prefix.text() or "学习任务", start.date().toPython(), end.date().toPython(),
                    count.value(), duration.value(), daily.value()
                )
                self.refresh()
        except ValueError as error:
            QMessageBox.warning(self, "无法分配", str(error))

    def recurring(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("创建重复任务")
        form = QFormLayout(dialog)
        title = QLineEdit()
        day = QDateEdit()
        day.setCalendarPopup(True)
        day.setDate(date.today())
        frequency = QComboBox()
        frequency.addItem("每天", "daily")
        frequency.addItem("每周", "weekly")
        occurrences = QSpinBox()
        occurrences.setRange(1, 365)
        occurrences.setValue(7)
        duration = QSpinBox()
        duration.setRange(5, 480)
        duration.setValue(30)
        duration.setSuffix(" 分钟")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("任务名称", title)
        form.addRow("开始日期", day)
        form.addRow("频率", frequency)
        form.addRow("次数", occurrences)
        form.addRow("单次时长", duration)
        form.addRow(buttons)
        if dialog.exec():
            try:
                created = self.service.create_recurring_tasks(
                    title.text(), day.date().toPython(), frequency.currentData(),
                    occurrences.value(), duration.value()
                )
                self.refresh()
                QMessageBox.information(self, "重复任务", f"创建了 {len(created)} 个任务；已存在的日期不会重复。")
            except ValueError as error:
                QMessageBox.warning(self, "无法创建", str(error))


