from pathlib import Path
import re

from fastapi.testclient import TestClient

from server.config import ServerSettings
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
    assert 'resource_ids: [resourceId]' in script
    assert 'data-extract-resource="${resource.id}"' in script
    assert 'data-view-retry' in script
    assert 'dataset.jobState' in script
    assert 'value="multiple_choice"' in page
    assert 'value="fill_blank"' in page
    assert "practice-answer-long" in script
    assert 'id="knowledge-view"' in page
    assert "loadKnowledgeWorkspace" in script
    assert "dataset.courseView = 'knowledge'" in script
    assert 'data-course-view="knowledge">知识</button>' in script
    assert "Canonical course workspace entry point" in script
    assert "data.course || {}" in script
    assert "productLoadCoursesWithEmptyAction" in script
    assert "new-course-empty" in script
    assert "data-task-source" in script
    assert "data-task-course" in script
    assert "data-task-knowledge" in script
    assert "focus_areas" in script
    assert "generateWeeklyReportWithAi" in script
    assert "AI 解读与下周建议" in script
    assert "data-resource-summary" in script
    assert "data-resource-practice" in script
    assert "data-resource-tutor" in script
    assert "name=\"course_id\"" in page
    assert "ask-why-today" in script
    assert "data-knowledge-tutor" in script
    assert "AI 分析课程" in script
    assert "analyze-mistakes" in page
    assert "activeView === 'today'" in script
    assert "today: '今日学习'" in script
    assert "ai: 'AI 学习助手'" in script
    assert "localizeStaticProductCopy" in script
    assert "AI 生成题目" in script
    assert "输入学习问题、目标或想让 AI 帮你完成的下一步" in script
    assert "app.js?v=20260825-release-18" in page
    assert "bulk-delete-tasks" in script
    assert "task_ids: ids" in script
    assert "agent-course" in script
    assert 'src="/web/mathjax-config.js"' in page
    assert "<script>" not in page


def test_default_compose_does_not_mount_docker_socket() -> None:
    compose = Path("docker-compose.saas.yml").read_text(encoding="utf-8")
    coding = Path("docker-compose.coding.yml").read_text(encoding="utf-8")
    assert "/var/run/docker.sock" not in compose
    assert "/var/run/docker.sock:/var/run/docker.sock" in coding
    assert "LEARNING_WEB_CODING_ENABLED: \"false\"" in compose


def test_primary_navigation_views_have_render_targets() -> None:
    page = Path("server/web/index.html").read_text(encoding="utf-8")
    views = set(re.findall(r'data-view="([a-z-]+)"', page))
    for view in views:
        assert f'id="{view}-view"' in page, f"navigation view {view!r} has no render target"


def test_web_and_api_responses_include_browser_security_headers() -> None:
    client = TestClient(create_app())
    web = client.get("/web/")
    assert web.status_code == 200
    assert web.headers["x-content-type-options"] == "nosniff"
    assert web.headers["x-frame-options"] == "DENY"
    assert web.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert web.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=(), payment=()"
    assert "frame-ancestors 'none'" in web.headers["content-security-policy"]
    assert "object-src 'none'" in web.headers["content-security-policy"]
    assert "script-src 'self'" in web.headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" not in web.headers["content-security-policy"]

    api = client.get("/v1/me")
    assert api.status_code == 401
    assert api.headers["cache-control"] == "no-store"
    assert api.headers["x-content-type-options"] == "nosniff"

    app_script = client.get("/web/app.js")
    assert app_script.status_code == 200
    assert app_script.headers["cache-control"] == "no-cache"


def test_production_liveness_response_enables_hsts(monkeypatch) -> None:
    settings = ServerSettings(
        app_env="production",
        secret_key="s" * 32,
        database_url="postgresql+psycopg://user:password@host/database",
        object_storage_endpoint="https://storage.example.test",
        object_storage_access_key="access",
        object_storage_secret_key="secret",
        cors_origins="https://learn.example.test",
        redis_password="redis-secret-value-123",
        redis_url="redis://:redis-secret-value-123@redis:6379/0",
    )
    monkeypatch.setattr("server.main.get_server_settings", lambda: settings)
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
