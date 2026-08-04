from __future__ import annotations

from collections.abc import Callable

from ai.factory import (
    create_grounded_qa_service,
    create_knowledge_extraction_service,
    create_knowledge_point_index,
    create_learning_report_service,
    create_question_generation_service,
    create_resource_indexing_pipeline,
    create_subjective_grading_service,
    create_error_analysis_service,
    create_plan_generation_service,
)
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from app.core.config import AppSettings
from app.services.learning import LearningService
from app.services.domain import (
    AnalyticsService, JobService, MaintenanceService, QuestionService, ResourceService, ReviewService,
)
from app.ui.admin_pages import JobsPage, LogsPage
from app.ui.advanced_pages import AnalyticsPage, PracticePage, ResourcesPage, ReviewPage, ToolsPage
from app.ui.pages import CoursesPage, DashboardPage, PlanPage, SettingsPage
from app.ui.icons import IconProvider
from app.tools.registry import ToolRegistry
from app.ui.styles.theme import DARK, LIGHT


class MainWindow(QMainWindow):
    def __init__(self, service: LearningService, config: AppSettings) -> None:
        super().__init__()
        self.service = service
        self.config = config
        self.preferences = QSettings(config.organization, config.app_name)
        self.setWindowTitle(config.app_name)
        self.setMinimumSize(1100, 700)
        self.resize(self.preferences.value("size", QSize(1440, 900)))
        self._nav_buttons: list[QPushButton] = []
        self.resources = ResourceService(service.database, config)
        self.questions = QuestionService(service.database)
        self.reviews = ReviewService(service.database)
        self.analytics = AnalyticsService(service.database)
        self.maintenance = MaintenanceService(service.database, config)
        self.tool_registry = ToolRegistry(service.database, config)
        self.jobs = JobService(service.database)
        self.jobs.recover_interrupted()
        self._build_ui()
        geometry = self.preferences.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            if not any(self.frameGeometry().intersects(screen.availableGeometry()) for screen in QApplication.screens()):
                self.move(QApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        self.sidebar.setVisible(not self.preferences.value("nav_collapsed", False, type=bool))
        self.apply_theme(str(self.preferences.value("theme", "light")))
        last_page = int(self.preferences.value("page", 0))
        self.navigate(max(0, min(last_page, self.stack.count() - 1)))

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        nav = QVBoxLayout(self.sidebar)
        nav.setContentsMargins(14, 18, 14, 16)
        brand = QLabel("个性化学习助手")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        mode = QLabel("● 本地模式")
        mode.setProperty("muted", True)
        nav.addWidget(mode)
        nav.addSpacing(16)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top_layout = QHBoxLayout(topbar)
        self.search = QLineEdit()
        self.search.setPlaceholderText("全局搜索（Ctrl+K）")
        self.search.setMaximumWidth(420)
        self.search.returnPressed.connect(self.run_search)
        top_layout.addWidget(QLabel("当前课程"))
        self.current_course = QComboBox()
        self.current_course.addItem("全部课程", None)
        for course in self.service.list_courses():
            self.current_course.addItem(course.name, course.id)
        saved_course = self.preferences.value("current_course_id")
        if saved_course is not None:
            index = self.current_course.findData(int(saved_course))
            self.current_course.setCurrentIndex(max(0, index))
        self.current_course.currentIndexChanged.connect(
            lambda _: self.preferences.setValue("current_course_id", self.current_course.currentData())
        )
        top_layout.addWidget(self.current_course)
        nav_toggle = QPushButton("导航")
        nav_toggle.setIcon(IconProvider.get("navigation"))
        nav_toggle.setToolTip("显示或隐藏左侧导航")
        nav_toggle.clicked.connect(self.toggle_navigation)
        top_layout.addWidget(nav_toggle)
        top_layout.addStretch()
        top_layout.addWidget(self.search)
        notifications = QPushButton("通知")
        notifications.setIcon(IconProvider.get("notification"))
        notifications.setToolTip("查看到期复习和后台任务")
        notifications.clicked.connect(self.show_notifications)
        top_layout.addWidget(notifications)
        theme = QPushButton("切换主题")
        theme.setIcon(IconProvider.get("settings"))
        theme.setToolTip("在浅色与深色主题之间切换")
        theme.clicked.connect(self.toggle_theme)
        top_layout.addWidget(theme)
        content_layout.addWidget(topbar)
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self.resources_page = ResourcesPage(
            self.resources,
            self.jobs,
            indexing_factory=lambda: create_resource_indexing_pipeline(
                database=self.service.database,
                app_settings=self.config,
            ),
            qa_factory=lambda: create_grounded_qa_service(
                database=self.service.database,
                app_settings=self.config,
            ),
            extraction_factory=lambda: create_knowledge_extraction_service(
                database=self.service.database,
                app_settings=self.config,
            ),
        )
        self.resources_page.jobs_changed.connect(self.update_status)
        practice_page = PracticePage(
            self.questions,
            resources=self.resources,
            jobs=self.jobs,
            extraction_factory=lambda: create_knowledge_extraction_service(
                database=self.service.database,
                app_settings=self.config,
            ),
            knowledge_index_factory=lambda: create_knowledge_point_index(
                database=self.service.database,
                app_settings=self.config,
            ),
            question_generation_factory=lambda: create_question_generation_service(
                database=self.service.database,
                app_settings=self.config,
            ),
            grading_factory=lambda: create_subjective_grading_service(
                database=self.service.database,
                app_settings=self.config,
            ),
            analysis_factory=lambda: create_error_analysis_service(
                database=self.service.database,
                app_settings=self.config,
            ),
        )
        if practice_page.knowledge_extraction_widget is not None:
            practice_page.knowledge_extraction_widget.jobs_changed.connect(
                self.update_status
            )
        if practice_page.question_generation_widget is not None:
            practice_page.question_generation_widget.jobs_changed.connect(
                self.update_status
            )
        jobs_page = JobsPage(self.jobs)
        jobs_page.retry_requested.connect(self.retry_job)
        analytics_page = AnalyticsPage(
            self.analytics,
            jobs=self.jobs,
            report_factory=lambda: create_learning_report_service(
                database=self.service.database,
                app_settings=self.config,
            ),
        )
        analytics_page.jobs_changed.connect(self.update_status)
        pages: list[tuple[str, QWidget]] = [
            ("首页", DashboardPage(self.service)),
            ("我的课程", CoursesPage(self.service)),
            ("学习资料", self.resources_page),
            ("学习计划", PlanPage(
                self.service,
                jobs=self.jobs,
                plan_factory=lambda: create_plan_generation_service(
                    database=self.service.database,
                    app_settings=self.config,
                ),
            )),
            ("练习中心", practice_page),
            ("错题与复习", ReviewPage(self.reviews)),
            ("学习分析", analytics_page),
            ("工具中心", ToolsPage(self.tool_registry)),
            ("后台任务", jobs_page),
            ("日志查看器", LogsPage(self.config.log_dir / "app.log")),
            ("系统设置", SettingsPage(self.config, self.maintenance, self.service)),
        ]
        for index, (name, page) in enumerate(pages):
            self.stack.addWidget(page)
            button = QPushButton(name)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda _=False, i=index: self.navigate(i))
            nav.addWidget(button)
            self._nav_buttons.append(button)
        nav.addStretch()
        nav.addWidget(QLabel(f"v{self.config.version}  ·  数据库已连接"))
        outer.addWidget(self.sidebar)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)
        settings_page = pages[-1][1]
        assert isinstance(settings_page, SettingsPage)
        settings_page.theme_changed.connect(self.apply_theme)
        shortcut = QAction(self)
        shortcut.setShortcut(QKeySequence("Ctrl+K"))
        shortcut.triggered.connect(self.focus_search)
        self.addAction(shortcut)
        self.update_status()

    def focus_search(self) -> None:
        dialog = CommandPalette(self)
        dialog.exec()

    def run_search(self) -> None:
        results = self.maintenance.search(self.search.text())
        if not results:
            QMessageBox.information(self, "全局搜索", "没有找到匹配的课程、任务、题目或资料。")
            return
        text = "\n".join(f"[{item['type']}] {item['title']}" for item in results)
        QMessageBox.information(self, f"搜索结果（{len(results)}）", text)

    def update_status(self) -> None:
        active = sum(1 for job in self.jobs.list() if job.status in {"queued", "running"})
        self.statusBar().showMessage(
            f"数据库：正常  |  后台任务：{active}  |  v{self.config.version}  |  本地模式"
        )

    def show_notifications(self) -> None:
        stats = self.service.dashboard()["stats"]
        active = sum(1 for job in self.jobs.list() if job.status in {"queued", "running"})
        QMessageBox.information(
            self, "通知", f"到期复习：{stats['due']} 项\n正在处理的后台任务：{active} 项"
        )

    def retry_job(self, job_id: int) -> None:
        from pathlib import Path

        try:
            old = self.jobs.get(job_id)
            if not old:
                return
            retry = self.jobs.retry(job_id)
            path = Path(old.payload)
            self.resources_page._start_import(path, old.job_type == "directory_import", retry.id)
            self.update_status()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法重试", str(error))

    def execute_command(self, command: str) -> None:
        if command == "new_course":
            self.navigate(1)
            page = self.stack.currentWidget()
            getattr(page, "create_course")()
        elif command == "add_file":
            self.navigate(2)
            getattr(self.stack.currentWidget(), "import_file")()
        elif command == "new_task":
            self.navigate(3)
        elif command == "start_study":
            self.navigate(0)
            getattr(self.stack.currentWidget(), "start_study")()
        elif command == "open_review":
            self.navigate(5)
        elif command == "toggle_theme":
            self.toggle_theme()
        elif command == "backup":
            self.navigate(10)
            getattr(self.stack.currentWidget(), "backup")()
        elif command == "open_logs":
            self.navigate(9)

    def navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def toggle_theme(self) -> None:
        current = str(self.preferences.value("theme", "light"))
        self.apply_theme("dark" if current == "light" else "light")

    def toggle_navigation(self) -> None:
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self.preferences.setValue("nav_collapsed", not visible)

    def apply_theme(self, theme: str) -> None:
        QApplication.instance().setStyleSheet(DARK if theme == "dark" else LIGHT)
        self.preferences.setValue("theme", theme)

    def closeEvent(self, event: QCloseEvent) -> None:
        for job in self.jobs.list():
            if job.status in {"queued", "running"}:
                self.jobs.cancel(job.id)
        self.resources_page.pool.clear()
        self.resources_page.pool.waitForDone(3000)
        self.preferences.setValue("size", self.size())
        self.preferences.setValue("geometry", self.saveGeometry())
        self.preferences.setValue("page", self.stack.currentIndex())
        self.service.database.close()
        super().closeEvent(event)


