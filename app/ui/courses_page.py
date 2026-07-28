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

class CourseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, course: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑课程" if course else "新建课程")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：高中数学 · 函数专题")
        self.stage = QComboBox()
        self.stage.addItems(["小学", "初中", "高中", "大学", "职业考试", "其他"])
        self.stage.setCurrentText("高中")
        self.subject = QLineEdit("数学")
        self.grade = QLineEdit()
        self.exam = QLineEdit()
        self.textbook = QLineEdit()
        self.target_date = QDateEdit()
        self.target_date.setCalendarPopup(True)
        self.target_date.setDate(date.today())
        self.target_score = QSpinBox()
        self.target_score.setRange(0, 1000)
        self.progress = QSpinBox()
        self.progress.setRange(0, 100)
        self.progress.setSuffix("%")
        self.description = QTextEdit()
        self.description.setMaximumHeight(90)
        form.addRow("课程名称 *", self.name)
        form.addRow("学习阶段", self.stage)
        form.addRow("学科", self.subject)
        form.addRow("年级", self.grade)
        form.addRow("考试类型", self.exam)
        form.addRow("教材版本", self.textbook)
        form.addRow("目标日期", self.target_date)
        form.addRow("目标分数", self.target_score)
        form.addRow("当前进度", self.progress)
        form.addRow("说明", self.description)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if course:
            self.name.setText(course.name)
            self.stage.setCurrentText(course.education_stage)
            self.subject.setText(course.subject)
            self.grade.setText(course.grade_level)
            self.exam.setText(course.exam_type)
            self.textbook.setText(course.textbook_version)
            if course.target_date:
                self.target_date.setDate(course.target_date)
            self.target_score.setValue(int(course.target_score or 0))
            self.progress.setValue(course.progress)
            self.description.setPlainText(course.description)


