"""Render report SVG charts from JSON on stdin; output chart payloads as JSON."""
from __future__ import annotations

import json
import sys
from html import escape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def svg(body: str, height: int) -> str:
    # 历史资料、网页文本或模型输出中可能含有不完整的 Unicode 代理字符。
    # UTF-8 无法直接编码它们，因此在生成 SVG 前统一替换为安全字符。
    body = body.encode("utf-8", errors="replace").decode("utf-8")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" '
        f'height="{height}" viewBox="0 0 760 {height}">'
        '<style>text{font-family:Arial,Microsoft YaHei,sans-serif;fill:#172B4D}'
        '.title{font-size:22px;font-weight:700}.label{font-size:15px}.value{font-size:18px;font-weight:700}</style>'
        '<rect width="100%" height="100%" fill="#FFFFFF"/>' + body + '</svg>'
    )


def safe_text(value: object) -> str:
    """将异常 Unicode 代理字符替换为可安全写入 SVG 的字符。"""
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


def overview(stats: dict) -> str:
    accuracy = round(float(stats.get("accuracy", 0)) * 100)
    completion = round(float(stats.get("task_completion_rate", 0)) * 100)
    blocks = [
        '<text x="32" y="42" class="title">学习概览</text>',
        f'<text x="32" y="70" class="label">{escape(str(stats.get("start_date", "")))} 至 {escape(str(stats.get("end_date", "")))}</text>',
    ]
    rows = (
        ("练习正确率", accuracy, "#2E90FA", f'{stats.get("correct_total", 0)}/{stats.get("attempt_total", 0)}'),
        ("任务完成率", completion, "#12B76A", f'{stats.get("task_completed", 0)}/{stats.get("task_total", 0)}'),
    )
    for index, (label, value, color, detail) in enumerate(rows):
        y = 125 + index * 100
        blocks.extend((
            f'<text x="32" y="{y}" class="label">{label}</text>',
            f'<rect x="200" y="{y - 20}" width="440" height="24" rx="12" fill="#E4E7EC"/>',
            f'<rect x="200" y="{y - 20}" width="{440 * value / 100:.1f}" height="24" rx="12" fill="{color}"/>',
            f'<text x="660" y="{y}" class="value">{value}%</text>',
            f'<text x="200" y="{y + 30}" class="label">{detail}</text>',
        ))
    blocks.extend((
        '<text x="32" y="345" class="label">本周期学习时长</text>',
        f'<text x="240" y="345" class="value">{int(stats.get("study_minutes", 0))} 分钟</text>',
    ))
    return svg("".join(blocks), 385)


def mastery(stats: dict) -> str:
    points = list(stats.get("weak_points", []))[:8]
    height = max(170, 100 + len(points) * 52)
    blocks = ['<text x="32" y="42" class="title">待强化知识点掌握度</text>']
    if not points:
        blocks.append('<text x="32" y="92" class="label">本周期暂无可视化知识点数据。</text>')
    for index, point in enumerate(points):
        name = escape(safe_text(point.get("name", "未命名知识点"))[:24])
        value = max(0, min(100, int(point.get("mastery", 0))))
        y = 88 + index * 52
        blocks.extend((
            f'<text x="32" y="{y}" class="label">{name}</text>',
            f'<rect x="280" y="{y - 17}" width="360" height="20" rx="10" fill="#F2F4F7"/>',
            f'<rect x="280" y="{y - 17}" width="{360 * value / 100:.1f}" height="20" rx="10" fill="#F79009"/>',
            f'<text x="660" y="{y}" class="value">{value}%</text>',
        ))
    return svg("".join(blocks), height)


def main() -> None:
    payload = json.load(sys.stdin)
    stats = payload.get("stats", payload)
    if not isinstance(stats, dict):
        raise ValueError("stats must be an object")
    # 使用 ASCII 转义输出；调用方 json.loads 后会恢复正常中文字符。
    print(json.dumps({"charts": [
        {"filename": "learning-overview.svg", "svg": overview(stats)},
        {"filename": "knowledge-mastery.svg", "svg": mastery(stats)},
    ]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
