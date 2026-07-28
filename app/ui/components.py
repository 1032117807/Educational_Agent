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


def page_title(title: str, subtitle: str) -> QVBoxLayout:
    box = QVBoxLayout()
    label = QLabel(title)
    label.setProperty("title", True)
    hint = QLabel(subtitle)
    hint.setProperty("muted", True)
    box.addWidget(label)
    box.addWidget(hint)
    return box


def stat_card(title: str, value: str, caption: str) -> QFrame:
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    name = QLabel(title)
    name.setProperty("muted", True)
    number = QLabel(value)
    number.setStyleSheet("font-size: 26px; font-weight: 700;")
    note = QLabel(caption)
    note.setProperty("muted", True)
    layout.addWidget(name)
    layout.addWidget(number)
    layout.addWidget(note)
    return card


