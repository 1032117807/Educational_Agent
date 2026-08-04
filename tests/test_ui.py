from app.core.config import AppSettings
from app.database import Database
from app.services.learning import LearningService
from app.ui.main_window import CommandPalette, MainWindow


def test_main_window_and_navigation(qtbot, tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    window = MainWindow(LearningService(database), config)
    qtbot.addWidget(window)
    assert window.stack.count() == 12
    assert window.resources_page.tabs.count() == 2
    assert window.resources_page.tabs.tabText(1) == "资料问答"
    practice_page = window.stack.widget(4)
    assert practice_page.tabs.count() == 4
    assert practice_page.tabs.tabText(3) == "AI 出题"
    analytics_page = window.stack.widget(6)
    assert analytics_page.tabs.tabText(6) == "AI 报告"
    assert window.stack.widget(7).windowTitle() == ""
    window.navigate(3)
    assert window.stack.currentIndex() == 3


def test_command_palette_searches_and_navigates(qtbot, tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    service = LearningService(database)
    service.create_course("离散数学", "大学", "数学")
    window = MainWindow(service, config)
    qtbot.addWidget(window)
    palette = CommandPalette(window)
    qtbot.addWidget(palette)
    palette.query.setText("离散")
    qtbot.wait(300)
    assert any("离散数学" in palette.results.item(index).text() for index in range(palette.results.count()))
    for index in range(palette.results.count()):
        if "离散数学" in palette.results.item(index).text():
            palette.results.setCurrentRow(index)
            break
    palette.activate_current()
    assert window.stack.currentIndex() == 1
