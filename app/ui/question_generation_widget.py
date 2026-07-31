from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.chains import QuestionDraftService, QuestionGenerationService
from app.services.domain import JobService, ResourceService


class QuestionGenerationSignals(QObject):
    finished = Signal(bool, str)


class QuestionGenerationWorker(QRunnable):
    """在后台线程执行知识点和原始资料的联合召回及出题。"""

    def __init__(
        self,
        *,
        service_factory: Callable[[], QuestionGenerationService],
        jobs: JobService,
        job_id: int,
        request: str,
        course_id: int,
        count: int,
        kinds: list[str],
        difficulty: int,
        resource_ids: list[int] | None,
    ) -> None:
        super().__init__()
        self.service_factory = service_factory
        self.jobs = jobs
        self.job_id = job_id
        self.request = request
        self.course_id = course_id
        self.count = count
        self.kinds = kinds
        self.difficulty = difficulty
        self.resource_ids = resource_ids
        self.signals = QuestionGenerationSignals()

    def run(self) -> None:
        try:
            self.jobs.update(self.job_id, "running", 10, "正在准备 AI 出题")
            result = self.service_factory().generate(
                self.request,
                course_id=self.course_id,
                count=self.count,
                kinds=self.kinds,
                difficulty=self.difficulty,
                resource_ids=self.resource_ids,
            )
            message = (
                f"已生成 {len(result.draft_ids)} 道待审核题目；"
                f"召回 {result.knowledge_hit_count} 个知识点、"
                f"{result.document_hit_count} 个原文片段"
            )
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.finished.emit(True, message)
        except InterruptedError as exc:
            self.jobs.update(self.job_id, "cancelled", 100, str(exc))
            self.signals.finished.emit(False, str(exc))
        except Exception as exc:
            self.jobs.update(
                self.job_id,
                "failed",
                100,
                detail="AI 出题失败",
                error=str(exc),
            )
            self.signals.finished.emit(False, str(exc))


