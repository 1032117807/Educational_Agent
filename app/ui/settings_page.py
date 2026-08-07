from __future__ import annotations

import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

from dotenv import dotenv_values
from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QCheckBox,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.learning import LearningService
from app.services.agent_permissions import AgentPermissionService, DEFAULT_POLICY


from app.ui.components import page_title, stat_card

class SettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, config: object, maintenance: object, learning: LearningService) -> None:
        super().__init__()
        self.config = config
        self.maintenance = maintenance
        self.learning = learning
        self.mcp_permissions = AgentPermissionService(self.config.data_dir / "mcp_policy.json")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addLayout(page_title("系统设置", "外观、本地数据与学习偏好"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(["浅色", "深色"])
        self.theme.currentTextChanged.connect(lambda text: self.theme_changed.emit("dark" if text == "深色" else "light"))
        goal = QSpinBox()
        goal.setRange(10, 600)
        goal.setValue(60)
        goal.setSuffix(" 分钟")
        goal.setValue(int(self.maintenance.get_setting("daily_goal_minutes", "60")))
        autosave = QComboBox()
        autosave.addItems(["开启", "关闭"])
        autosave.setCurrentText("开启" if self.maintenance.get_setting("autosave", "true") == "true" else "关闭")
        language = QComboBox()
        language.addItem("简体中文")
        date_format = QComboBox()
        date_format.addItems(["yyyy-MM-dd", "yyyy/MM/dd", "yyyy年MM月dd日"])
        date_format.setCurrentText(self.maintenance.get_setting("date_format", "yyyy-MM-dd"))
        week_start = QComboBox()
        week_start.addItems(["星期一", "星期日"])
        week_start.setCurrentText(self.maintenance.get_setting("week_start", "星期一"))
        question_count = QSpinBox()
        question_count.setRange(1, 200)
        question_count.setValue(int(self.maintenance.get_setting("default_question_count", "10")))
        difficulty = QSpinBox()
        difficulty.setRange(1, 5)
        difficulty.setValue(int(self.maintenance.get_setting("default_difficulty", "3")))
        immediate = QComboBox()
        immediate.addItems(["即时显示", "提交后显示"])
        immediate.setCurrentText(self.maintenance.get_setting("answer_feedback", "即时显示"))
        compact = QComboBox()
        compact.addItems(["标准", "紧凑"])
        compact.setCurrentText(self.maintenance.get_setting("density", "标准"))
        form.addRow("主题", self.theme)
        form.addRow("语言", language)
        form.addRow("日期格式", date_format)
        form.addRow("每周第一天", week_start)
        form.addRow("每日学习目标", goal)
        form.addRow("自动保存", autosave)
        form.addRow("默认练习题数", question_count)
        form.addRow("默认难度", difficulty)
        form.addRow("答案显示", immediate)
        form.addRow("界面密度", compact)
        form.addRow("数据目录", QLabel(str(self.config.data_dir)))
        form.addRow("AI 功能", QLabel("尚未启用（第一阶段保持完全本地）"))
        form.addRow("MCP 功能", QLabel("尚未启用"))
        root.addLayout(form)
        self.mcp_checks: dict[str, QCheckBox] = {}
        mcp_form = QFormLayout()
        mcp_form.addRow(QLabel("MCP Agent permissions"))
        current_policy = self.mcp_permissions.policy()
        labels = {
            "list_workspace_files": "Allow listing workspace files",
            "read_workspace_file": "Allow reading workspace files",
            "fetch_public_url": "Allow approved HTTPS sites",
            "search_web": "Allow Tavily web search",
            "write_workspace_file": "Allow writing approved file types (confirmation required)",
            "run_python_in_sandbox": "Allow Docker Python sandbox (confirmation required)",
            "run_skill_script": "Allow executable Agent Skills in Docker sandbox (confirmation required)",
        }
        for name in DEFAULT_POLICY:
            check = QCheckBox(labels[name])
            check.setChecked(current_policy[name][0])
            self.mcp_checks[name] = check
            mcp_form.addRow(check)
        self.mcp_status = QLabel()
        refresh_mcp = QPushButton("Refresh MCP status")
        refresh_mcp.clicked.connect(self.refresh_mcp_status)
        mcp_form.addRow("Runtime", self.mcp_status)
        mcp_form.addRow(refresh_mcp)
        root.addLayout(mcp_form)
        self.refresh_mcp_status()
        actions = QGridLayout()
        save = QPushButton("保存设置")
        save.setProperty("primary", True)
        save.clicked.connect(lambda: self.save(
            goal.value(), autosave.currentText(), date_format.currentText(),
            week_start.currentText(), question_count.value(), difficulty.value(),
            immediate.currentText(), compact.currentText()
        ))
        backup = QPushButton("创建完整备份")
        backup.clicked.connect(self.backup)
        restore = QPushButton("从备份恢复")
        restore.clicked.connect(self.restore)
        open_workspace = QPushButton("打开 workspace")
        open_workspace.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.workspace_dir)))
        )
        demo = QPushButton("加载演示数据")
        demo.clicked.connect(self.load_demo)
        clear_demo = QPushButton("清除演示数据")
        clear_demo.clicked.connect(self.clear_demo)
        export_data = QPushButton("导出全部数据")
        export_data.clicked.connect(self.export_data)
        check_data = QPushButton("检查数据")
        check_data.clicked.connect(self.check_data)
        vacuum = QPushButton("压缩数据库")
        vacuum.clicked.connect(self.vacuum)
        reset = QPushButton("重置全部数据")
        reset.clicked.connect(self.reset_data)
        for index, button in enumerate((
            save, backup, restore, open_workspace, demo, clear_demo, export_data, check_data, vacuum, reset
        )):
            actions.addWidget(button, index // 4, index % 4)
        root.addLayout(actions)
        info = self.maintenance.database_info()
        root.addWidget(QLabel(
            f"数据库：{info['database_bytes'] / 1024:.1f} KB    "
            f"资料：{info['file_count']} 个 / {info['file_bytes'] / 1024:.1f} KB"
        ))
        root.addStretch()

    def save(
        self, goal: int, autosave: str, date_format: str, week_start: str,
        question_count: int, difficulty: int, immediate: str, compact: str
    ) -> None:
        self.maintenance.set_setting("daily_goal_minutes", str(goal))
        self.maintenance.set_setting("autosave", "true" if autosave == "开启" else "false")
        self.maintenance.set_setting("date_format", date_format)
        self.maintenance.set_setting("week_start", week_start)
        self.maintenance.set_setting("default_question_count", str(question_count))
        self.maintenance.set_setting("default_difficulty", str(difficulty))
        self.maintenance.set_setting("answer_feedback", immediate)
        self.maintenance.set_setting("density", compact)
        self.mcp_permissions.save_policy({name: check.isChecked() for name, check in self.mcp_checks.items()})
        QMessageBox.information(self, "设置", "设置已保存。")

    def refresh_mcp_status(self) -> None:
        docker = "available" if shutil.which("docker") else "not installed"
        env_values = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
        tavily = "configured" if (os.getenv("TAVILY_API_KEY") or env_values.get("TAVILY_API_KEY")) else "not configured"
        self.mcp_status.setText(f"Docker: {docker}; Tavily Search: {tavily}")

    def backup(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "创建完整备份", "learning-backup.zip", "ZIP (*.zip)")
        if filename:
            try:
                path = self.maintenance.backup(Path(filename))
                QMessageBox.information(self, "备份完成", f"备份已保存到：\n{path}")
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "备份失败", str(error))

    def restore(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "选择备份", filter="ZIP (*.zip)")
        if not filename:
            return
        if QMessageBox.warning(
            self, "恢复备份", "恢复前会自动备份当前数据。恢复完成后建议重启应用，确认继续？",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            self.maintenance.restore(Path(filename))
            QMessageBox.information(self, "恢复完成", "数据已恢复，请重启应用。")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "恢复失败", str(error))

    def load_demo(self) -> None:
        self.learning.seed_demo()
        QMessageBox.information(self, "演示数据", "演示数据已加载；不会覆盖已有用户数据。")

    def clear_demo(self) -> None:
        if QMessageBox.question(self, "清除演示数据", "只删除 source=demo 的数据，用户数据不受影响。继续？") == QMessageBox.Yes:
            count = self.learning.clear_demo()
            QMessageBox.information(self, "清理完成", f"已清除 {count} 条演示数据。")

    def export_data(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if directory:
            try:
                counts = self.maintenance.export_user_data(Path(directory))
                summary = "，".join(f"{key} {value}" for key, value in counts.items())
                QMessageBox.information(self, "导出完成", f"数据已导出：{summary}")
            except OSError as error:
                QMessageBox.warning(self, "导出失败", str(error))

    def check_data(self) -> None:
        result = self.maintenance.integrity_check()
        QMessageBox.information(
            self, "数据检查",
            f"数据库：{result['database']}\n缺失文件：{len(result['missing_files'])}\n"
            f"孤立文件：{len(result['orphaned_files'])}"
        )

    def vacuum(self) -> None:
        try:
            self.maintenance.vacuum()
            QMessageBox.information(self, "数据库维护", "数据库压缩完成。")
        except Exception as error:
            QMessageBox.warning(self, "维护失败", str(error))

    def reset_data(self) -> None:
        text, ok = QInputDialog.getText(
            self, "重置全部数据", "此操作会清空数据库并将资料移入可恢复目录。\n请输入 RESET 确认："
        )
        if not ok:
            return
        try:
            deleted = self.maintenance.reset_all(text)
            QMessageBox.information(self, "重置完成", f"已清除 {deleted} 条数据；资料已移入 workspace/.trash。")
        except ValueError as error:
            QMessageBox.warning(self, "未重置", str(error))
