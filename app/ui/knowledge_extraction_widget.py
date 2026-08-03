from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ai.chains import KnowledgeDraftService, KnowledgeExtractionService
from ai.retrieval import KnowledgePointIndex
from app.services.domain import JobService, ResourceService


class KnowledgeExtractionSignals(QObject):
    finished = Signal(bool, str)


class KnowledgeExtractionWorker(QRunnable):
    def __init__(
        self,
        *,
        service_factory: Callable[[], KnowledgeExtractionService],
        jobs: JobService,
        job_id: int,
        course_id: int,
        resource_ids: list[int] | None,
    ) -> None:
        super().__init__()
        self.service_factory = service_factory
        self.jobs = jobs
        self.job_id = job_id
        self.course_id = course_id
        self.resource_ids = resource_ids
        self.signals = KnowledgeExtractionSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self.jobs.update(self.job_id, "running", 5, "正在准备知识点抽取")
            result = self.service_factory().extract(
                course_id=self.course_id,
                resource_ids=self.resource_ids,
                progress=lambda value: self.jobs.update(
                    self.job_id, "running", value, "正在抽取和合并知识点"
                ),
                should_cancel=lambda: self.jobs.is_cancelled(self.job_id),
            )
            message = (
                f"已从 {result.chunk_count} 个资料片段生成 "
                f"{result.draft_count} 条待审核知识点"
            )
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.finished.emit(True, message)
        except InterruptedError as exc:
            self.jobs.update(self.job_id, "cancelled", 100, str(exc))
            self.signals.finished.emit(False, str(exc))
        except Exception as exc:
            message = str(exc)
            if "timed out" in message.casefold() or "timeout" in message.casefold():
                message = (
                    "模型请求超时。资料索引没有丢失，请重试；如果仍然失败，"
                    "请检查 API 服务状态或提高请求超时时间。"
                )
            self.jobs.update(
                self.job_id, "failed", 100,
                detail="知识点抽取失败", error=message,
            )
            self.signals.finished.emit(False, message)


class KnowledgeIndexWorker(QRunnable):
    def __init__(
        self,
        *,
        index_factory: Callable[[], KnowledgePointIndex],
        jobs: JobService,
        job_id: int,
    ) -> None:
        super().__init__()
        self.index_factory = index_factory
        self.jobs = jobs
        self.job_id = job_id
        self.signals = KnowledgeExtractionSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self.jobs.update(self.job_id, "running", 10, "正在重建知识点索引")
            count = self.index_factory().rebuild()
            message = f"已重建 {count} 个正式知识点的关键词和向量索引"
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.finished.emit(True, message)
        except Exception as exc:
            self.jobs.update(
                self.job_id, "failed", 100,
                detail="知识点索引失败", error=str(exc),
            )
            self.signals.finished.emit(False, str(exc))


