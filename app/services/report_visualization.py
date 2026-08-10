"""Deterministic local SVG charts for learning reports."""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.reports.learning_report import LearningStats


class ReportVisualizationService:
    """Render objective report metrics locally; never sends learning data to a chart API."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def render(self, stats: "LearningStats") -> tuple[Path, ...]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        overview = self.output_dir / f"report-overview-{stamp}.svg"
        mastery = self.output_dir / f"report-mastery-{stamp}.svg"
        overview.write_text(self._overview_svg(stats), encoding="utf-8")
        mastery.write_text(self._mastery_svg(stats), encoding="utf-8")
        return overview, mastery

    @staticmethod
    def _svg(body: str, height: int) -> str:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="760" '
            f'height="{height}" viewBox="0 0 760 {height}">'
            '<style>text{font-family:Arial,Microsoft YaHei,sans-serif;fill:#172B4D}'
            '.title{font-size:22px;font-weight:700}.label{font-size:15px}.value{font-size:18px;font-weight:700}</style>'
            '<rect width="100%" height="100%" fill="#FFFFFF"/>' + body + '</svg>'
        )

    def _overview_svg(self, stats: "LearningStats") -> str:
        accuracy = round(stats.accuracy * 100)
        completion = round(stats.task_completion_rate * 100)
        blocks = [
            '<text x="32" y="42" class="title">学习概览</text>',
            f'<text x="32" y="70" class="label">{escape(str(stats.start_date))} 至 {escape(str(stats.end_date))}</text>',
        ]
        for row, (label, value, color, detail) in enumerate((
            ("练习正确率", accuracy, "#2E90FA", f"{stats.correct_total}/{stats.attempt_total}"),
            ("任务完成率", completion, "#12B76A", f"{stats.task_completed}/{stats.task_total}"),
        )):
            y = 125 + row * 100
            blocks.extend((
                f'<text x="32" y="{y}" class="label">{label}</text>',
                f'<rect x="200" y="{y - 20}" width="440" height="24" rx="12" fill="#E4E7EC"/>',
                f'<rect x="200" y="{y - 20}" width="{440 * value / 100:.1f}" height="24" rx="12" fill="{color}"/>',
                f'<text x="660" y="{y}" class="value">{value}%</text>',
                f'<text x="200" y="{y + 30}" class="label">{detail}</text>',
            ))
        blocks.extend((
            f'<text x="32" y="345" class="label">本周期学习时长</text>',
            f'<text x="240" y="345" class="value">{stats.study_minutes} 分钟</text>',
        ))
        return self._svg("".join(blocks), 385)

    def _mastery_svg(self, stats: "LearningStats") -> str:
        points = list(stats.weak_points[:8])
        height = max(170, 100 + len(points) * 52)
        blocks = ['<text x="32" y="42" class="title">待强化知识点掌握度</text>']
        if not points:
            blocks.append('<text x="32" y="92" class="label">本周期暂无可视化知识点数据。</text>')
        for index, point in enumerate(points):
            name = escape(str(point.get("name", "未命名知识点"))[:24])
            mastery = max(0, min(100, int(point.get("mastery", 0))))
            y = 88 + index * 52
            blocks.extend((
                f'<text x="32" y="{y}" class="label">{name}</text>',
                f'<rect x="280" y="{y - 17}" width="360" height="20" rx="10" fill="#F2F4F7"/>',
                f'<rect x="280" y="{y - 17}" width="{360 * mastery / 100:.1f}" height="20" rx="10" fill="#F79009"/>',
                f'<text x="660" y="{y}" class="value">{mastery}%</text>',
            ))
        return self._svg("".join(blocks), height)
