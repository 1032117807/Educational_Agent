from __future__ import annotations

# 统一的桌面端设计令牌。页面样式只能引用这里定义的节奏与语义色。
TOKENS = {
    "sidebar_expanded": 230,
    "sidebar_compact": 64,
    "control_height": 36,
    "radius": 8,
    "space_small": 8,
    "space_medium": 16,
    "space_large": 24,
}

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
#agentChat { background: #F8FAFC; border: 1px solid #E3E8EF; border-radius: 8px; }
#agentChat table.message { margin: 8px 0; border-radius: 8px; }
#agentChat table.agent { background: #FFFFFF; border: 1px solid #E3E8EF; }
#agentChat table.user { background: #EAF2FF; border: 1px solid #B2CCFF; }
#agentChat .message-label { color: #475467; font-weight: 700; margin-bottom: 4px; }
#executionTimeline { background: #FFFFFF; border: 1px solid #E3E8EF; border-radius: 8px; }
#executionTimeline::item { min-height: 30px; padding: 6px 8px; border-bottom: 1px solid #F2F4F7; }
#executionTimeline::item:selected { background: #EFF8FF; color: #175CD3; }
#agentInput { min-height: 64px; }
#agentLiveStatus { color: #175CD3; background: #EFF8FF; border: 1px solid #B2DDFF; border-radius: 6px; padding: 8px 10px; }
#agentStreamOutput { background: #FFFFFF; border: 1px solid #D0D5DD; border-radius: 6px; padding: 8px; }
#agentPanelTitle { font-size: 15px; font-weight: 700; }
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
#agentChat { background: #111827; border: 1px solid #344054; border-radius: 8px; }
#agentChat table.agent { background: #182230; border: 1px solid #344054; }
#agentChat table.user { background: #1D3A5F; border: 1px solid #3B82C4; }
#agentChat .message-label { color: #98A2B3; font-weight: 700; margin-bottom: 4px; }
#executionTimeline { background: #182230; border: 1px solid #344054; border-radius: 8px; }
#executionTimeline::item { min-height: 30px; padding: 6px 8px; border-bottom: 1px solid #344054; }
#executionTimeline::item:selected { background: #1D3A5F; color: #D1E9FF; }
#agentLiveStatus { color: #D1E9FF; background: #15324F; border: 1px solid #3B82C4; border-radius: 6px; padding: 8px 10px; }
#agentStreamOutput { background: #182230; border: 1px solid #475467; border-radius: 6px; padding: 8px; }
"""