class QuestionGenerationWidget(QWidget):
    jobs_changed = Signal()
    questions_changed = Signal()

    def __init__(
        self,
        *,
        resources: ResourceService,
        jobs: JobService,
        draft_service: QuestionDraftService,
        generation_factory: Callable[[], QuestionGenerationService],
    ) -> None:
        super().__init__()
        self.resources = resources
        self.jobs = jobs
        self.drafts = draft_service
        self.generation_factory = generation_factory
        self.pool = QThreadPool.globalInstance()
        self._workers: list[QRunnable] = []

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self.refresh_resources)
        self.resource = QComboBox()
        self.request = QTextEdit()
        self.request.setMaximumHeight(90)
        self.request.setPlaceholderText(
            "例如：围绕函数极限的定义和常见错误，生成概念辨析题"
        )
        self.count = QSpinBox()
        self.count.setRange(1, 20)
        self.count.setValue(5)
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(3)

        kinds_widget = QWidget()
        kinds_layout = QHBoxLayout(kinds_widget)
        kinds_layout.setContentsMargins(0, 0, 0, 0)
        self.kind_checks: dict[str, QCheckBox] = {}
        for kind in ("单选", "多选", "判断", "填空", "简答"):
            checkbox = QCheckBox(kind)
            checkbox.setChecked(kind in {"单选", "判断", "填空", "简答"})
            self.kind_checks[kind] = checkbox
            kinds_layout.addWidget(checkbox)
        kinds_layout.addStretch()

        generate = QPushButton("生成题目草稿")
        generate.setProperty("primary", True)
        generate.clicked.connect(self.start_generation)

        form.addRow("课程", self.course)
        form.addRow("资料范围", self.resource)
        form.addRow("出题要求", self.request)
        form.addRow("题目数量", self.count)
        form.addRow("目标难度", self.difficulty)
        form.addRow("允许题型", kinds_widget)
        form.addRow(generate)
        root.addLayout(form)

        filters = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("待审核", "pending")
        self.status_filter.addItem("已接受", "accepted")
        self.status_filter.addItem("已拒绝", "rejected")
        self.status_filter.addItem("全部草稿", None)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        refresh_button = QPushButton("刷新草稿")
        refresh_button.clicked.connect(self.refresh)
        filters.addWidget(QLabel("草稿状态"))
        filters.addWidget(self.status_filter)
        filters.addStretch()
        filters.addWidget(refresh_button)
        root.addLayout(filters)

        splitter = QSplitter()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "题干", "题型", "知识点", "难度", "引用数", "状态", "标准答案"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(self.table)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(
            "选择草稿后查看题干、答案、解析和原始资料引用"
        )
        actions = QHBoxLayout()
        accept = QPushButton("接受并写入题库")
        accept.setProperty("primary", True)
        accept.clicked.connect(self.accept_selected)
        reject = QPushButton("拒绝")
        reject.clicked.connect(self.reject_selected)
        actions.addWidget(accept)
        actions.addWidget(reject)
        actions.addStretch()
        detail_layout.addWidget(self.detail, 1)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail_widget)
        splitter.setSizes([720, 430])
        root.addWidget(splitter, 1)

        self.refresh_scopes()

    def refresh_scopes(self) -> None:
        selected_course = self.course.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        for course in self.resources.list_courses():
            self.course.addItem(course.name, course.id)
        if selected_course is not None:
            self.course.setCurrentIndex(max(0, self.course.findData(selected_course)))
        self.course.blockSignals(False)
        self.refresh_resources()

    def refresh_resources(self) -> None:
        course_id = self.course.currentData()
        selected_resource = self.resource.currentData()
        self.resource.clear()
        self.resource.addItem("该课程的全部已索引资料", None)
        for resource in self.resources.list_files():
            if resource.course_id == course_id:
                self.resource.addItem(resource.name, resource.id)
        if selected_resource is not None:
            self.resource.setCurrentIndex(
                max(0, self.resource.findData(selected_resource))
            )
        self.refresh()

    def selected_kinds(self) -> list[str]:
        return [
            kind for kind, checkbox in self.kind_checks.items()
            if checkbox.isChecked()
        ]

    def start_generation(self) -> None:
        course_id = self.course.currentData()
        request = self.request.toPlainText().strip()
        kinds = self.selected_kinds()
        if course_id is None:
            QMessageBox.information(self, "AI 出题", "请先创建并选择课程。")
            return
        if not request:
            QMessageBox.information(self, "AI 出题", "请输入出题要求。")
            return
        if not kinds:
            QMessageBox.information(self, "AI 出题", "请至少选择一种题型。")
            return

        resource_id = self.resource.currentData()
        resource_ids = [resource_id] if resource_id is not None else None
        payload = json.dumps({
            "request": request,
            "course_id": course_id,
            "count": self.count.value(),
            "kinds": kinds,
            "difficulty": self.difficulty.value(),
            "resource_ids": resource_ids or [],
        }, ensure_ascii=False)
        job = self.jobs.create(
            "question_generation",
            "AI 生成题目草稿",
            payload=payload,
        )
        worker = QuestionGenerationWorker(
            service_factory=self.generation_factory,
            jobs=self.jobs,
            job_id=job.id,
            request=request,
            course_id=course_id,
            count=self.count.value(),
            kinds=kinds,
            difficulty=self.difficulty.value(),
            resource_ids=resource_ids,
        )
        worker.signals.finished.connect(
            lambda ok, message, item=worker:
            self._generation_finished(ok, message, item)
        )
        self._workers.append(worker)
        self.pool.start(worker)
        self.jobs_changed.emit()
        QMessageBox.information(self, "AI 出题", "任务已经加入后台队列。")

    def _generation_finished(
        self, ok: bool, message: str, worker: QRunnable
    ) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self.refresh()
        self.jobs_changed.emit()
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "AI 出题完成" if ok else "AI 出题失败", message
        )

    def refresh(self) -> None:
        drafts = self.drafts.list(
            course_id=self.course.currentData(),
            status=self.status_filter.currentData(),
        )
        self.table.setRowCount(len(drafts))
        for row, draft in enumerate(drafts):
            prompt = QTableWidgetItem(draft.prompt)
            prompt.setData(Qt.UserRole, draft.id)
            prompt.setData(Qt.UserRole + 1, draft)
            values = (
                prompt,
                QTableWidgetItem(draft.kind),
                QTableWidgetItem(draft.knowledge_point_name),
                QTableWidgetItem(str(draft.difficulty)),
                QTableWidgetItem(str(len(draft.citations))),
                QTableWidgetItem(draft.status),
                QTableWidgetItem(draft.answer),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, value)
        self.detail.clear()

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
            f"题型：{draft.kind}",
            f"知识点：{draft.knowledge_point_name}",
            f"难度：{draft.difficulty} / 5",
            "",
            "题干：",
            draft.prompt,
        ]
        if draft.options:
            lines.extend(["", "选项：", *draft.options])
        lines.extend([
            "",
            "标准答案：",
            draft.answer,
            "",
            "解析：",
            draft.explanation,
        ])
        if draft.tags:
            lines.extend(["", "标签：", "、".join(draft.tags)])
        lines.extend(["", "原始资料引用："])
        if not draft.citations:
            lines.append("没有保存引用。")
        for number, citation in enumerate(draft.citations, 1):
            location = (
                f"，{citation.location_label}" if citation.location_label else ""
            )
            lines.extend([
                "",
                f"[D{number}] {citation.source_name}{location}",
                f"片段 ID：{citation.chunk_id}",
                citation.quote_text,
            ])
        self.detail.setPlainText("\n".join(lines))

    def accept_selected(self) -> None:
        draft = self._selected_draft()
        if draft is None:
            QMessageBox.information(self, "题目审核", "请先选择题目草稿。")
            return
        note, ok = QInputDialog.getMultiLineText(
            self, "接受题目", "审核备注（可选）"
        )
        if not ok:
            return
        try:
            question_id = self.drafts.accept(draft.id, review_note=note)
            self.refresh()
            self.questions_changed.emit()
            QMessageBox.information(
                self, "题目审核", f"题目已写入正式题库，ID：{question_id}"
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "无法接受", str(exc))

    def reject_selected(self) -> None:
        draft = self._selected_draft()
        if draft is None:
            QMessageBox.information(self, "题目审核", "请先选择题目草稿。")
            return
        reason, ok = QInputDialog.getMultiLineText(
            self, "拒绝题目", "拒绝原因（可选）"
        )
        if not ok:
            return
        try:
            self.drafts.reject(draft.id, review_note=reason)
            self.refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "无法拒绝", str(exc))