class CoursesPage(QWidget):
    def __init__(self, service: LearningService) -> None:
        super().__init__()
        self.service = service
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addLayout(page_title("我的课程", "集中管理课程目标、进度和学习内容"))
        toolbar = QHBoxLayout()
        create = QPushButton("新建课程")
        create.setProperty("primary", True)
        create.clicked.connect(self.create_course)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索课程或学科")
        self.search.textChanged.connect(self.refresh)
        self.stage_filter = QComboBox()
        self.stage_filter.addItems(["全部阶段", "小学", "初中", "高中", "大学", "职业考试", "其他"])
        self.stage_filter.currentTextChanged.connect(self.refresh)
        self.subject_filter = QComboBox()
        self.subject_filter.addItems(["全部学科", "数学", "语文", "英语", "物理", "化学", "计算机", "行测", "其他"])
        self.subject_filter.currentTextChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["进行中", "已归档"])
        self.status_filter.currentTextChanged.connect(self.refresh)
        self.view_mode = QComboBox()
        self.view_mode.addItems(["列表", "卡片"])
        self.view_mode.currentIndexChanged.connect(lambda index: self.views.setCurrentIndex(index))
        toolbar.addWidget(create)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.stage_filter)
        toolbar.addWidget(self.subject_filter)
        toolbar.addWidget(self.status_filter)
        toolbar.addWidget(self.view_mode)
        root.addLayout(toolbar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["课程", "阶段", "学科", "进度", "状态", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.details)
        self.card_container = QWidget()
        self.card_grid = QGridLayout(self.card_container)
        card_scroll = QScrollArea()
        card_scroll.setWidgetResizable(True)
        card_scroll.setWidget(self.card_container)
        self.views = QStackedWidget()
        self.views.addWidget(self.table)
        self.views.addWidget(card_scroll)
        root.addWidget(self.views)
        self.refresh()

    def refresh(self) -> None:
        stage = "" if self.stage_filter.currentText() == "全部阶段" else self.stage_filter.currentText()
        subject = "" if self.subject_filter.currentText() == "全部学科" else self.subject_filter.currentText()
        status = "active" if self.status_filter.currentText() == "进行中" else "archived"
        courses = self.service.list_courses(self.search.text(), status, stage, subject)
        self.table.setRowCount(len(courses))
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for row, course in enumerate(courses):
            self.table.setItem(row, 0, QTableWidgetItem(course.name))
            self.table.setItem(row, 1, QTableWidgetItem(course.education_stage))
            self.table.setItem(row, 2, QTableWidgetItem(course.subject))
            progress = QProgressBar()
            progress.setValue(course.progress)
            progress.setFormat(f"{course.progress}%")
            self.table.setCellWidget(row, 3, progress)
            self.table.setItem(row, 4, QTableWidgetItem("进行中" if course.status == "active" else "已归档"))
            operations = QWidget()
            buttons = QHBoxLayout(operations)
            buttons.setContentsMargins(0, 0, 0, 0)
            detail = QPushButton("详情")
            detail.clicked.connect(lambda _=False, course_id=course.id: self.show_details(course_id))
            edit = QPushButton("编辑")
            edit.clicked.connect(lambda _=False, course_id=course.id: self.edit_course(course_id))
            archive = QPushButton("归档")
            archive.setEnabled(course.status == "active")
            archive.clicked.connect(lambda _=False, course_id=course.id: self.archive(course_id))
            buttons.addWidget(detail)
            buttons.addWidget(edit)
            buttons.addWidget(archive)
            self.table.setCellWidget(row, 5, operations)
            card = QFrame()
            card.setProperty("card", True)
            card_layout = QVBoxLayout(card)
            card_title = QLabel(course.name)
            card_title.setStyleSheet("font-size: 16px; font-weight: 700;")
            card_layout.addWidget(card_title)
            card_layout.addWidget(QLabel(f"{course.education_stage} · {course.subject} · {course.exam_type or '自主学习'}"))
            card_progress = QProgressBar()
            card_progress.setValue(course.progress)
            card_progress.setFormat(f"{course.progress}%")
            card_layout.addWidget(card_progress)
            card_layout.addWidget(QLabel(
                f"目标日期：{course.target_date or '未设置'}\n最近更新：{course.updated_at:%Y-%m-%d}"
            ))
            card_actions = QHBoxLayout()
            open_button = QPushButton("打开")
            open_button.clicked.connect(lambda _=False, course_id=course.id: self.show_details(course_id))
            edit_button = QPushButton("编辑")
            edit_button.clicked.connect(lambda _=False, course_id=course.id: self.edit_course(course_id))
            card_actions.addWidget(open_button)
            card_actions.addWidget(edit_button)
            card_layout.addLayout(card_actions)
            self.card_grid.addWidget(card, row // 3, row % 3)

    def create_course(self) -> None:
        dialog = CourseDialog(self)
        if dialog.exec():
            try:
                self.service.create_course(
                    dialog.name.text(), dialog.stage.currentText(),
                    dialog.subject.text(), dialog.description.toPlainText(),
                    dialog.grade.text(), dialog.exam.text(), dialog.textbook.text(),
                    dialog.target_date.date().toPython(), float(dialog.target_score.value()) or None,
                    dialog.progress.value()
                )
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "无法保存", str(error))

    def archive(self, course_id: int) -> None:
        if QMessageBox.question(self, "归档课程", "归档后课程将从当前列表隐藏，确认继续？") == QMessageBox.Yes:
            self.service.archive_course(course_id)
            self.refresh()

    def details(self, _index: object | None = None) -> None:
        row = self.table.currentRow()
        stage = "" if self.stage_filter.currentText() == "全部阶段" else self.stage_filter.currentText()
        subject = "" if self.subject_filter.currentText() == "全部学科" else self.subject_filter.currentText()
        status = "active" if self.status_filter.currentText() == "进行中" else "archived"
        courses = self.service.list_courses(self.search.text(), status, stage, subject)
        if 0 <= row < len(courses):
            self.show_details(courses[row].id)

    def show_details(self, course_id: int) -> None:
        course = self.service.get_course(course_id)
        if not course:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(course.name)
        dialog.resize(700, 480)
        root = QVBoxLayout(dialog)
        heading = QLabel(course.name)
        heading.setProperty("title", True)
        root.addWidget(heading)
        root.addWidget(QLabel(
            f"{course.education_stage} · {course.grade_level or '未设置年级'} · {course.subject} · "
            f"目标日期 {course.target_date or '未设置'} · 进度 {course.progress}%"
        ))
        tabs = QTabWidget()
        tabs.addTab(QLabel(course.description or "暂无课程说明", wordWrap=True, alignment=Qt.AlignTop), "概览")
        tabs.addTab(QLabel("课程资料会在“学习资料”中按课程关联显示。", alignment=Qt.AlignCenter), "资料")
        tabs.addTab(QLabel("知识点掌握度会随练习记录更新。", alignment=Qt.AlignCenter), "知识点")
        tabs.addTab(QLabel("课程任务会在“学习计划”中显示。", alignment=Qt.AlignCenter), "任务")
        tabs.addTab(QLabel("练习记录会在完成本课程练习后显示。", alignment=Qt.AlignCenter), "练习记录")
        root.addWidget(tabs)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        root.addWidget(close)
        dialog.exec()

    def edit_course(self, course_id: int) -> None:
        course = self.service.get_course(course_id)
        if not course:
            return
        dialog = CourseDialog(self, course)
        if dialog.exec():
            try:
                self.service.update_course(
                    course_id, name=dialog.name.text(), education_stage=dialog.stage.currentText(),
                    subject=dialog.subject.text(), description=dialog.description.toPlainText(),
                    grade_level=dialog.grade.text(), exam_type=dialog.exam.text(),
                    textbook_version=dialog.textbook.text(),
                    target_date=dialog.target_date.date().toPython(),
                    target_score=float(dialog.target_score.value()) or None,
                    progress=dialog.progress.value(),
                )
                self.refresh()
            except ValueError as error:
                QMessageBox.warning(self, "无法保存", str(error))


