from __future__ import annotations

from collections.abc import Callable

from ai.factory import (
    create_grounded_qa_service,
    create_knowledge_extraction_service,
    create_knowledge_point_index,
    create_learning_report_service,
    create_learning_plan_agent_service,
    create_question_generation_service,
    create_resource_indexing_pipeline,
    create_subjective_grading_service,
    create_error_analysis_service,
    create_plan_generation_service,
)
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget, QTabWidget,
)

from app.core.config import AppSettings
from app.services.learning import LearningService
from app.services.agent_sessions import AgentSessionService
from app.services.agent_workflows import AgentWorkflowService
from app.services.agent_skills import AgentSkillCatalog
from app.services.agent_memory import AgentMemoryService
from app.services.domain import (
    AnalyticsService, JobService, MaintenanceService, QuestionService, ResourceService, ReviewService,
)
from app.ui.admin_pages import JobsPage, LogsPage
from app.ui.advanced_pages import AnalyticsPage, PracticePage, ResourcesPage, ReviewPage, ToolsPage
from app.ui.pages import CoursesPage, DashboardPage, PlanPage, SettingsPage
from app.ui.icons import IconProvider
from app.tools.registry import ToolRegistry
from app.ui.styles.theme import DARK, LIGHT, TOKENS
from app.ui.learning_agent_page import LearningAgentPage


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
        self._nav_button_labels: list[str] = []
        self._agent_session_count = 1
        self.resources = ResourceService(service.database, config)
        self.questions = QuestionService(service.database)
        self.reviews = ReviewService(service.database)
        self.analytics = AnalyticsService(service.database)
        self.maintenance = MaintenanceService(service.database, config)
        self.tool_registry = ToolRegistry(service.database, config)
        self.agent_sessions = AgentSessionService(service.database)
        self.agent_skills = AgentSkillCatalog(
            state_path=config.data_dir / "agent_skills.json"
        )
        self.agent_memory = AgentMemoryService(service.database)
        self.jobs = JobService(service.database)
        self.jobs.recover_interrupted()
        self._build_ui()
        geometry = self.preferences.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            if not any(self.frameGeometry().intersects(screen.availableGeometry()) for screen in QApplication.screens()):
                self.move(QApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        self.set_navigation_compact(
            self.preferences.value("nav_collapsed", False, type=bool)
        )
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
        self.sidebar.setFixedWidth(TOKENS["sidebar_expanded"])
        nav = QVBoxLayout(self.sidebar)
        self._nav_layout = nav
        nav.setContentsMargins(14, 18, 14, 16)
        brand = QLabel("个性化学习助手")
        brand.setObjectName("brand")
        self.brand = brand
        nav.addWidget(brand)
        mode = QLabel("● 本地模式")
        mode.setProperty("muted", True)
        self.mode = mode
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
        sessions_button = QPushButton("会话")
        sessions_button.setToolTip("搜索、归档或恢复 Agent 会话")
        sessions_button.clicked.connect(self.manage_agent_sessions)
        top_layout.addWidget(sessions_button)
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
        sessions = self.agent_sessions.list_sessions()
        if not sessions:
            sessions = [self.agent_sessions.create_session("Agent 1")]
        primary_session = sessions[0]
        agent_page = LearningAgentPage(
            jobs=self.jobs,
            agent_factory=lambda: create_learning_plan_agent_service(
                database=self.service.database,
                app_settings=self.config,
                tool_registry=self.tool_registry,
                skill_catalog=self.agent_skills,
            ),
            session_service=self.agent_sessions,
            session_id=primary_session.id,
            skill_catalog=self.agent_skills,
            memory_service=self.agent_memory,
            workflow_factory=lambda: AgentWorkflowService(
                database=self.service.database,
                indexing_factory=lambda: create_resource_indexing_pipeline(
                    database=self.service.database, app_settings=self.config
                ),
                extraction_factory=lambda: create_knowledge_extraction_service(
                    database=self.service.database, app_settings=self.config
                ),
                question_factory=lambda: create_question_generation_service(
                    database=self.service.database, app_settings=self.config
                ),
                report_factory=lambda: create_learning_report_service(
                    database=self.service.database, app_settings=self.config
                ),
            ),
        )
        agent_page.navigate_requested.connect(
            lambda route: self._route_from_agent(route, agent_page, practice_page, analytics_page)
        )
        agent_page.practice_requested.connect(
            lambda question_ids: self._open_agent_practice(agent_page, practice_page, question_ids)
        )
        agent_page.workflow_practice_requested.connect(
            lambda workflow_id, question_ids: self._open_workflow_practice(
                agent_page, workflow_id, practice_page, question_ids
            )
        )
        agent_page.new_window_requested.connect(
            lambda: self._open_agent_window(practice_page, analytics_page)
        )
        agent_page.session_title_changed.connect(self._update_agent_session_title)
        agent_page.knowledge_review_requested.connect(
            lambda course_id: self._open_knowledge_drafts(practice_page, course_id)
        )
        self.agent_tabs = QTabWidget()
        self.agent_tabs.setDocumentMode(True)
        self.agent_tabs.setTabsClosable(True)
        self.agent_tabs.tabCloseRequested.connect(self.close_agent_tab)
        new_tab_button = QPushButton("+")
        new_tab_button.setToolTip("新建 Agent 会话")
        new_tab_button.clicked.connect(
            lambda: self._open_agent_window(practice_page, analytics_page)
        )
        self.agent_tabs.setCornerWidget(new_tab_button, Qt.TopRightCorner)
        self.agent_tabs.addTab(agent_page, primary_session.title)
        self.resources_page.knowledge_drafts_ready.connect(
            lambda course_id: self._open_knowledge_drafts(practice_page, course_id)
        )
        practice_page.report_requested.connect(
            lambda: self._open_today_report(analytics_page)
        )
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
            ("AI 中心", self.agent_tabs),
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
            button.setIcon(IconProvider.get("folder"))
            button.setToolTip(name)
            button.clicked.connect(lambda _=False, i=index: self.navigate(i))
            nav.addWidget(button)
            self._nav_buttons.append(button)
            self._nav_button_labels.append(name)
        for session in sessions[1:]:
            self._open_agent_session(session.id, session.title, practice_page, analytics_page)
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

    def manage_agent_sessions(self) -> None:
        """提供会话检索、归档和恢复，不直接删除学习记录。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Agent 会话管理")
        dialog.resize(520, 420)
        layout = QVBoxLayout(dialog)
        query = QLineEdit()
        query.setPlaceholderText("搜索会话")
        include_archived = QCheckBox("显示已归档会话")
        sessions = QListWidget()
        archive_button = QPushButton("归档")
        restore_button = QPushButton("恢复")
        close_button = QPushButton("关闭")

        def refresh() -> None:
            sessions.clear()
            for item in self.agent_sessions.search_sessions(
                query.text(), include_archived=include_archived.isChecked()
            ):
                label = f"[已归档] {item.title}" if item.archived else item.title
                row = QListWidgetItem(label)
                row.setData(Qt.UserRole, {"id": item.id, "archived": item.archived})
                sessions.addItem(row)

        def selected() -> dict | None:
            item = sessions.currentItem()
            return item.data(Qt.UserRole) if item else None

        def archive() -> None:
            value = selected()
            if value and not value["archived"]:
                self.agent_sessions.archive(value["id"])
                refresh()

        def restore() -> None:
            value = selected()
            if value and value["archived"]:
                self.agent_sessions.restore(value["id"])
                refresh()

        query.textChanged.connect(refresh)
        include_archived.toggled.connect(refresh)
        archive_button.clicked.connect(archive)
        restore_button.clicked.connect(restore)
        close_button.clicked.connect(dialog.accept)
        actions = QHBoxLayout()
        actions.addWidget(archive_button)
        actions.addWidget(restore_button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addWidget(query)
        layout.addWidget(include_archived)
        layout.addWidget(sessions, 1)
        layout.addLayout(actions)
        refresh()
        dialog.exec()

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
            self.navigate(11)
            getattr(self.stack.currentWidget(), "backup")()
        elif command == "open_logs":
            self.navigate(10)

    def navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _open_knowledge_drafts(self, practice_page: PracticePage, course_id: int) -> None:
        self.navigate(4)
        practice_page.show_pending_knowledge_drafts(course_id)

    def _open_today_report(self, analytics_page: AnalyticsPage) -> None:
        self.navigate(6)
        analytics_page.open_today_report()

    def _route_from_agent(
        self,
        route: str,
        agent_page: LearningAgentPage,
        practice_page: PracticePage,
        analytics_page: AnalyticsPage,
    ) -> None:
        routes = {
            "resources": 2,
            "practice": 4,
            "plan": 3,
            "analytics": 6,
            "review": 5,
            "courses": 1,
            "agent": 7,
        }
        index = routes.get(route)
        if index is None:
            return
        self.navigate(index)
        if route == "resources":
            self.resources_page.tabs.setCurrentIndex(1)
        elif route == "practice":
            practice_page.tabs.setCurrentIndex(3)
        elif route == "analytics":
            analytics_page.open_today_report()

    def _open_agent_practice(
        self, agent_page: LearningAgentPage, practice_page: PracticePage,
        question_ids: list[int] | tuple[int, ...]
    ) -> None:
        self.navigate(4)
        practice_page.tabs.setCurrentIndex(0)
        if practice_page.start_practice_for_questions(question_ids):
            agent_page.generate_report_after_practice()

    def _open_workflow_practice(
        self, agent_page: LearningAgentPage, workflow_id: int,
        practice_page: PracticePage, question_ids: list[int] | tuple[int, ...],
    ) -> None:
        self.navigate(4)
        practice_page.tabs.setCurrentIndex(0)
        if practice_page.start_practice_for_questions(question_ids):
            agent_page.finish_workflow_practice(workflow_id)

    def _open_agent_window(
        self, practice_page: PracticePage, analytics_page: AnalyticsPage
    ) -> None:
        session = self.agent_sessions.create_session(f"Agent {self._agent_session_count + 1}")
        self._open_agent_session(session.id, session.title, practice_page, analytics_page, activate=True)

    def _open_agent_session(
        self, session_id: int, title: str, practice_page: PracticePage,
        analytics_page: AnalyticsPage, *, activate: bool = False,
    ) -> None:
        page = LearningAgentPage(
            jobs=self.jobs,
            agent_factory=lambda: create_learning_plan_agent_service(
                database=self.service.database,
                app_settings=self.config,
                tool_registry=self.tool_registry,
                skill_catalog=self.agent_skills,
            ),
            session_service=self.agent_sessions,
            session_id=session_id,
            skill_catalog=self.agent_skills,
            memory_service=self.agent_memory,
            workflow_factory=lambda: AgentWorkflowService(
                database=self.service.database,
                indexing_factory=lambda: create_resource_indexing_pipeline(
                    database=self.service.database, app_settings=self.config
                ),
                extraction_factory=lambda: create_knowledge_extraction_service(
                    database=self.service.database, app_settings=self.config
                ),
                question_factory=lambda: create_question_generation_service(
                    database=self.service.database, app_settings=self.config
                ),
                report_factory=lambda: create_learning_report_service(
                    database=self.service.database, app_settings=self.config
                ),
            ),
        )
        page.navigate_requested.connect(
            lambda route: self._route_from_agent(route, page, practice_page, analytics_page)
        )
        page.practice_requested.connect(
            lambda question_ids: self._open_agent_practice(page, practice_page, question_ids)
        )
        page.workflow_practice_requested.connect(
            lambda workflow_id, question_ids: self._open_workflow_practice(
                page, workflow_id, practice_page, question_ids
            )
        )
        page.knowledge_review_requested.connect(
            lambda course_id: self._open_knowledge_drafts(practice_page, course_id)
        )
        page.new_window_requested.connect(
            lambda: self._open_agent_window(practice_page, analytics_page)
        )
        page.session_title_changed.connect(self._update_agent_session_title)
        self._agent_session_count += 1
        index = self.agent_tabs.addTab(page, title)
        if activate:
            self.navigate(7)
            self.agent_tabs.setCurrentIndex(index)

    def _update_agent_session_title(self, session_id: int, title: str) -> None:
        for index in range(self.agent_tabs.count()):
            page = self.agent_tabs.widget(index)
            if isinstance(page, LearningAgentPage) and page.session_id == session_id:
                self.agent_tabs.setTabText(index, title)
                return

    def close_agent_tab(self, index: int) -> None:
        """关闭会话视图但保留持久化记录，便于下次恢复。"""
        if self.agent_tabs.count() == 1:
            return
        page = self.agent_tabs.widget(index)
        self.agent_tabs.removeTab(index)
        page.deleteLater()

    def toggle_theme(self) -> None:
        current = str(self.preferences.value("theme", "light"))
        self.apply_theme("dark" if current == "light" else "light")

    def toggle_navigation(self) -> None:
        self.set_navigation_compact(not bool(self.sidebar.property("compact")))

    def set_navigation_compact(self, compact: bool) -> None:
        """在完整导航与保留入口的图标紧凑模式之间切换。"""
        self.sidebar.setProperty("compact", compact)
        self.sidebar.setFixedWidth(
            TOKENS["sidebar_compact"] if compact else TOKENS["sidebar_expanded"]
        )
        self.brand.setVisible(not compact)
        self.mode.setVisible(not compact)
        for button, label in zip(self._nav_buttons, self._nav_button_labels):
            button.setText("" if compact else label)
            button.setToolTip(label)
        self.preferences.setValue("nav_collapsed", compact)

    def apply_theme(self, theme: str) -> None:
        QApplication.instance().setStyleSheet(DARK if theme == "dark" else LIGHT)
        self.preferences.setValue("theme", theme)

    def closeEvent(self, event: QCloseEvent) -> None:
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if isinstance(page, LearningAgentPage):
                page.prepare_for_shutdown()
                page.pool.waitForDone(3000)
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
