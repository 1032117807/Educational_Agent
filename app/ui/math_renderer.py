from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QEvent, QUrl
from PySide6.QtWidgets import QHBoxLayout, QLabel, QRadioButton, QCheckBox, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # Allows a packaged minimal Qt build to keep the practice page usable.
    QWebEngineView = None


_ASSET_DIR = Path(__file__).parent / "assets" / "mathjax"
_MATHJAX_FILE = _ASSET_DIR / "tex-mml-chtml.js"


def _body(text: str) -> str:
    value = escape(text.replace("\\n", "\n"))
    return value.replace("\n", "<br>")


class MathTextView(QWidget):
    """Renders user-provided text plus LaTeX delimiters with local MathJax."""

    def __init__(self, fallback: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fallback = QLabel(self)
        self.fallback.setWordWrap(True)
        self.fallback.setText(fallback)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if QWebEngineView is not None and _MATHJAX_FILE.exists():
            self.browser = QWebEngineView(self)
            self.browser.setMinimumHeight(54)
            layout.addWidget(self.browser)
            self.fallback.hide()
        else:
            self.browser = None
            layout.addWidget(self.fallback)

    def set_math_text(self, text: str) -> None:
        self.fallback.setText(text)
        if self.browser is None:
            return
        html = f"""<!doctype html><html><head><meta charset='utf-8'>
<script>window.MathJax={{tex:{{inlineMath:[['\\\\(','\\\\)'],['$','$']],displayMath:[['\\\\[','\\\\]'],['$$','$$']]}},options:{{skipHtmlTags:['script','noscript','style','textarea','pre','code']}}}};</script>
<script src='tex-mml-chtml.js'></script>
<style>html,body{{margin:0;padding:0;background:transparent;color:#182230;font:16px "Microsoft YaHei",sans-serif;line-height:1.55}} .MathJax{{font-size:1.08em}}</style>
</head><body>{_body(text)}</body></html>"""
        self.browser.setHtml(html, QUrl.fromLocalFile(str(_ASSET_DIR) + "/"))


class MathChoice(QWidget):
    """Selectable option with a MathJax label; clicking formula text selects it too."""

    def __init__(
        self, text: str, *, multiple: bool, fallback_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.control = QCheckBox(self) if multiple else QRadioButton(self)
        self.math = MathTextView(fallback_text, parent=self)
        self.math.set_math_text(text)
        self.math.installEventFilter(self)
        if self.math.browser is not None:
            self.math.browser.installEventFilter(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.control, 0)
        layout.addWidget(self.math, 1)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched in {self.math, self.math.browser} and event.type() == QEvent.MouseButtonPress:
            self.control.toggle()
        return super().eventFilter(watched, event)
