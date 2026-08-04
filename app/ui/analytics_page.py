from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QDateTimeAxis,
    QLineSeries, QValueAxis,
)
from PySide6.QtCore import QDate, QDateTime, QObject, QRunnable, QThreadPool, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
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
from ai.reports import LearningReport, LearningReportService, render_learning_report


def _selected_id(table: QTableWidget) -> int | None:
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, 0)
    return int(item.data(Qt.UserRole)) if item else None


class LearningReportSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class LearningReportWorker(QRunnable):
    def __init__(
        self,
        *,
        factory: Callable[[], LearningReportService],
        jobs: JobService | None,
        job_id: int | None,
        start_date: date,
        end_date: date,
    ) -> None:
        super().__init__()
        self.factory = factory
        self.jobs = jobs
        self.job_id = job_id
        self.start_date = start_date
        self.end_date = end_date
        self.signals = LearningReportSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if self.jobs is not None and self.job_id is not None:
                self.jobs.update(self.job_id, "running", 20, "正在计算学习统计")
            report = self.factory().generate(
                start_date=self.start_date,
                end_date=self.end_date,
            )
            if self.jobs is not None and self.job_id is not None:
                self.jobs.update(self.job_id, "completed", 100, "AI 学习报告生成完成")
            self.signals.succeeded.emit(report)
        except Exception as exc:
            if self.jobs is not None and self.job_id is not None:
                self.jobs.update(self.job_id, "failed", 100, "AI 学习报告生成失败", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class AnalyticsPage(QWidget):
    jobs_changed = Signal()

    def __init__(
        self,
        service: AnalyticsService,
        *,
        jobs: JobService | None = None,
        report_factory: Callable[[], LearningReportService] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.report_factory = report_factory
        self.report_worker: LearningReportWorker | None = None
        self.current_report_markdown = ""
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
        self.tabs = QTabWidget()
        self.tabs.addTab(self.chart_view, "学习时长")
        self.tabs.addTab(self.task_chart, "任务完成")
        self.tabs.addTab(self.course_chart, "课程分布")
        self.tabs.addTab(self.knowledge, "知识点掌握")
        self.tabs.addTab(self.error_chart, "错误类型")
        self.tabs.addTab(self.accuracy_chart, "正确率趋势")
        if self.report_factory is not None:
            self.report_tab = self._build_report_tab()
            self.tabs.addTab(self.report_tab, "AI 报告")
        root.addWidget(self.tabs, 1)
        self.refresh()

    def _build_report_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        controls = QHBoxLayout()
        self.report_start = QDateEdit()
        self.report_start.setCalendarPopup(True)
        self.report_end = QDateEdit()
        self.report_end.setCalendarPopup(True)
        start, end = self._dates()
        self.report_start.setDate(QDate(start.year, start.month, start.day))
        self.report_end.setDate(QDate(end.year, end.month, end.day))
        self.report_button = QPushButton("生成 AI 报告")
        self.report_button.clicked.connect(self.generate_report)
        self.report_export_button = QPushButton("导出 Markdown")
        self.report_export_button.setEnabled(False)
        self.report_export_button.clicked.connect(self.export_report_markdown)
        controls.addWidget(QLabel("开始"))
        controls.addWidget(self.report_start)
        controls.addWidget(QLabel("结束"))
        controls.addWidget(self.report_end)
        controls.addWidget(self.report_button)
        controls.addWidget(self.report_export_button)
        controls.addStretch()
        self.report_status = QLabel("就绪")
        controls.addWidget(self.report_status)
        root.addLayout(controls)
        self.report_history = QTableWidget(0, 2)
        self.report_history.setHorizontalHeaderLabels(["报告周期", "生成时间"])
        self.report_history.horizontalHeader().setStretchLastSection(True)
        self.report_history.setSelectionBehavior(QTableWidget.SelectRows)
        self.report_history.setEditTriggers(QTableWidget.NoEditTriggers)
        self.report_history.itemSelectionChanged.connect(self.open_selected_report)
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.report_history)
        splitter.addWidget(self.report_text)
        splitter.setSizes([280, 720])
        root.addWidget(splitter, 1)
        self.refresh_report_history()
        return page

    def _dates(self) -> tuple[date, date]:
        days = {"最近 7 天": 7, "最近 30 天": 30, "最近 90 天": 90}[self.range.currentText()]
        return date.today() - timedelta(days=days - 1), date.today()

    def open_today_report(self) -> None:
        if self.report_factory is None:
            return
        self.tabs.setCurrentWidget(self.report_tab)
        today = date.today()
        self.report_start.setDate(QDate(today.year, today.month, today.day))
        self.report_end.setDate(QDate(today.year, today.month, today.day))
        self.report_status.setText("练习已完成，可生成今日 AI 报告")

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

    def generate_report(self) -> None:
        if self.report_factory is None:
            return
        start = self.report_start.date().toPython()
        end = self.report_end.date().toPython()
        if end < start:
            QMessageBox.warning(self, "AI 报告", "结束日期不能早于开始日期。")
            return
        job_id = None
        if self.jobs is not None:
            job_id = self.jobs.create("learning_report", "生成 AI 学习报告").id
            self.jobs_changed.emit()
        self.report_button.setEnabled(False)
        self.report_status.setText("正在生成")
        worker = LearningReportWorker(
            factory=self.report_factory,
            jobs=self.jobs,
            job_id=job_id,
            start_date=start,
            end_date=end,
        )
        worker.signals.succeeded.connect(self.show_report)
        worker.signals.failed.connect(self.show_report_error)
        worker.signals.finished.connect(lambda: self.report_button.setEnabled(True))
        worker.signals.finished.connect(self.jobs_changed.emit)
        self.report_worker = worker
        QThreadPool.globalInstance().start(worker)

    def show_report(self, report: LearningReport) -> None:
        self.current_report_markdown = render_learning_report(report)
        self.report_text.setMarkdown(self.current_report_markdown)
        self.report_export_button.setEnabled(True)
        if self.report_factory is not None:
            try:
                self.report_factory().save_snapshot(report, self.current_report_markdown)
                self.refresh_report_history()
            except Exception as exc:
                QMessageBox.warning(self, "保存 AI 报告失败", str(exc))
        self.report_status.setText("完成")

    def show_report_error(self, message: str) -> None:
        self.report_status.setText("失败")
        QMessageBox.warning(self, "AI 报告失败", message)

    def refresh_report_history(self) -> None:
        if self.report_factory is None:
            return
        reports = self.report_factory().list_snapshots()
        self.report_history.setRowCount(len(reports))
        for row, report in enumerate(reports):
            period = QTableWidgetItem(f"{report.start_date} 至 {report.end_date}")
            period.setData(Qt.UserRole, report.markdown)
            created = QTableWidgetItem(report.created_at.strftime("%Y-%m-%d %H:%M"))
            self.report_history.setItem(row, 0, period)
            self.report_history.setItem(row, 1, created)

    def open_selected_report(self) -> None:
        row = self.report_history.currentRow()
        item = self.report_history.item(row, 0) if row >= 0 else None
        if item is None:
            return
        self.current_report_markdown = item.data(Qt.UserRole)
        self.report_text.setMarkdown(self.current_report_markdown)
        self.report_export_button.setEnabled(True)
        self.report_status.setText("已打开历史报告")

    def export_report_markdown(self) -> None:
        if not self.current_report_markdown:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出 AI 学习报告", "learning-report.md", "Markdown (*.md)"
        )
        if not filename:
            return
        try:
            Path(filename).write_text(self.current_report_markdown, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

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


