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


from app.ui.components import page_title, stat_card

class DashboardPage(QWidget):
    data_changed = Signal()

    def __init__(self, service: LearningService) -> None:
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        head = QHBoxLayout()
        welcome = QVBoxLayout()
        welcome.addWidget(QLabel(f"今天是 {date.today():%Y年%m月%d日}"))
        title = QLabel("继续向目标前进")
        title.setProperty("title", True)
        welcome.addWidget(title)
        head.addLayout(welcome)
        head.addStretch()
        start = QPushButton("开始今日学习")
        start.setProperty("primary", True)
        start.clicked.connect(self.start_study)
        head.addWidget(start)
        root.addLayout(head)
        self.stats = QGridLayout()
        root.addLayout(self.stats)
        root.addWidget(QLabel("今日任务", styleSheet="font-size: 17px; font-weight: 700;"))
        self.tasks = QTableWidget(0, 4)
        self.tasks.setHorizontalHeaderLabels(["任务", "预计时长", "优先级", "操作"])
        self.tasks.horizontalHeader().setStretchLastSection(True)
        self.tasks.setMaximumHeight(240)
        root.addWidget(self.tasks)
        insights = QTabWidget()
        self.recent_courses = QTableWidget(0, 4)
        self.recent_courses.setHorizontalHeaderLabels(["课程", "阶段", "学科", "进度"])
        self.recent_courses.horizontalHeader().setStretchLastSection(True)
        self.weak = QTableWidget(0, 3)
        self.weak.setHorizontalHeaderLabels(["知识点", "掌握度", "建议"])
        self.weak.horizontalHeader().setStretchLastSection(True)
        self.chart = QChartView()
        insights.addTab(self.recent_courses, "最近课程")
        insights.addTab(self.weak, "薄弱知识点")
        insights.addTab(self.chart, "最近 7 天")
        root.addWidget(insights, 1)
        self.refresh()

    def refresh(self) -> None:
        data = self.service.dashboard()
        while self.stats.count():
            item = self.stats.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        stats = data["stats"]
        values = [
            ("今日任务", str(stats["today"]), f"已完成 {stats['done']} 项"),
            ("到期复习", str(stats["due"]), "按计划巩固"),
            ("本周学习", f"{stats['week_minutes'] / 60:.1f} 小时", "来自专注记录"),
            ("连续学习", f"{stats['streak']} 天", "保持节奏"),
        ]
        for column, value in enumerate(values):
            self.stats.addWidget(stat_card(*value), 0, column)
        tasks = data["tasks"]
        self.tasks.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            self.tasks.setItem(row, 0, QTableWidgetItem(task.title))
            self.tasks.setItem(row, 1, QTableWidgetItem(f"{task.duration_minutes} 分钟"))
            self.tasks.setItem(row, 2, QTableWidgetItem(task.priority))
            button = QPushButton("已完成" if task.completed else "完成")
            button.setEnabled(not task.completed)
            button.clicked.connect(lambda _=False, task_id=task.id: self.complete(task_id))
            self.tasks.setCellWidget(row, 3, button)
        courses = data["courses"]
        self.recent_courses.setRowCount(len(courses))
        for row, course in enumerate(courses):
            for column, text in enumerate((
                course.name, course.education_stage, course.subject, f"{course.progress}%"
            )):
                self.recent_courses.setItem(row, column, QTableWidgetItem(text))
        weak = data["weak"]
        self.weak.setRowCount(len(weak))
        for row, item in enumerate(weak):
            suggestion = "优先练习" if item.mastery < 50 else "安排复习"
            for column, text in enumerate((item.name, f"{item.mastery}%", suggestion)):
                self.weak.setItem(row, column, QTableWidgetItem(text))
        series = QLineSeries()
        daily = data["daily"]
        for day, minutes in daily.items():
            moment = QDateTime(day.year, day.month, day.day, 0, 0, 0)
            series.append(moment.toMSecsSinceEpoch(), minutes)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("最近 7 天学习时长")
        axis_x = QDateTimeAxis()
        axis_x.setFormat("MM-dd")
        axis_x.setTitleText("日期")
        axis_y = QValueAxis()
        axis_y.setTitleText("分钟")
        axis_y.setRange(0, max(list(daily.values()) + [60]))
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        self.chart.setChart(chart)

    def complete(self, task_id: int) -> None:
        self.service.complete_task(task_id)
        self.refresh()
        self.data_changed.emit()

    def start_study(self) -> None:
        dialog = StudyTimerDialog(self.service, self)
        if dialog.exec():
            self.refresh()
            self.data_changed.emit()


class StudyTimerDialog(QDialog):
    def __init__(self, service: LearningService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.record = service.start_study_session()
        self.seconds = 0
        self.setWindowTitle("专注学习")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        title = QLabel("专注计时")
        title.setProperty("title", True)
        self.clock = QLabel("00:00:00")
        self.clock.setAlignment(Qt.AlignCenter)
        self.clock.setStyleSheet("font-size: 42px; font-weight: 700; padding: 24px;")
        self.note = QTextEdit()
        self.note.setPlaceholderText("记录本次学习内容或心得（可选）")
        finish = QPushButton("结束并保存")
        finish.setProperty("primary", True)
        finish.clicked.connect(self.finish)
        root.addWidget(title)
        root.addWidget(self.clock)
        root.addWidget(self.note)
        root.addWidget(finish)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self) -> None:
        self.seconds += 1
        hours, rest = divmod(self.seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        self.clock.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def finish(self) -> None:
        self.timer.stop()
        self.service.finish_study_session(
            self.record.id, max(1, round(self.seconds / 60)), self.note.toPlainText()
        )
        self.accept()

    def reject(self) -> None:
        if QMessageBox.question(self, "放弃计时", "退出会保存当前已用时间，确认退出？") == QMessageBox.Yes:
            self.finish()


