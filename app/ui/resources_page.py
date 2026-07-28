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


class ImportSignals(QObject):
    finished = Signal(bool, str)


class ImportWorker(QRunnable):
    def __init__(self, service: ResourceService, jobs: JobService, job_id: int, path: Path, directory: bool) -> None:
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.job_id = job_id
        self.path = path
        self.directory = directory
        self.signals = ImportSignals()

    def run(self) -> None:
        self.jobs.update(self.job_id, "running", 10, f"正在导入 {self.path.name}")
        try:
            if self.directory:
                count, errors = self.service.import_directory(
                    self.path,
                    should_cancel=lambda: self.jobs.is_cancelled(self.job_id),
                    progress=lambda value: self.jobs.update(
                        self.job_id, "running", value, f"正在导入 {self.path.name}"
                    ),
                )
                message = f"成功导入 {count} 个文件，跳过 {len(errors)} 个"
            else:
                self.service.import_file(self.path)
                message = f"已导入 {self.path.name}"
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.finished.emit(True, message)
        except InterruptedError as error:
            self.jobs.update(self.job_id, "cancelled", 100, str(error))
            self.signals.finished.emit(False, str(error))
        except Exception as error:
            self.jobs.update(self.job_id, "failed", 100, error=str(error))
            self.signals.finished.emit(False, str(error))


