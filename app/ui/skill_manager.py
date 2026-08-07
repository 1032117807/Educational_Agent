from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget,
)

from app.services.agent_skills import AgentSkillCatalog


class SkillManagerDialog(QDialog):
    """Manage local Agent Skills and the permission scopes they may request."""

    def __init__(self, catalog: AgentSkillCatalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.skills = catalog.list_skills()
        self.setWindowTitle("Agent Skills 管理")
        self.resize(820, 520)
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        self.items = QListWidget()
        for skill in self.skills:
            item = QListWidgetItem(f"{'已启用' if skill['enabled'] else '已禁用'}  {skill['display_name']}")
            item.setData(Qt.UserRole, skill["name"])
            self.items.addItem(item)
        self.items.currentRowChanged.connect(self._show_skill)
        splitter.addWidget(self.items)

        details = QWidget()
        form = QFormLayout(details)
        self.enabled = QCheckBox("启用此 Skill")
        self.version = QLineEdit()
        self.version.setReadOnly(True)
        self.executable = QLineEdit()
        self.executable.setReadOnly(True)
        self.scopes = QLineEdit()
        self.scopes.setPlaceholderText("用英文逗号分隔，例如 mcp.search_web,human.confirmation")
        self.description = QPlainTextEdit()
        self.description.setReadOnly(True)
        self.instructions = QPlainTextEdit()
        self.instructions.setReadOnly(True)
        form.addRow("状态", self.enabled)
        form.addRow("版本", self.version)
        form.addRow("可执行入口", self.executable)
        form.addRow("权限范围", self.scopes)
        form.addRow("说明", self.description)
        form.addRow("Skill 指令", self.instructions)
        splitter.addWidget(details)
        splitter.setSizes([240, 560])
        root.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if self.skills:
            self.items.setCurrentRow(0)

    def _current(self) -> dict[str, object] | None:
        row = self.items.currentRow()
        return self.skills[row] if 0 <= row < len(self.skills) else None

    def _show_skill(self, row: int) -> None:
        skill = self._current()
        if skill is None:
            return
        self.enabled.setChecked(bool(skill["enabled"]))
        self.version.setText(str(skill["version"]))
        self.executable.setText(str(skill["entrypoint"]) if skill["executable"] else "无")
        self.scopes.setText(", ".join(str(item) for item in skill["permissions"]))
        self.description.setPlainText(str(skill["description"]))
        self.instructions.setPlainText(str(skill["instructions"]))

    def save(self) -> None:
        skill = self._current()
        if skill is None:
            return
        self.catalog.update(
            str(skill["name"]),
            enabled=self.enabled.isChecked(),
            permissions=self.scopes.text().split(","),
        )
        self.accept()
