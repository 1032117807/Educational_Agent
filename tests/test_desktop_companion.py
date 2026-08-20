from __future__ import annotations

from app.services.desktop_companion import DesktopCompanion


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, bool]] = []

    def execute(self, name: str, arguments: dict, *, confirmed: bool) -> dict:
        self.calls.append((name, arguments, confirmed))
        return {"ok": True}


def test_companion_maps_web_desktop_tools_to_local_mcp() -> None:
    gateway = FakeGateway()
    companion = DesktopCompanion(
        api_url="http://127.0.0.1:8000", access_token="token", companion_id="desktop-a", gateway=gateway,
    )
    assert companion.enabled
    assert companion._execute_tool("desktop.read_file", {"relative_path": "notes.md"}) == {"ok": True}
    assert gateway.calls == [("read_workspace_file", {"relative_path": "notes.md"}, True)]


def test_companion_requires_complete_configuration() -> None:
    assert not DesktopCompanion(api_url="", access_token="token", companion_id="desktop-a").enabled
