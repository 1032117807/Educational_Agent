from pathlib import Path

from server.main import create_app


def test_web_client_assets_and_mount_are_present() -> None:
    root = Path("server/web")
    assert (root / "index.html").is_file()
    assert (root / "app.js").is_file()
    assert (root / "styles.css").is_file()

    page = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    assert 'data-view="goals"' in page
    assert 'id="goal-form"' in page
    assert 'id="knowledge-point-form"' in page
    assert "api('/goals'" in script
    assert "api('/knowledge-points'" in script
    routes = {getattr(route, "path", "") for route in create_app().routes}
    assert "/web" in routes
    assert 'data-view="members"' in page
    script = (root / "app.js").read_text(encoding="utf-8")
    assert "/organization/members" in script
    assert "/auth/refresh" in script
    assert "/auth/logout" in script
