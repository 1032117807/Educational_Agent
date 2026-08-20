from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

# The managed Windows environment may block unsigned PyTorch DLLs. Optional
# tokenizer integrations must not auto-import torch while the GUI is starting.
# Features that explicitly need the local embedding backend report their own
# actionable error instead.
os.environ.setdefault("USE_TORCH", "0")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

_QT_PLUGIN_ROOT: Path | None = None
if sys.platform == "win32":
    pyside_root = (
        Path(sys.prefix)
        / "Lib"
        / "site-packages"
        / "PySide6"
    )
    process_path = pyside_root / "QtWebEngineProcess.exe"
    if process_path.is_file():
        # Conda's Qt lookup can miss PySide's bundled WebEngine subprocess.
        # This must be set before importing any PySide6 module.
        os.environ.setdefault("QTWEBENGINEPROCESS_PATH", str(process_path))
    webengine_resources = pyside_root / "resources"
    if (webengine_resources / "qtwebengine_resources.pak").is_file():
        # PySide wheels keep Chromium resources beside the bindings, while
        # Conda's Qt runtime first looks under Library/share/qt6.
        os.environ.setdefault("QTWEBENGINE_RESOURCES_PATH", str(webengine_resources))
    candidate = pyside_root / "plugins"
    if (candidate / "platforms" / "qwindows.dll").is_file():
        _QT_PLUGIN_ROOT = candidate
        os.environ["QT_PLUGIN_PATH"] = str(candidate)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(
            candidate / "platforms"
        )

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.bootstrap import bootstrap
from app.services.domain import ResourceService
from app.services.desktop_companion import DesktopCompanion
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
    if _QT_PLUGIN_ROOT is not None:
        QCoreApplication.setLibraryPaths([str(_QT_PLUGIN_ROOT)])
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
    companion = DesktopCompanion(
        api_url=config.saas_api_url, access_token=config.saas_access_token,
        refresh_token=config.saas_refresh_token, companion_id=config.desktop_companion_id,
        token_store=config.data_dir / "desktop_companion_auth.json",
    )
    companion.start()
    app.aboutToQuit.connect(companion.stop)
    window = MainWindow(service, config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
