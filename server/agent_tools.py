"""Cloud executors for the Agent tools shared with the desktop client.

The desktop client executes MCP tools against its local companion workspace.
The Web client uses a tenant/session-scoped cloud workspace instead.  Tool
names and Skill manifests stay identical so an Agent can be moved between the
two clients without changing its capability contract.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import requests
import base64
from app.agent_runtime import search_capabilities
from app.agent_runtime.observations import observe_failure, observe_success
from app.services.agent_skills import AgentSkillCatalog


MAX_OUTPUT_CHARS = 12_000
MAX_FILE_BYTES = 500_000


class WebAgentToolExecutor:
    """Execute cloud-safe counterparts of desktop MCP and Skill tools."""

    def __init__(self, *, tenant_id: str, session_id: int) -> None:
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.workspace = Path(tempfile.gettempdir()) / "learning-agent-workspaces" / tenant_id / str(session_id)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.skills_dir = Path(__file__).resolve().parents[1] / "skills"

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        name = tool_name.removeprefix("mcp.")
        if name == "tool.search":
            query = str(arguments.get("query", "")).strip()
            return {"capabilities": search_capabilities(query, client="web", limit=int(arguments.get("limit", 8)))}
        if name == "skill.load":
            skill_name = str(arguments.get("name", arguments.get("skill_name", ""))).strip()
            if not skill_name:
                raise ValueError("skill name is required")
            return {"skill": skill_name, "instructions": AgentSkillCatalog(self.skills_dir).load_skill(skill_name)}
        if name in {"web.search", "search_web"}:
            return {"results": self.search_web(str(arguments.get("query", "")))}
        if name in {"web.fetch", "fetch_public_url"}:
            return {"content": self.fetch_public_url(str(arguments.get("url", "")))}
        if name in {"web.browser_screenshot", "browser_screenshot"}:
            return self.browser_screenshot(arguments)
        if name == "list_workspace_files":
            return {"files": self.list_workspace_files(str(arguments.get("relative_path", ".")), int(arguments.get("limit", 100)))}
        if name == "read_workspace_file":
            return {"content": self.read_workspace_file(str(arguments.get("relative_path", "")), int(arguments.get("max_chars", 30_000)))}
        if name == "write_workspace_file":
            return {"message": self.write_workspace_file(str(arguments.get("relative_path", "")), str(arguments.get("content", "")))}
        if name in {"run_skill_script", "skill.run"}:
            return self.run_skill_script(str(arguments.get("skill_name", "")), arguments.get("arguments", {}))
        if name == "coding.run_python":
            return self.run_python(str(arguments.get("code", "")))
        if name == "coding.write_workspace":
            return {"message": self.write_workspace_file(str(arguments.get("relative_path", "")), str(arguments.get("content", "")))}
        if name == "coding.run_workspace_python":
            return self.run_workspace_python(str(arguments.get("relative_path", "")))
        if name == "coding.delete_workspace":
            return {"message": self.delete_workspace_file(str(arguments.get("relative_path", "")))}
        skill_aliases = {
            "skill.resource_analysis": "resource-analysis",
            "skill.learning_plan": "learning-plan",
            "skill.error_diagnosis": "error-diagnosis",
            "skill.report_visualization": "report-visualization",
        }
        if name in skill_aliases:
            return self.run_skill_script(skill_aliases[name], arguments)
        raise ValueError(f"unsupported Web Agent tool: {tool_name}")

    def execute_observed(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return observe_success(tool_name, self.execute(tool_name, arguments), source="cloud")
        except Exception as exc:
            return observe_failure(tool_name, exc, suggestion="change the query or ask the learner for clarification")

    def run_python(self, code: str) -> dict[str, Any]:
        if not code.strip() or len(code) > 12_000:
            raise ValueError("sandbox code must contain 1 to 12000 characters")
        try:
            import docker
            client = docker.from_env()
            container = client.containers.run(
                "personal_learning_desktop-agent-sandbox:latest", ["-I", "-c", code],
                detach=True, network_mode="none", read_only=True, user="10001:10001",
                mem_limit="256m", nano_cpus=500_000_000, pids_limit=64,
                security_opt=["no-new-privileges"], remove=False,
            )
            try:
                result = container.wait(timeout=30)
                logs = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")[-12_000:]
                errors = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")[-4_000:]
            finally:
                container.remove(force=True)
        except Exception as exc:
            raise RuntimeError(f"cloud sandbox execution failed: {exc}") from exc
        return {"returncode": int(result.get("StatusCode", 1)), "stdout": logs, "stderr": errors}

    def search_web(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        query = query.strip()
        if not query:
            raise ValueError("search query is required")
        # Uvicorn does not automatically export values from the project .env
        # into os.environ. Load it here so the tool sees the same Tavily
        # configuration as the rest of the server settings.
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
        key = os.getenv("TAVILY_API_KEY", "").strip()
        if not key:
            raise RuntimeError("TAVILY_API_KEY is not configured; Web search is unavailable")
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": query, "search_depth": "basic", "max_results": max(1, min(max_results, 10))},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"web search failed: {exc}") from exc
        results = [
            {"title": str(item.get("title", ""))[:500], "url": str(item.get("url", "")), "description": str(item.get("content", ""))[:1600]}
            for item in payload.get("results", []) if isinstance(item, dict)
        ]
        # For material-seeking requests, a timetable or administrative notice
        # is not a study resource. Keep schedule lookups intact, but rank them
        # out of the dedicated research Agent's learning-material candidates.
        material_request = any(term in query.casefold() for term in (
            "资料", "教材", "真题", "练习", "题目", "教程", "课程", "学习材料",
            "study material", "practice", "tutorial", "lecture",
        ))
        if material_request:
            notice_terms = ("通知", "公告", "报名", "考试时间", "考试安排", "admission", "notice", "schedule")
            learning_terms = ("教材", "真题", "练习", "教程", "课程", "听力", "阅读", "写作", "题库", "pdf", "lesson", "practice")
            focused = [item for item in results if not any(term in f"{item['title']} {item['description']}".casefold() for term in notice_terms) and any(term in f"{item['title']} {item['description']}".casefold() for term in learning_terms)]
            cet_request = any(term in query.casefold() for term in ("cet-6", "cet6", "大学英语六级", "英语六级"))
            if cet_request:
                cet_terms = ("cet-6", "cet6", "六级", "大学英语")
                focused = [item for item in focused if any(term in f"{item['title']} {item['description']}".casefold() for term in cet_terms)]
            results = focused
        return results[:max(1, min(max_results, 10))]

    def fetch_public_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("only public HTTPS URLs can be fetched")
        try:
            addresses = {record[4][0] for record in socket.getaddrinfo(parsed.hostname, 443)}
        except OSError as exc:
            raise ValueError("host could not be resolved") from exc
        if not addresses or any(not self._public_address(value) for value in addresses):
            raise ValueError("URL must resolve only to public addresses")
        request = Request(url, headers={"User-Agent": "LearningAgent/1.0"})
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/plain", "text/html", "application/json"}:
                raise ValueError(f"unsupported response type: {content_type}")
            return response.read(100_000).decode("utf-8", errors="replace")

    def browser_screenshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Capture a public page after a small, read-only action sequence.

        Authentication, downloads, uploads, scripts, and arbitrary selectors are
        intentionally unsupported. The browser dependency is optional so the
        core SaaS service can still start without a browser image installed.
        """
        url = str(arguments.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("browser automation only accepts public HTTPS URLs")
        actions = arguments.get("actions", [])
        if not isinstance(actions, list) or len(actions) > 8:
            raise ValueError("at most 8 read-only browser actions are allowed")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("browser automation is not installed in this deployment") from exc
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                for action in actions:
                    if not isinstance(action, dict):
                        raise ValueError("browser actions must be objects")
                    kind = str(action.get("type", "")).lower()
                    if kind == "wait":
                        page.wait_for_timeout(min(max(int(action.get("milliseconds", 500)), 0), 3000))
                    elif kind == "scroll":
                        page.mouse.wheel(0, min(max(int(action.get("pixels", 500)), -1500), 1500))
                    elif kind == "click":
                        selector = str(action.get("selector", ""))
                        if not selector or any(token in selector for token in ("javascript:", "xpath=", "..")):
                            raise ValueError("only simple CSS selectors are allowed")
                        page.locator(selector).first.click(timeout=5000)
                    elif kind == "type":
                        selector = str(action.get("selector", "")); value = str(action.get("text", ""))
                        if not selector or len(value) > 1000 or any(token in selector for token in ("javascript:", "xpath=", "..")):
                            raise ValueError("invalid type action")
                        page.locator(selector).first.fill(value, timeout=5000)
                    else:
                        raise ValueError(f"unsupported browser action: {kind}")
                screenshot = page.screenshot(type="png", full_page=False)
                title = page.title()
                final_url = page.url
                browser.close()
        except Exception as exc:
            raise RuntimeError(f"browser screenshot failed: {exc}") from exc
        return {"url": final_url, "title": title[:300], "mime_type": "image/png", "image_base64": base64.b64encode(screenshot).decode("ascii")}

    def list_workspace_files(self, relative_path: str, limit: int) -> list[str]:
        root = self._path(relative_path)
        if not root.is_dir():
            raise ValueError("workspace path is not a directory")
        return [item.relative_to(self.workspace).as_posix() for item in list(root.rglob("*"))[:max(1, min(limit, 300))] if item.is_file()]

    def read_workspace_file(self, relative_path: str, max_chars: int) -> str:
        path = self._path(relative_path)
        if not path.is_file():
            raise ValueError("workspace file does not exist")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("workspace file is too large")
        return path.read_text(encoding="utf-8")[:max(1, min(max_chars, 30_000))]

    def write_workspace_file(self, relative_path: str, content: str) -> str:
        path = self._path(relative_path, writable=True)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("workspace file content is too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"wrote {path.relative_to(self.workspace).as_posix()}"

    def run_workspace_python(self, relative_path: str) -> dict[str, Any]:
        path = self._path(relative_path)
        if path.suffix.lower() != ".py":
            raise ValueError("only Python workspace files can be run")
        return self.run_python(self.read_workspace_file(relative_path, MAX_FILE_BYTES))

    def delete_workspace_file(self, relative_path: str) -> str:
        path = self._path(relative_path)
        if not path.is_file():
            raise ValueError("workspace file does not exist")
        path.unlink()
        return f"deleted {path.relative_to(self.workspace).as_posix()}"

    def run_skill_script(self, skill_name: str, arguments: object) -> dict[str, Any]:
        if not skill_name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid skill name")
        if not isinstance(arguments, dict):
            raise ValueError("skill arguments must be an object")
        skill_dir = (self.skills_dir / skill_name).resolve()
        if self.skills_dir.resolve() not in skill_dir.parents:
            raise PermissionError("skill path escapes the skill catalog")
        manifest_path = skill_dir / "skill.json"
        if not manifest_path.is_file():
            raise ValueError("skill is not executable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entrypoint = manifest.get("entrypoint")
        script = (skill_dir / str(entrypoint)).resolve()
        if not isinstance(entrypoint, str) or skill_dir not in script.parents or not script.is_file() or script.suffix != ".py":
            raise ValueError("invalid Skill entrypoint")
        payload = dict(arguments)
        payload.setdefault("workspace", str(self.workspace))
        result = subprocess.run([sys.executable, "-I", str(script)], input=json.dumps(payload, ensure_ascii=True), capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=self.workspace)
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:] or "Skill script failed")
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Skill script returned invalid JSON") from exc
        return {"skill": skill_name, "output": output}

    def _path(self, relative_path: str, *, writable: bool = False) -> Path:
        path = (self.workspace / relative_path).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise PermissionError("workspace path escapes its session")
        if writable and path.suffix.lower() not in {".py", ".md", ".mmd", ".json", ".toml", ".txt", ".yaml", ".yml"}:
            raise PermissionError("file type is not writable")
        return path

    @staticmethod
    def _public_address(value: str) -> bool:
        address = ip_address(value)
        return not any((address.is_private, address.is_loopback, address.is_link_local, address.is_multicast, address.is_reserved, address.is_unspecified))
