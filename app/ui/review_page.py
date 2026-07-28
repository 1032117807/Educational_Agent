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


class ReviewPage(QWidget):
    def __init__(self, service: ReviewService) -> None:
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("错题与复习", "依据 1、3、7、14、30 天规则安排间隔复习"))
        bar = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(["今日到期", "全部错题"])
        self.scope.currentTextChanged.connect(self.refresh)
        bar.addWidget(self.scope)
        for text, result in [("答对", "correct"), ("答错", "wrong"), ("推迟一天", "postpone"), ("标记掌握", "mastered")]:
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, value=result: self.review(value))
            bar.addWidget(button)
        bar.addStretch()
        root.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["错题", "错误次数", "连续答对", "状态", "下次复习"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.details)
        root.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        items = self.service.list_items(self.scope.currentText() == "今日到期")
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            title = QTableWidgetItem(item.title)
            title.setData(Qt.UserRole, item.id)
            for column, value in enumerate((title, QTableWidgetItem(str(item.wrong_count)), QTableWidgetItem(str(item.streak)),
                                            QTableWidgetItem(item.status), QTableWidgetItem(item.next_review.isoformat()))):
                self.table.setItem(row, column, value)

    def review(self, result: str) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            QMessageBox.information(self, "请选择错题", "请先选择一条复习记录。")
            return
        self.service.review(item_id, result)
        self.refresh()

    def details(self, _index: object | None = None) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        items = {item.id: item for item in self.service.list_items()}
        item = items.get(item_id)
        if not item:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("错题详情")
        dialog.resize(650, 480)
        root = QVBoxLayout(dialog)
        title = QLabel(item.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        reason = QLineEdit(item.error_reason)
        reason.setPlaceholderText("例如：概念混淆、计算失误、审题错误")
        note = QTextEdit(item.note)
        history = QTableWidget(0, 3)
        history.setHorizontalHeaderLabels(["时间", "结果", "下次复习"])
        history.horizontalHeader().setStretchLastSection(True)
        rows = self.service.history(item_id)
        history.setRowCount(len(rows))
        for row, attempt in enumerate(rows):
            for column, text in enumerate((
                attempt.created_at.strftime("%Y-%m-%d %H:%M"), attempt.result,
                attempt.next_review.isoformat()
            )):
                history.setItem(row, column, QTableWidgetItem(text))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(title)
        root.addWidget(QLabel("错误原因"))
        root.addWidget(reason)
        root.addWidget(QLabel("笔记"))
        root.addWidget(note)
        root.addWidget(QLabel("复习历史"))
        root.addWidget(history)
        root.addWidget(buttons)
        if dialog.exec():
            self.service.update_notes(item_id, reason.text(), note.toPlainText())


