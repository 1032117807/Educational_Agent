"""Authenticated bridge that lets a Web Agent use the signed-in desktop app.

The desktop initiates every network request.  The API only stores a queued
command, so the SaaS host never receives filesystem or shell permissions.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.services.mcp_gateway import MCPGateway


class DesktopCompanion:
    def __init__(
        self, *, api_url: str, access_token: str, companion_id: str,
        refresh_token: str = "", token_store: Path | None = None, gateway: MCPGateway | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.access_token = access_token.strip()
        self.refresh_token = refresh_token.strip()
        self.companion_id = companion_id.strip()
        self.token_store = token_store
        self.gateway = gateway or MCPGateway()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load_tokens()

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and (self.access_token or self.refresh_token) and self.companion_id)

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="desktop-companion", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                commands = self._request("GET", f"/v1/desktop-companion/commands?companion_id={quote(self.companion_id)}")
                if not isinstance(commands, list):
                    raise RuntimeError("companion command response must be a list")
                for command in commands:
                    if isinstance(command, dict):
                        self._execute(command)
            except (HTTPError, URLError, OSError, RuntimeError, ValueError):
                # A server restart or expired token must not take down the UI.
                pass
            self._stop.wait(1.5)

    def _execute(self, command: dict[str, Any]) -> None:
        command_id = int(command["command_id"])
        try:
            result = self._execute_tool(str(command["tool_name"]), dict(command.get("arguments", {})))
            payload: dict[str, object] = {"companion_id": self.companion_id, "result": result}
        except Exception as exc:
            payload = {"companion_id": self.companion_id, "error": f"{type(exc).__name__}: {exc}"}
        self._request("POST", f"/v1/desktop-companion/commands/{command_id}/result", payload)

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_map = {
            "desktop.list_files": "list_workspace_files",
            "desktop.read_file": "read_workspace_file",
            "desktop.write_file": "write_workspace_file",
            "desktop.run_code": "run_python_in_sandbox",
        }
        mcp_name = tool_map.get(name)
        if mcp_name is None:
            raise ValueError(f"unsupported desktop companion tool: {name}")
        return self.gateway.execute(mcp_name, arguments, confirmed=True)

    def _request(self, method: str, path: str, body: dict[str, object] | None = None, *, retried: bool = False) -> object:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.api_url}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code != 401 or retried or not self.refresh_token or path.startswith("/v1/auth/refresh"):
                raise
            self._refresh_access_token()
            return self._request(method, path, body, retried=True)
        return json.loads(raw) if raw else None

    def _refresh_access_token(self) -> None:
        data = json.dumps({"refresh_token": self.refresh_token}).encode("utf-8")
        request = Request(
            f"{self.api_url}/v1/auth/refresh", data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.access_token = str(payload["access_token"])
        self.refresh_token = str(payload.get("refresh_token", self.refresh_token))
        self._save_tokens()

    def _load_tokens(self) -> None:
        if self.token_store is None or not self.token_store.is_file():
            return
        try:
            value = json.loads(self.token_store.read_text(encoding="utf-8"))
            self.access_token = str(value.get("access_token", self.access_token))
            self.refresh_token = str(value.get("refresh_token", self.refresh_token))
        except (OSError, ValueError, TypeError):
            return

    def _save_tokens(self) -> None:
        if self.token_store is None:
            return
        self.token_store.parent.mkdir(parents=True, exist_ok=True)
        self.token_store.write_text(
            json.dumps({"access_token": self.access_token, "refresh_token": self.refresh_token}), encoding="utf-8",
        )
