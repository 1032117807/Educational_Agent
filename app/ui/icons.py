from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle


class IconProvider:
    """集中提供 Qt 原生图标，避免页面自行使用 emoji 或平台路径。"""

    _MAP = {
        "search": QStyle.SP_FileDialogContentsView,
        "settings": QStyle.SP_FileDialogDetailedView,
        "notification": QStyle.SP_MessageBoxInformation,
        "navigation": QStyle.SP_ArrowRight,
        "folder": QStyle.SP_DirIcon,
        "file": QStyle.SP_FileIcon,
        "save": QStyle.SP_DialogSaveButton,
        "delete": QStyle.SP_TrashIcon,
        "refresh": QStyle.SP_BrowserReload,
    }

    @classmethod
    def get(cls, name: str) -> QIcon:
        style = QApplication.style()
        return style.standardIcon(cls._MAP.get(name, QStyle.SP_FileIcon))
