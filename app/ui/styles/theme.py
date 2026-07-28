from __future__ import annotations

LIGHT = """
QWidget { color: #182230; background: #F5F7FA; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow, QDialog { background: #F5F7FA; }
#sidebar { background: #FFFFFF; border-right: 1px solid #E3E8EF; }
#topbar { background: #FFFFFF; border-bottom: 1px solid #E3E8EF; }
#brand { font-size: 17px; font-weight: 700; color: #155EEF; }
QPushButton { background: #FFFFFF; border: 1px solid #CDD5DF; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { border-color: #155EEF; color: #155EEF; }
QPushButton:checked, QPushButton[primary="true"] { background: #155EEF; color: white; border-color: #155EEF; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: white; border: 1px solid #CDD5DF; border-radius: 7px; padding: 7px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border: 2px solid #528BFF; }
QFrame[card="true"] { background: white; border: 1px solid #E3E8EF; border-radius: 10px; }
QLabel[muted="true"] { color: #697586; }
QLabel[title="true"] { font-size: 24px; font-weight: 700; }
QTableWidget { background: white; border: 1px solid #E3E8EF; border-radius: 8px; gridline-color: #EEF2F6; }
QHeaderView::section { background: #F8FAFC; padding: 8px; border: none; border-bottom: 1px solid #E3E8EF; font-weight: 600; }
QProgressBar { border: none; border-radius: 4px; background: #E8EEF8; height: 8px; text-align: center; }
QProgressBar::chunk { background: #155EEF; border-radius: 4px; }
QStatusBar { background: white; border-top: 1px solid #E3E8EF; color: #697586; }
"""

DARK = """
QWidget { color: #E6E9EF; background: #111827; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow, QDialog { background: #111827; }
#sidebar, #topbar { background: #182230; border-color: #344054; }
#brand { font-size: 17px; font-weight: 700; color: #84ADFF; }
QPushButton { background: #1F2937; border: 1px solid #475467; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { border-color: #84ADFF; }
QPushButton:checked, QPushButton[primary="true"] { background: #2970FF; color: white; border-color: #2970FF; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget { background: #182230; border: 1px solid #475467; border-radius: 7px; padding: 7px; }
QFrame[card="true"] { background: #182230; border: 1px solid #344054; border-radius: 10px; }
QLabel[muted="true"] { color: #98A2B3; }
QLabel[title="true"] { font-size: 24px; font-weight: 700; }
QHeaderView::section { background: #1F2937; padding: 8px; border: none; color: #D0D5DD; }
QProgressBar { border: none; border-radius: 4px; background: #344054; height: 8px; }
QProgressBar::chunk { background: #528BFF; border-radius: 4px; }
QStatusBar { background: #182230; border-top: 1px solid #344054; color: #98A2B3; }
"""