class CommandPalette(QDialog):
    COMMANDS = [
        ("新建课程", "new_course"), ("添加学习资料", "add_file"),
        ("新建学习任务", "new_task"), ("开始今日学习", "start_study"),
        ("打开到期复习", "open_review"), ("切换主题", "toggle_theme"),
        ("创建完整备份", "backup"), ("打开日志查看器", "open_logs"),
    ]

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("搜索与命令")
        self.resize(680, 460)
        root = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索课程、任务、题目、资料，或输入命令名称")
        self.results = QListWidget()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(lambda: self.refresh(self.query.text()))
        self.query.textChanged.connect(lambda _: self.timer.start())
        self.query.returnPressed.connect(self.activate_current)
        self.results.itemActivated.connect(lambda _: self.activate_current())
        root.addWidget(self.query)
        root.addWidget(self.results)
        root.addWidget(QLabel("↑↓ 选择 · Enter 打开 · Esc 关闭"))
        self.refresh("")
        self.query.setFocus()

    def refresh(self, text: str) -> None:
        self.results.clear()
        lowered = text.strip().casefold()
        commands = [item for item in self.COMMANDS if not lowered or lowered in item[0].casefold()]
        if commands:
            header = QListWidgetItem("— 命令 —")
            header.setFlags(Qt.NoItemFlags)
            self.results.addItem(header)
            for title, command in commands:
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, ("command", command))
                self.results.addItem(item)
        if not text.strip():
            recent = self.window.preferences.value("recent_searches", [], type=list)
            if recent:
                header = QListWidgetItem("— 最近搜索 —")
                header.setFlags(Qt.NoItemFlags)
                self.results.addItem(header)
                for query in recent[:8]:
                    item = QListWidgetItem(str(query))
                    item.setData(Qt.UserRole, ("recent", str(query)))
                    self.results.addItem(item)
        if text.strip():
            matches = self.window.maintenance.search(text)
            if matches:
                header = QListWidgetItem("— 搜索结果 —")
                header.setFlags(Qt.NoItemFlags)
                self.results.addItem(header)
                for result in matches:
                    item = QListWidgetItem(f"[{result['type']}] {result['title']}")
                    item.setData(Qt.UserRole, ("result", result))
                    self.results.addItem(item)
        for index in range(self.results.count()):
            if self.results.item(index).flags() & Qt.ItemIsEnabled:
                self.results.setCurrentRow(index)
                break

    def activate_current(self) -> None:
        item = self.results.currentItem()
        if not item:
            return
        payload = item.data(Qt.UserRole)
        if not payload:
            return
        kind, value = payload
        if kind == "recent":
            self.query.setText(value)
            self.query.selectAll()
            self.refresh(value)
            return
        self.accept()
        if kind == "command":
            self.window.execute_command(value)
            return
        recent = [self.query.text().strip()] + self.window.preferences.value(
            "recent_searches", [], type=list
        )
        self.window.preferences.setValue(
            "recent_searches", list(dict.fromkeys(item for item in recent if item))[:8]
        )
        page_by_type = {"课程": 1, "任务": 3, "题目": 4, "资料": 2}
        self.window.navigate(page_by_type.get(value["type"], 0))
