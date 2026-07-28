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


class AnalyticsPage(QWidget):
    def __init__(self, service: AnalyticsService) -> None:
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("学习分析", "统计仅来自本地真实任务、练习和学习记录"))
        bar = QHBoxLayout()
        self.range = QComboBox()
        self.range.addItems(["最近 7 天", "最近 30 天", "最近 90 天"])
        self.range.currentTextChanged.connect(self.refresh)
        self.course = QComboBox()
        self.course.addItem("全部课程", None)
        for item in self.service.list_courses():
            self.course.addItem(item.name, item.id)
        self.course.currentIndexChanged.connect(self.refresh)
        export = QPushButton("导出 CSV")
        export.clicked.connect(self.export)
        export_image = QPushButton("导出当前图表")
        export_image.clicked.connect(self.export_image)
        bar.addWidget(self.range)
        bar.addWidget(self.course)
        bar.addWidget(export)
        bar.addWidget(export_image)
        bar.addStretch()
        root.addLayout(bar)
        self.cards = QHBoxLayout()
        root.addLayout(self.cards)
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.task_chart = QChartView()
        self.task_chart.setRenderHint(QPainter.Antialiasing)
        self.course_chart = QChartView()
        self.course_chart.setRenderHint(QPainter.Antialiasing)
        self.knowledge = QTableWidget(0, 2)
        self.knowledge.setHorizontalHeaderLabels(["知识点", "掌握度"])
        self.knowledge.horizontalHeader().setStretchLastSection(True)
        self.error_chart = QChartView()
        self.accuracy_chart = QChartView()
        tabs = QTabWidget()
        tabs.addTab(self.chart_view, "学习时长")
        tabs.addTab(self.task_chart, "任务完成")
        tabs.addTab(self.course_chart, "课程分布")
        tabs.addTab(self.knowledge, "知识点掌握")
        tabs.addTab(self.error_chart, "错误类型")
        tabs.addTab(self.accuracy_chart, "正确率趋势")
        root.addWidget(tabs, 1)
        self.refresh()

    def _dates(self) -> tuple[date, date]:
        days = {"最近 7 天": 7, "最近 30 天": 30, "最近 90 天": 90}[self.range.currentText()]
        return date.today() - timedelta(days=days - 1), date.today()

    def refresh(self) -> None:
        start, end = self._dates()
        data = self.service.summary(start, end, self.course.currentData())
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        values = [
            ("学习时长", f"{data['study_minutes']} 分钟", "专注记录"),
            ("任务完成", f"{data['tasks_done']}/{data['tasks_total']}", "计划执行"),
            ("练习题数", str(data["practice_questions"]), "本地题库"),
            ("正确率", f"{data['accuracy']}%", "客观题与自评"),
        ]
        for value in values:
            self.cards.addWidget(stat_card(*value))
        bar_set = QBarSet("学习分钟")
        categories = []
        points = list(data["daily"].items())
        if len(points) > 31:
            points = points[::7]
        for day, minutes in points:
            bar_set.append(minutes)
            categories.append(day.strftime("%m-%d"))
        series = QBarSeries()
        series.append(bar_set)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("每日学习时长")
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setTitleText("分钟")
        axis_y.setRange(0, max([int(v) for _, v in points] + [60]))
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        self.chart_view.setChart(chart)
        self.task_chart.setChart(self._bar_chart(
            "每周任务完成", list(data["weekly_tasks"].keys()),
            [done for _, done in data["weekly_tasks"].values()], "完成任务"
        ))
        self.course_chart.setChart(self._bar_chart(
            "各课程学习时间", list(data["course_minutes"].keys()),
            list(data["course_minutes"].values()), "分钟"
        ))
        knowledge = data["knowledge"]
        self.knowledge.setRowCount(len(knowledge))
        for row, item in enumerate(knowledge):
            self.knowledge.setItem(row, 0, QTableWidgetItem(item["name"]))
            self.knowledge.setItem(row, 1, QTableWidgetItem(f"{item['mastery']}%"))
        self.error_chart.setChart(self._bar_chart(
            "错误类型分布", list(data["error_types"].keys()),
            list(data["error_types"].values()), "错误次数"
        ))
        accuracy_series = QLineSeries()
        for day, accuracy in data["accuracy_daily"].items():
            accuracy_series.append(
                QDateTime(day.year, day.month, day.day, 0, 0, 0).toMSecsSinceEpoch(), accuracy
            )
        accuracy_chart = QChart()
        accuracy_chart.addSeries(accuracy_series)
        accuracy_chart.setTitle("正确率趋势")
        accuracy_x = QDateTimeAxis()
        accuracy_x.setFormat("MM-dd")
        accuracy_y = QValueAxis()
        accuracy_y.setRange(0, 100)
        accuracy_y.setTitleText("%")
        accuracy_chart.addAxis(accuracy_x, Qt.AlignBottom)
        accuracy_chart.addAxis(accuracy_y, Qt.AlignLeft)
        accuracy_series.attachAxis(accuracy_x)
        accuracy_series.attachAxis(accuracy_y)
        self.accuracy_chart.setChart(accuracy_chart)

    @staticmethod
    def _bar_chart(title: str, categories: list[str], values: list[int], series_name: str) -> QChart:
        bar_set = QBarSet(series_name)
        bar_set.append(values or [0])
        series = QBarSeries()
        series.append(bar_set)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle(title)
        axis_x = QBarCategoryAxis()
        axis_x.append(categories or ["暂无数据"])
        axis_y = QValueAxis()
        axis_y.setRange(0, max(values + [1]))
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        return chart

    def export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "导出分析", "analytics.csv", "CSV (*.csv)")
        if filename:
            self.service.export_csv(Path(filename), *self._dates(), self.course.currentData())

    def export_image(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "导出图表", "analytics.png", "PNG (*.png)")
        if filename:
            if not self.chart_view.grab().save(filename, "PNG"):
                QMessageBox.warning(self, "导出失败", "无法保存当前图表。")


