from __future__ import annotations

import html
import json
import re
from collections.abc import Callable

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai.chains import GroundedQAService, RAGAnswer, KnowledgeExtractionService
from app.services.domain import JobService, ResourceService


CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class QAWorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class QAWorker(QRunnable):
    """Run retrieval and model generation away from the Qt UI thread."""

    def __init__(
        self,
        *,
        qa_factory: Callable[[], GroundedQAService],
        jobs: JobService,
        job_id: int,
        question: str,
        course_id: int | None,
        resource_ids: list[int] | None,
    ) -> None:
        super().__init__()
        self.qa_factory = qa_factory
        self.jobs = jobs
        self.job_id = job_id
        self.question = question
        self.course_id = course_id
        self.resource_ids = resource_ids
        self.signals = QAWorkerSignals()
        # Python owns the runnable until the queued ``finished`` slot has run.
        # This avoids Qt deleting an auto-delete runnable while its signal
        # callbacks are still being delivered.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if self.jobs.is_cancelled(self.job_id):
                self.signals.failed.emit("问答任务已取消")
                return

            self.jobs.update(self.job_id, "running", 10, "正在检索资料")
            service = self.qa_factory()
            self.jobs.update(self.job_id, "running", 35, "正在生成带引用的回答")
            result = service.ask(
                self.question,
                course_id=self.course_id,
                resource_ids=self.resource_ids,
            )
            message = f"回答完成，使用 {len(result.citations)} 条引用"
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.succeeded.emit(result)
        except Exception as exc:
            message = str(exc)
            self.jobs.update(
                self.job_id,
                "failed",
                100,
                detail="资料问答失败",
                error=message,
            )
            self.signals.failed.emit(message)
        finally:
            self.signals.finished.emit()


