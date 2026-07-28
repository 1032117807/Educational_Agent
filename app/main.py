from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.bootstrap import bootstrap
from app.services.domain import ResourceService
from app.ui.main_window import MainWindow


def exception_hook(exc_type: type[BaseException], value: BaseException, tb: object) -> None:
    logging.getLogger(__name__).critical("未处理异常", exc_info=(exc_type, value, tb))
    QMessageBox.critical(None, "应用错误", f"发生未处理错误：\n{value}")


def release_smoke_test() -> int:
    """Exercise bundled persistence without requiring GUI automation."""
    service, config = bootstrap()
    courses = service.list_courses()
    course = next((item for item in courses if item.name == "发布冒烟课程"), None)
    if course is None:
        course = service.create_course("发布冒烟课程", "自测", "通用")
        source = config.data_dir / "release-smoke.txt"
        source.write_text("个性化学习助手发布冒烟测试", encoding="utf-8")
        ResourceService(service.database, config).import_file(source, course.id)
        service.create_task("发布冒烟任务", 15, course_id=course.id)
    resources = ResourceService(service.database, config).list_files()
    tasks = service.list_today_tasks()
    valid = (
        any(item.name == "发布冒烟课程" for item in service.list_courses())
        and any(item.name == "release-smoke.txt" for item in resources)
        and any(item.title == "发布冒烟任务" for item in tasks)
    )
    service.database.close()
    if not valid:
        logging.getLogger(__name__).error("发布冒烟数据验证失败")
        return 1
    print("release smoke test passed")
    return 0


def main() -> int:
    if "--smoke-test" in sys.argv:
        return release_smoke_test()
    app = QApplication(sys.argv)
    app.setApplicationName("个性化学习助手")
    icon_path = Path(__file__).resolve().parent / "resources" / "app_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    # 某些隔离环境不会自动枚举 Windows 中文字体；显式加载可避免中文方框。
    if sys.platform == "win32":
        windows_dir = Path(os.environ.get("WINDIR", ""))
        for font_name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"):
            font_path = windows_dir / "Fonts" / font_name
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
                break
    sys.excepthook = exception_hook
    service, config = bootstrap()
    window = MainWindow(service, config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