class KnowledgeExtractionWidget(QWidget):
    jobs_changed = Signal()
    knowledge_changed = Signal()

    def __init__(
        self,
        *,
        resources: ResourceService,
        jobs: JobService,
        draft_service: KnowledgeDraftService,
        extraction_factory: Callable[[], KnowledgeExtractionService],
        index_factory: Callable[[], KnowledgePointIndex],
    ) -> None:
        super().__init__()
        self.resources = resources
        self.jobs = jobs
        self.drafts = draft_service
        self.extraction_factory = extraction_factory
        self.index_factory = index_factory
        self.pool = QThreadPool.globalInstance()
        self._workers: list[QRunnable] = []

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh_resources)
        self.resource = QComboBox()
        extract = QPushButton("从资料抽取知识点")
        extract.setProperty("primary", True)
        extract.clicked.connect(self.start_extraction)
        rebuild = QPushButton("重建知识点索引")
        rebuild.clicked.connect(self.rebuild_index)
        self.status_filter = QComboBox()
        self.status_filter.addItem("待审核", "pending")
        self.status_filter.addItem("已接受", "accepted")
        self.status_filter.addItem("已拒绝", "rejected")
        self.status_filter.addItem("全部草稿", None)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(QLabel("课程"))
        bar.addWidget(self.course)
        bar.addWidget(QLabel("资料"))
        bar.addWidget(self.resource, 1)
        bar.addWidget(extract)
        bar.addWidget(rebuild)
        bar.addWidget(self.status_filter)
        root.addLayout(bar)

        splitter = QSplitter()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "名称", "类型", "难度", "重要性", "置信度", "证据数", "状态"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选择草稿后查看定义、公式和原文证据")
        actions = QHBoxLayout()
        accept = QPushButton("接受并写入知识库")
        accept.clicked.connect(self.accept_selected)
        reject = QPushButton("拒绝")
        reject.clicked.connect(self.reject_selected)
        actions.addWidget(accept)
        actions.addWidget(reject)
        detail_layout.addWidget(self.detail)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail)
        splitter.setSizes([700, 430])
        root.addWidget(splitter, 1)
        self.refresh_scopes()

    def refresh_scopes(self) -> None:
        selected_course = self.course.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        for course in self.resources.list_courses():
            self.course.addItem(course.name, course.id)
        if selected_course is not None:
            index = self.course.findData(selected_course)
            self.course.setCurrentIndex(max(0, index))
        self.course.blockSignals(False)
        self.refresh_resources()

    def refresh_resources(self) -> None:
        course_id = self.course.currentData()
        selected_resource = self.resource.currentData()
        self.resource.clear()
        self.resource.addItem("该课程的全部已索引资料", None)
        for item in self.resources.list_files():
            if item.course_id == course_id:
                self.resource.addItem(item.name, item.id)
        if selected_resource is not None:
            index = self.resource.findData(selected_resource)
            self.resource.setCurrentIndex(max(0, index))
        self.refresh()

    def refresh(self) -> None:
        course_id = self.course.currentData()
        status = self.status_filter.currentData()
        rows = self.drafts.list(course_id=course_id, status=status)
        self.table.setRowCount(len(rows))
        for row, draft in enumerate(rows):
            name = QTableWidgetItem(draft.name)
            name.setData(Qt.UserRole, draft.id)
            name.setData(Qt.UserRole + 1, draft)
            values = (
                name,
                QTableWidgetItem(draft.category),
                QTableWidgetItem(str(draft.difficulty)),
                QTableWidgetItem(str(draft.importance)),
                QTableWidgetItem(f"{draft.confidence:.0%}"),
                QTableWidgetItem(str(len(draft.citations))),
                QTableWidgetItem(draft.status),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, value)
        self.detail.clear()

    def start_extraction(self) -> None:
        course_id = self.course.currentData()
        if course_id is None:
            QMessageBox.information(self, "知识点抽取", "请先创建并选择课程。")
            return
        resource_id = self.resource.currentData()
        payload = json.dumps({
            "course_id": course_id,
            "resource_ids": [resource_id] if resource_id else [],
        }, ensure_ascii=False)
        job = self.jobs.create(
            "knowledge_extraction", "AI 知识点抽取", payload=payload
        )
        worker = KnowledgeExtractionWorker(
            service_factory=self.extraction_factory,
            jobs=self.jobs,
            job_id=job.id,
            course_id=course_id,
            resource_ids=[resource_id] if resource_id else None,
        )
        worker.signals.finished.connect(
            lambda ok, message, item=worker: self._finished(ok, message, item)
        )
        self._workers.append(worker)
        self.pool.start(worker)
        self.jobs_changed.emit()
        QMessageBox.information(self, "知识点抽取", "任务已经加入后台队列。")

    def _finished(
        self, ok: bool, message: str, worker: QRunnable
    ) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self.refresh()
        self.jobs_changed.emit()
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "知识点抽取完成" if ok else "知识点抽取失败", message
        )

    def rebuild_index(self) -> None:
        job = self.jobs.create(
            "knowledge_index", "重建正式知识点混合检索索引"
        )
        worker = KnowledgeIndexWorker(
            index_factory=self.index_factory,
            jobs=self.jobs,
            job_id=job.id,
        )
        worker.signals.finished.connect(
            lambda ok, message, item=worker: self._finished(ok, message, item)
        )
        self._workers.append(worker)
        self.pool.start(worker)
        self.jobs_changed.emit()
        QMessageBox.information(self, "知识点索引", "任务已经加入后台队列。")

    def _selected_draft(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole + 1) if item else None

    def show_detail(self) -> None:
        draft = self._selected_draft()
        if draft is None:
            self.detail.clear()
            return
        lines = [
            f"名称：{draft.name}",
            f"类型：{draft.category}",
            f"难度：{draft.difficulty} / 5",
            f"重要性：{draft.importance} / 5",
            f"置信度：{draft.confidence:.0%}",
            "",
            "定义：",
            draft.definition,
        ]
        if draft.formula:
            lines.extend(["", "公式：", draft.formula])
        lines.extend(["", "原文证据："])
        for number, citation in enumerate(draft.citations, 1):
            lines.extend([
                f"[{number}] {citation.source_name}，{citation.location_label}",
                citation.quote_text,
                "",
            ])
        self.detail.setPlainText("\n".join(lines).rstrip())

    def accept_selected(self) -> None:
        draft = self._selected_draft()
        if draft is None:
            QMessageBox.information(self, "知识点审核", "请先选择草稿。")
            return
        try:
            self.drafts.accept(draft.id)
            self.refresh()
            self.knowledge_changed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, "无法接受", str(exc))

    def reject_selected(self) -> None:
        draft = self._selected_draft()
        if draft is None:
            QMessageBox.information(self, "知识点审核", "请先选择草稿。")
            return
        try:
            self.drafts.reject(draft.id)
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "无法拒绝", str(exc))