class LazyKnowledgeWorker(QRunnable):
    def __init__(self, *, extraction_factory, jobs, job_id, course_id, chunk_ids):
        super().__init__()
        self.extraction_factory = extraction_factory
        self.jobs = jobs
        self.job_id = job_id
        self.course_id = course_id
        self.chunk_ids = chunk_ids
        self.signals = QAWorkerSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self.jobs.update(self.job_id, "running", 15, "正在总结引用片段中的知识点")
            result = self.extraction_factory().extract_selected(
                course_id=self.course_id,
                chunk_ids=self.chunk_ids,
                progress=lambda value: self.jobs.update(
                    self.job_id, "running", value, "正在生成待审核知识点"
                ),
                should_cancel=lambda: self.jobs.is_cancelled(self.job_id),
            )
            message = f"已生成 {result.draft_count} 条待审核知识点草稿"
            self.jobs.update(self.job_id, "completed", 100, message)
            self.signals.succeeded.emit(message)
        except Exception as exc:
            self.jobs.update(self.job_id, "failed", 100, "按需知识总结失败", str(exc))
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ResourceQAWidget(QWidget):
    jobs_changed = Signal()

    def __init__(
        self,
        *,
        resources: ResourceService,
        jobs: JobService,
        qa_factory: Callable[[], GroundedQAService],
        extraction_factory: Callable[[], KnowledgeExtractionService],
    ) -> None:
        super().__init__()
        self.resources = resources
        self.jobs = jobs
        self.qa_factory = qa_factory
        self.extraction_factory = extraction_factory
        self.pool = QThreadPool.globalInstance()
        self._worker: QAWorker | None = None
        self._citations: dict[int, object] = {}
        self._last_result: RAGAnswer | None = None
        self._memory_worker = None

        root = QVBoxLayout(self)
        description = QLabel(
            "回答只使用已经建立索引的学习资料；证据不足时不会凭空补全答案。"
        )
        description.setWordWrap(True)
        root.addWidget(description)

        scope_form = QFormLayout()
        self.course = QComboBox()
        self.course.currentIndexChanged.connect(self._course_changed)
        scope_form.addRow("课程范围", self.course)
        self.resource = QComboBox()
        scope_form.addRow("指定资料", self.resource)
        root.addLayout(scope_form)

        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("例如：函数极限和函数连续有什么区别？")
        self.question.setMaximumHeight(110)
        root.addWidget(self.question)

        actions = QHBoxLayout()
        self.ask_button = QPushButton("根据资料回答")
        self.ask_button.clicked.connect(self.ask)
        actions.addWidget(self.ask_button)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear)
        actions.addWidget(self.clear_button)
        self.remember_button = QPushButton("总结为知识点")
        self.remember_button.setEnabled(False)
        self.remember_button.clicked.connect(self.remember_knowledge)
        actions.addWidget(self.remember_button)
        actions.addStretch()
        self.status_label = QLabel("就绪")
        actions.addWidget(self.status_label)
        root.addLayout(actions)

        splitter = QSplitter()
        self.answer = QTextBrowser()
        self.answer.setOpenLinks(False)
        self.answer.setPlaceholderText("AI 回答将在这里显示")
        self.answer.anchorClicked.connect(self._open_answer_link)
        splitter.addWidget(self.answer)

        citation_container = QWidget()
        citation_layout = QVBoxLayout(citation_container)
        citation_layout.setContentsMargins(0, 0, 0, 0)
        citation_layout.addWidget(QLabel("引用来源"))
        self.citation_list = QListWidget()
        self.citation_list.itemActivated.connect(self._open_citation_item)
        citation_layout.addWidget(self.citation_list)
        self.excerpt = QPlainTextEdit()
        self.excerpt.setReadOnly(True)
        self.excerpt.setPlaceholderText("选择引用后查看原始资料片段")
        self.citation_list.currentItemChanged.connect(self._show_excerpt)
        citation_layout.addWidget(self.excerpt)
        splitter.addWidget(citation_container)
        splitter.setSizes([700, 380])
        root.addWidget(splitter, 1)
        self.refresh_scopes()

    def refresh_scopes(self) -> None:
        selected_course = self.course.currentData()
        selected_resource = self.resource.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        self.course.addItem("全部课程", None)
        for course in self.resources.list_courses():
            self.course.addItem(course.name, course.id)
        course_index = self.course.findData(selected_course)
        self.course.setCurrentIndex(course_index if course_index >= 0 else 0)
        self.course.blockSignals(False)
        self._refresh_resources(selected_resource)

    def _course_changed(self) -> None:
        self._refresh_resources(None)

    def _refresh_resources(self, selected_resource: int | None) -> None:
        course_id = self.course.currentData()
        self.resource.clear()
        self.resource.addItem("该范围内的全部资料", None)
        for item in self.resources.list_files("", False):
            if course_id is not None and item.course_id != course_id:
                continue
            self.resource.addItem(item.name, item.id)
        index = self.resource.findData(selected_resource)
        self.resource.setCurrentIndex(index if index >= 0 else 0)

    def ask(self) -> None:
        question = self.question.toPlainText().strip()
        if not question:
            QMessageBox.information(self, "资料问答", "请先输入问题。")
            return
        if self._worker is not None:
            QMessageBox.information(self, "资料问答", "当前问题仍在处理中。")
            return

        course_id = self.course.currentData()
        resource_id = self.resource.currentData()
        resource_ids = [int(resource_id)] if resource_id is not None else None
        payload = json.dumps(
            {
                "question": question,
                "course_id": course_id,
                "resource_ids": resource_ids or [],
            },
            ensure_ascii=False,
        )
        job = self.jobs.create(
            "document_qa",
            f"资料问答：{question[:50]}",
            payload=payload,
        )
        worker = QAWorker(
            qa_factory=self.qa_factory,
            jobs=self.jobs,
            job_id=job.id,
            question=question,
            course_id=course_id,
            resource_ids=resource_ids,
        )
        worker.signals.succeeded.connect(self._answer_succeeded)
        worker.signals.failed.connect(self._answer_failed)
        worker.signals.finished.connect(self._answer_finished)
        self._worker = worker
        self.ask_button.setEnabled(False)
        self.status_label.setText("正在检索和生成回答…")
        self.answer.setPlainText("正在处理，请稍候。")
        self.citation_list.clear()
        self.excerpt.clear()
        self._citations.clear()
        self.jobs_changed.emit()
        self.pool.start(worker)

    def _answer_succeeded(self, result: RAGAnswer) -> None:
        self._last_result = result
        self.remember_button.setEnabled(bool(result.citations))
        self._citations = {
            citation.number: citation for citation in result.citations
        }
        escaped = html.escape(result.answer)
        linked = CITATION_PATTERN.sub(
            lambda match: (
                f'<a href="citation:{match.group(1)}">[{match.group(1)}]</a>'
            ),
            escaped,
        )
        banner = ""
        if result.insufficient_evidence:
            banner = (
                '<p style="color:#b54708;"><b>证据不足：</b>'
                "以下回答可能无法完整解决问题。</p>"
            )
        self.answer.setHtml(
            banner
            + '<div style="line-height:1.65;">'
            + linked.replace("\n", "<br>")
            + "</div>"
        )
        self.citation_list.clear()
        for citation in result.citations:
            item = QListWidgetItem(
                f"[{citation.number}] {citation.citation_label}"
            )
            item.setData(Qt.UserRole, citation.number)
            self.citation_list.addItem(item)
        if result.citations:
            self.citation_list.setCurrentRow(0)
        self.status_label.setText(f"完成 · {len(result.citations)} 条引用")

    def _answer_failed(self, message: str) -> None:
        self._last_result = None
        self.remember_button.setEnabled(False)
        self.answer.setPlainText("资料问答失败。\n\n" + message)
        self.status_label.setText("失败")

    def _answer_finished(self) -> None:
        self.ask_button.setEnabled(True)
        self.jobs_changed.emit()
        # Keep the runnable alive for one more event-loop turn. Its ``finished``
        # signal is emitted immediately before ``run`` returns on another
        # thread, so releasing it synchronously can race with that return.
        QTimer.singleShot(0, self._release_worker)

    def _release_worker(self) -> None:
        self._worker = None

    def remember_knowledge(self) -> None:
        if self._last_result is None or not self._last_result.citations:
            QMessageBox.information(self, "知识总结", "当前回答没有可总结的资料引用。")
            return
        course_id = self.course.currentData()
        if course_id is None:
            QMessageBox.warning(self, "知识总结", "请先选择一个课程范围。")
            return
        chunk_ids = list(dict.fromkeys(
            citation.chunk_id for citation in self._last_result.citations
        ))
        job = self.jobs.create("lazy_knowledge_extraction", "总结当前回答引用片段")
        self.remember_button.setEnabled(False)
        worker = LazyKnowledgeWorker(
            extraction_factory=self.extraction_factory,
            jobs=self.jobs,
            job_id=job.id,
            course_id=course_id,
            chunk_ids=chunk_ids,
        )
        worker.signals.succeeded.connect(
            lambda message: QMessageBox.information(self, "知识总结完成", message)
        )
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(self, "知识总结失败", message)
        )
        worker.signals.finished.connect(lambda: self.remember_button.setEnabled(True))
        worker.signals.finished.connect(self.jobs_changed.emit)
        self._memory_worker = worker
        self.pool.start(worker)

    def _show_excerpt(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            self.excerpt.clear()
            return
        number = current.data(Qt.UserRole)
        citation = self._citations.get(int(number))
        if citation is None:
            self.excerpt.clear()
            return
        self.excerpt.setPlainText(
            f"{citation.citation_label}\n"
            f"Chunk ID：{citation.chunk_id}\n"
            f"RRF：{citation.rrf_score:.6f}\n\n"
            f"{citation.excerpt}"
        )

    def _open_answer_link(self, url: QUrl) -> None:
        if url.scheme() != "citation":
            return
        try:
            number = int(url.path())
        except ValueError:
            return
        self.open_citation(number)

    def _open_citation_item(self, item: QListWidgetItem) -> None:
        number = item.data(Qt.UserRole)
        if number is not None:
            self.open_citation(int(number))

    def open_citation(self, number: int) -> None:
        citation = self._citations.get(number)
        if citation is None:
            return
        try:
            path = self.resources.content_path(citation.resource_id)
            url = QUrl.fromLocalFile(str(path))
            if path.suffix.lower() == ".pdf":
                page_match = re.search(r"第\s*(\d+)\s*页", citation.location_label)
                if page_match:
                    url.setFragment(f"page={page_match.group(1)}")
            if not QDesktopServices.openUrl(url):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法打开引用", str(exc))

    def clear(self) -> None:
        if self._worker is not None:
            return
        self.question.clear()
        self.answer.clear()
        self.citation_list.clear()
        self.excerpt.clear()
        self._citations.clear()
        self._last_result = None
        self.remember_button.setEnabled(False)
        self.status_label.setText("就绪")
