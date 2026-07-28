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


class ToolsPage(QWidget):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__()
        self.registry = registry
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("工具中心", "所有本地工具调用都有输入校验、结果和审计 ID"))
        form = QFormLayout()
        self.tool = QComboBox()
        self.tool.addItems([tool.name for tool in registry.list()])
        self.tool.currentTextChanged.connect(self.show_schema)
        self.arguments = QPlainTextEdit('{"path":"."}')
        self.arguments.setMaximumHeight(110)
        run = QPushButton("校验并执行")
        run.setProperty("primary", True)
        run.clicked.connect(self.run_tool)
        form.addRow("工具", self.tool)
        form.addRow("JSON 参数", self.arguments)
        form.addRow(run)
        root.addLayout(form)
        self.schema = QPlainTextEdit()
        self.schema.setReadOnly(True)
        self.schema.setMaximumHeight(150)
        root.addWidget(QLabel("输入 Schema"))
        root.addWidget(self.schema)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(180)
        root.addWidget(self.result)
        root.addWidget(QLabel("最近调用"))
        self.audit = QTableWidget(0, 5)
        self.audit.setHorizontalHeaderLabels(["时间", "工具", "结果", "耗时", "审计 ID"])
        self.audit.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.audit)
        self.show_schema(self.tool.currentText())
        self.refresh_audit()

    def show_schema(self, name: str) -> None:
        definition = self.registry.get(name)
        self.schema.setPlainText(json.dumps({
            "description": definition.description, "risk": definition.risk,
            "mutates_data": definition.mutates_data, "schema": definition.schema(),
        }, ensure_ascii=False, indent=2))

    def run_tool(self) -> None:
        try:
            arguments = json.loads(self.arguments.toPlainText() or "{}")
        except json.JSONDecodeError as error:
            self.result.setPlainText(f"参数不是有效 JSON：{error}")
            return
        name = self.tool.currentText()
        definition = self.registry.get(name)
        confirmed = True
        if definition.mutates_data:
            confirmed = QMessageBox.question(
                self, "确认写操作",
                f"工具 {name} 会修改本地数据。\n风险等级：{definition.risk}\n确认执行？"
            ) == QMessageBox.Yes
        result = self.registry.execute(name, arguments, confirmed=confirmed)
        self.result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        self.refresh_audit()

    def refresh_audit(self) -> None:
        logs = self.registry.recent_logs()
        self.audit.setRowCount(len(logs))
        for row, item in enumerate(logs):
            for column, text in enumerate((
                item.created_at.strftime("%Y-%m-%d %H:%M:%S"), item.tool_name,
                "成功" if item.success else "失败", f"{item.elapsed_ms} ms", item.audit_id
            )):
                self.audit.setItem(row, column, QTableWidgetItem(text))
