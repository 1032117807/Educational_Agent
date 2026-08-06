from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("learning-project-ops")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 允许访问的网址
ALLOWED_HOSTS = {
    "docs.python.org",
    "platform.openai.com",
    "github.com",
    "raw.githubusercontent.com",
}

ALLOWED_COMMANDS = {
    "python": [sys.executable],
    "pytest": [sys.executable, "-m", "pytest"],
}


def safe_path(relative_path: str) -> Path:
    path = (PROJECT_ROOT/relative_path).resolve()
    if path != PROJECT_ROOT and PROJECT_ROOT not in path.parents:
        raise ValueError("路径超出项目目录")
    return path

@mcp.tool()
def list_files(relative_path:str = ".", max_items: int = 100) -> list[str]:
    """列出项目目录内文件，只读。"""
    root = safe_path(relative_path)
    if not root.is_dir():
        raise ValueError("不是目录")

    return [
        item.relative_to(PROJECT_ROOT).as_posix()
        for item in list(root.rglob("*"))[:max_items]
    ]


@mcp.tool()
def read_file(relative_path: str, max_chars: int = 30_000) -> str:
    """读取 UTF-8 文本文件。"""
    path = safe_path(relative_path)
    if not path.is_file():
        raise ValueError("文件不存在")

    return path.read_text(encoding="utf-8")[:max_chars]


@mcp.tool()
def write_file(relative_path: str, content: str, confirmed: bool = False) -> str:
    """写入项目文件。必须由界面人工确认后传入 confirmed=True。"""
    if not confirmed:
        raise PermissionError("写文件需要人工确认")

    path = safe_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"已写入：{path.relative_to(PROJECT_ROOT)}"


@mcp.tool()
def run_project_check(
    command:str,
    args: list[str] | None = None,
    confirmed: bool = False,
) -> dict:
    """运行受限的项目检查命令，例如 pytest。"""
    if not confirmed:
        raise PermissionError("执行命令需要人工确认")
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"不允许的命令：{command}")

    completed = subprocess.run(
        [*ALLOWED_COMMANDS[command], *(args or [])],
        cwd=PROJECT_ROOT,
        shell=False,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
    )

    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-12_000:],
        "stderr": completed.stderr[-4_000:],
    }

@mcp.tool()
def fetch_web_page(url:str, max_chars: int = 20_000) -> str:
    """抓取白名单网站的公开文本内容。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise PermissionError("仅允许访问 HTTPS 白名单域名")

    request = Request(url, headers={"User-Agent": "LearningAgent/1.0"})
    with urlopen(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/plain", "text/html", "application/json"}:
            raise ValueError(f"不支持的响应类型：{content_type}")
        return response.read(max_chars).decode("utf-8", errors="replace")

if __name__ == "__main__":
    mcp.run(transport="stdio")
    