class ResourcesPage(QWidget):
    def __init__(self, service: ResourceService, jobs: JobService) -> None:
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.pool = QThreadPool.globalInstance()
        self._workers: list[ImportWorker] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("学习资料", "文件会复制到受管 workspace，可安全预览和恢复"))
        actions = QGridLayout()
        for index, (text, slot) in enumerate([
            ("添加文件", self.import_file), ("添加目录", self.import_directory),
            ("新建文件夹", self.create_folder), ("移动", self.move_file),
            ("重命名", self.rename), ("关联/标签", self.metadata),
            ("移到回收站", self.trash), ("恢复", self.restore), ("彻底删除", self.delete_permanently),
            ("系统打开", self.open_system), ("打开所在目录", self.open_folder),
        ]):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button, index // 5, index % 5)
        root.addLayout(actions)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名")
        self.search.textChanged.connect(self.refresh)
        self.scope = QComboBox()
        self.scope.addItems(["全部资料", "回收站"])
        self.scope.currentTextChanged.connect(self.refresh)
        self.view_mode = QComboBox()
        self.view_mode.addItems(["列表", "缩略图"])
        filters.addStretch()
        filters.addWidget(self.search)
        filters.addWidget(self.scope)
        filters.addWidget(self.view_mode)
        root.addLayout(filters)
        splitter = QSplitter()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "课程", "标签", "相对路径", "加入时间"])
        self.table.setColumnHidden(0, False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.preview)
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setPlaceholderText("选择资料后在此预览文本内容")
        splitter.addWidget(self.table)
        splitter.addWidget(self.preview_box)
        splitter.setSizes([750, 360])
        self.card_container = QWidget()
        self.card_grid = QGridLayout(self.card_container)
        card_scroll = QScrollArea()
        card_scroll.setWidgetResizable(True)
        card_scroll.setWidget(self.card_container)
        self.views = QStackedWidget()
        self.views.addWidget(splitter)
        self.views.addWidget(card_scroll)
        self.view_mode.currentIndexChanged.connect(self.views.setCurrentIndex)
        root.addWidget(self.views, 1)
        self.refresh()

    def refresh(self) -> None:
        items = self.service.list_files(self.search.text(), self.scope.currentText() == "回收站")
        course_names = {course.id: course.name for course in self.service.list_courses()}
        self.table.setRowCount(len(items))
        while self.card_grid.count():
            layout_item = self.card_grid.takeAt(0)
            if layout_item.widget():
                layout_item.widget().deleteLater()
        for row, item in enumerate(items):
            name = QTableWidgetItem(item.name)
            name.setData(Qt.UserRole, item.id)
            values = [name, QTableWidgetItem(Path(item.name).suffix.lower() or "文件"),
                      QTableWidgetItem(self._size(item.size)),
                      QTableWidgetItem(course_names.get(item.course_id, "未关联")),
                      QTableWidgetItem(item.tags), QTableWidgetItem(item.relative_path),
                      QTableWidgetItem(item.created_at.strftime("%Y-%m-%d %H:%M"))]
            for column, value in enumerate(values):
                self.table.setItem(row, column, value)
            card = QFrame()
            card.setProperty("card", True)
            card_layout = QVBoxLayout(card)
            icon = QLabel()
            icon.setPixmap(IconProvider.get("file").pixmap(48, 48))
            icon.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(icon)
            title = QLabel(item.name)
            title.setAlignment(Qt.AlignCenter)
            title.setWordWrap(True)
            card_layout.addWidget(title)
            card_layout.addWidget(QLabel(self._size(item.size), alignment=Qt.AlignCenter))
            open_button = QPushButton("打开")
            open_button.clicked.connect(
                lambda _=False, item_id=item.id: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.service.content_path(item_id)))
                )
            )
            card_layout.addWidget(open_button)
            self.card_grid.addWidget(card, row // 4, row % 4)

    @staticmethod
    def _size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    def import_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "添加学习资料")
        if filename:
            self._start_import(Path(filename), False)

    def import_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "添加资料目录")
        if directory:
            self._start_import(Path(directory), True)

    def _start_import(self, path: Path, directory: bool, job_id: int | None = None) -> None:
        job = self.jobs.create("directory_import" if directory else "file_import", str(path)) if job_id is None else self.jobs.get(job_id)
        if not job:
            raise ValueError("后台任务不存在")
        worker = ImportWorker(self.service, self.jobs, job.id, path, directory)
        worker.signals.finished.connect(lambda ok, message, item=worker: self._import_finished(ok, message, item))
        self._workers.append(worker)
        self.pool.start(worker)

    def _import_finished(self, ok: bool, message: str, worker: ImportWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self.refresh()
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "导入完成" if ok else "导入失败", message
        )

    def rename(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        current = self.table.item(self.table.currentRow(), 0).text()
        name, ok = QInputDialog.getText(self, "重命名", "新文件名", text=current)
        if ok:
            try:
                self.service.rename(item_id, name)
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "重命名失败", str(error))

    def create_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "新建文件夹", "workspace 内相对路径")
        if ok:
            try:
                self.service.create_folder(name)
                QMessageBox.information(self, "文件夹", "文件夹已创建。")
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "无法创建", str(error))

    def move_file(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        folders = self.service.list_folders()
        folder, ok = QInputDialog.getItem(
            self, "移动资料", "目标文件夹", ["."] + folders, editable=False
        )
        if ok:
            try:
                self.service.move(item_id, folder)
                self.refresh()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "无法移动", str(error))

    def trash(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is not None and QMessageBox.question(self, "移到回收站", "资料可从回收站恢复，继续？") == QMessageBox.Yes:
            self.service.move_to_trash(item_id)
            self.refresh()

    def metadata(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        row = self.table.currentRow()
        dialog = QDialog(self)
        dialog.setWindowTitle("关联课程与标签")
        form = QFormLayout(dialog)
        courses = self.service.list_courses()
        course = QComboBox()
        course.addItem("未关联", None)
        for item in courses:
            course.addItem(item.name, item.id)
        current_course = self.table.item(row, 3).text()
        course.setCurrentText(current_course)
        tags = QLineEdit(self.table.item(row, 4).text())
        tags.setPlaceholderText("用逗号分隔多个标签")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow("课程", course)
        form.addRow("标签", tags)
        form.addRow(buttons)
        if dialog.exec():
            self.service.set_metadata(item_id, course.currentData(), tags.text())
            self.refresh()

    def restore(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is not None:
            self.service.restore(item_id)
            self.refresh()

    def delete_permanently(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        if QMessageBox.warning(
            self, "彻底删除", "此操作无法撤销，仅适用于回收站资料。确认继续？",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            try:
                self.service.delete_permanently(item_id)
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "无法删除", str(error))

    def open_system(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is not None:
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.content_path(item_id))))
            except ValueError as error:
                QMessageBox.warning(self, "无法打开", str(error))

    def open_folder(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is not None:
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.content_path(item_id).parent)))
            except ValueError as error:
                QMessageBox.warning(self, "无法打开", str(error))

    def preview(self) -> None:
        item_id = _selected_id(self.table)
        if item_id is None:
            return
        try:
            path = self.service.content_path(item_id)
            if path.suffix.lower() in {".txt", ".md", ".py", ".json", ".csv", ".yaml", ".yml"}:
                self.preview_box.setPlainText(path.read_text(encoding="utf-8", errors="replace")[:200_000])
            else:
                self.preview_box.setPlainText(f"文件：{path.name}\n类型：{path.suffix or '未知'}\n\n此类型请使用系统应用打开。")
        except (OSError, ValueError) as error:
            self.preview_box.setPlainText(str(error))


