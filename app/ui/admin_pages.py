from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.domain import JobService
from app.ui.pages import page_title


class JobsPage(QWidget):
    retry_requested = Signal(int)
    def __init__(self, service: JobService) -> None:
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("后台任务", "查看导入、导出和维护工作的进度与结果"))
        actions = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        clear = QPushButton("清理历史")
        clear.clicked.connect(self.clear)
        actions.addWidget(refresh)
        actions.addWidget(clear)
        actions.addStretch()
        root.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["类型", "状态", "进度", "详情", "错误", "创建时间", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        jobs = self.service.list()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = (
                job.job_type, job.status, f"{job.progress}%", job.detail,
                job.error, job.created_at.strftime("%Y-%m-%d %H:%M:%S")
            )
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(text))
            operations = QWidget()
            layout = QHBoxLayout(operations)
            layout.setContentsMargins(0, 0, 0, 0)
            cancel = QPushButton("取消")
            cancel.setEnabled(job.status in {"queued", "running"})
            cancel.clicked.connect(lambda _=False, item_id=job.id: self.cancel(item_id))
            retry = QPushButton("重试")
            retry.setEnabled(job.status in {"failed", "cancelled", "interrupted"})
            retry.clicked.connect(lambda _=False, item_id=job.id: self.retry_requested.emit(item_id))
            layout.addWidget(cancel)
            layout.addWidget(retry)
            self.table.setCellWidget(row, 6, operations)

    def clear(self) -> None:
        count = self.service.clear_history()
        self.refresh()
        QMessageBox.information(self, "清理完成", f"已清理 {count} 条历史记录。")

    def cancel(self, job_id: int) -> None:
        self.service.cancel(job_id)
        self.refresh()


class LogsPage(QWidget):
    def __init__(self, log_path: Path) -> None:
        super().__init__()
        self.log_path = log_path
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("日志查看器", "查看本地运行日志，可按级别和关键词筛选"))
        actions = QHBoxLayout()
        self.level = QLineEdit()
        self.level.setPlaceholderText("级别，例如 ERROR")
        self.query = QLineEdit()
        self.query.setPlaceholderText("关键词")
        self.level.textChanged.connect(self.refresh)
        self.query.textChanged.connect(self.refresh)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        export = QPushButton("导出日志")
        export.clicked.connect(self.export)
        clear = QPushButton("清理日志")
        clear.clicked.connect(self.clear)
        actions.addWidget(self.level)
        actions.addWidget(self.query, 1)
        actions.addWidget(refresh)
        actions.addWidget(export)
        actions.addWidget(clear)
        root.addLayout(actions)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["时间/级别", "消息"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.refresh()

    def _lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        level = self.level.text().strip().casefold()
        query = self.query.text().strip().casefold()
        return [line for line in lines if (not level or level in line.casefold()) and (not query or query in line.casefold())]

    def refresh(self) -> None:
        lines = self._lines()
        self.table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            head, _, message = line.partition(": ")
            self.table.setItem(row, 0, QTableWidgetItem(head))
            self.table.setItem(row, 1, QTableWidgetItem(message))
        if lines:
            self.table.scrollToBottom()

    def export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "导出日志", "app-log.txt", "Text (*.txt)")
        if filename:
            Path(filename).write_text("\n".join(self._lines()), encoding="utf-8")

    def clear(self) -> None:
        if QMessageBox.question(self, "清理日志", "此操作会清空当前日志文件，确认继续？") == QMessageBox.Yes:
            self.log_path.write_text("", encoding="utf-8")
            self.refresh()
