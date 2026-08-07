from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("learning-agent-mcp")

WORKSPACE = Path(os.getenv("AGENT_WORKSPACE", Path(__file__).resolve().parents[1]))
load_dotenv(WORKSPACE / ".env")
APPROVAL_TOKEN = os.getenv("MCP_APPROVAL_TOKEN", "")
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
SKILLS_DIR = WORKSPACE / "skills"

ALLOWED_HOSTS = {
    "docs.python.org",
    "platform.openai.com",
    "github.com",
    "raw.githubusercontent.com",
    "api.tavily.com",
}
WRITABLE_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".yaml", ".yml"}
BLOCKED_PARTS = {".git", ".venv", "__pycache__", "node_modules", ".env"}
MAX_FILE_SIZE = 500_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise PermissionError("网络请求不允许自动跳转")


def safe_path(relative_path: str, *, writable: bool = False) -> Path:
    path = (WORKSPACE / relative_path).resolve(strict=False)

    if path != WORKSPACE and WORKSPACE not in path.parents:
        raise PermissionError("路径超出项目工作区")
    if any(part in BLOCKED_PARTS for part in path.relative_to(WORKSPACE).parts):
        raise PermissionError("该路径不允许 Agent 操作")

    current = path
    while current != WORKSPACE:
        if current.exists() and current.is_symlink():
            raise PermissionError("不允许通过符号链接访问文件")
        current = current.parent

    if writable and path.suffix.lower() not in WRITABLE_SUFFIXES:
        raise PermissionError(f"不允许写入 {path.suffix} 类型文件")

    return path


def require_approval(approval_token: str) -> None:
    if not APPROVAL_TOKEN or not secrets.compare_digest(
        approval_token, APPROVAL_TOKEN
    ):
        raise PermissionError("该操作必须经过人工确认")


def fetch(
    url: str, headers: dict[str, str] | None = None, body: bytes | None = None,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise PermissionError("仅允许访问 HTTPS 白名单域名")

    request = Request(
        url, data=body,
        headers={"User-Agent": "LearningAgent/1.0", **(headers or {})},
    )
    opener = build_opener(NoRedirect())
    with opener.open(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/plain", "text/html", "application/json"}:
            raise ValueError(f"不支持的响应类型：{content_type}")
        return response.read(50_000).decode("utf-8", errors="replace")


@mcp.tool()
def list_workspace_files(relative_path: str = ".", limit: int = 100) -> list[str]:
    """列出项目工作区文件，只读。"""
    root = safe_path(relative_path)
    if not root.is_dir():
        raise ValueError("目标不是目录")

    return [
        path.relative_to(WORKSPACE).as_posix()
        for path in list(root.rglob("*"))[:max(1, min(limit, 300))]
    ]


@mcp.tool()
def read_workspace_file(relative_path: str, max_chars: int = 30_000) -> str:
    """读取工作区 UTF-8 文本文件。"""
    path = safe_path(relative_path)
    if not path.is_file():
        raise ValueError("文件不存在")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("文件过大，请缩小读取范围")

    return path.read_text(encoding="utf-8")[:max_chars]


@mcp.tool()
def write_workspace_file(
    relative_path: str,
    content: str,
    approval_token: str = "",
) -> str:
    """写入项目文件。只能由客户端在人工确认后调用。"""
    require_approval(approval_token)
    path = safe_path(relative_path, writable=True)

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("写入内容过大")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"已写入 {path.relative_to(WORKSPACE).as_posix()}"


@mcp.tool()
def fetch_public_url(url: str) -> str:
    """访问白名单公开网页。"""
    return fetch(url)


@mcp.tool()
def search_web(query: str) -> list[dict[str, str]]:
    """使用 Tavily Search 搜索公开网络，需要 TAVILY_API_KEY。"""
    if not TAVILY_KEY:
        return [{
            "title": "Web search is not configured",
            "url": "",
            "description": "Add TAVILY_API_KEY to the project .env file to enable web search.",
        }]
    payload = json.loads(fetch(
        "https://api.tavily.com/search",
        {"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {TAVILY_KEY}"},
        json.dumps({"query": query, "search_depth": "basic", "max_results": 5}).encode("utf-8"),
    ))
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("content", ""),
        }
        for item in payload.get("results", [])
    ]


@mcp.tool()
def run_python_in_sandbox(code: str, approval_token: str = "") -> dict:
    """在 Docker 无网络只读沙箱执行 Python。"""
    require_approval(approval_token)

    command = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--pids-limit", "64",
        "--memory", "512m",
        "--cpus", "0.5",
        "--security-opt", "no-new-privileges",
        "--stop-timeout", "1",
        "-v", f"{WORKSPACE}:/workspace:ro",
        "-w", "/workspace",
        "learning-agent-sandbox:latest",
        "-I", "-c", code,
    ]
    result = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-12_000:],
        "stderr": result.stderr[-4_000:],
    }


@mcp.tool()
def run_skill_script(
    skill_name: str, arguments: dict | None = None, approval_token: str = ""
) -> dict:
    """运行 skill.json 声明的 Python 脚本，仅在 Docker 只读沙箱中执行。"""
    require_approval(approval_token)
    if not skill_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Skill 名称无效")
    skill_dir = (SKILLS_DIR / skill_name).resolve(strict=False)
    if SKILLS_DIR.resolve() not in skill_dir.parents:
        raise PermissionError("Skill 路径越界")
    manifest_path = skill_dir / "skill.json"
    if not manifest_path.is_file():
        raise ValueError("Skill 没有可执行清单")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint.endswith(".py"):
        raise ValueError("Skill 入口必须是 Python 脚本")
    script = (skill_dir / entrypoint).resolve(strict=False)
    if skill_dir not in script.parents or not script.is_file() or script.is_symlink():
        raise PermissionError("Skill 入口不在允许目录内")
    payload = arguments or {}
    if not isinstance(payload, dict):
        raise ValueError("Skill 参数必须是对象")
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("Skill 参数过大")
    command = [
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
        "--pids-limit", "64", "--memory", "512m", "--cpus", "0.5",
        "--security-opt", "no-new-privileges", "--stop-timeout", "1",
        "-v", f"{WORKSPACE}:/workspace:ro", "-w", "/workspace",
        "learning-agent-sandbox:latest", "python", "-I",
        f"/workspace/skills/{skill_name}/{entrypoint}",
    ]
    result = subprocess.run(
        command, shell=False, input=encoded, capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    return {
        "skill": skill_name,
        "returncode": result.returncode,
        "stdout": result.stdout[-12_000:],
        "stderr": result.stderr[-4_000:],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
