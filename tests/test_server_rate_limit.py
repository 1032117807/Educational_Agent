from __future__ import annotations

from types import SimpleNamespace

import pytest
from server.config import ServerSettings
from server.rate_limit import RedisError, RedisRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    def ping(self) -> bool:
        return True


class BrokenRedis:
    def incr(self, key: str) -> int:
        raise RedisError("unavailable")


def request(path: str, ip: str = "203.0.113.5") -> SimpleNamespace:
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        headers={},
        client=SimpleNamespace(host=ip),
    )


def test_rate_limiter_enforces_request_limit_and_hashes_client_address() -> None:
    settings = ServerSettings(rate_limit_requests=2, rate_limit_window_seconds=60)
    limiter = RedisRateLimiter(settings, client=FakeRedis())
    assert limiter.check(request("/v1/courses")).allowed
    assert limiter.check(request("/v1/courses")).allowed
    decision = limiter.check(request("/v1/courses"))
    assert not decision.allowed
    assert decision.remaining == 0
    assert "203.0.113.5" not in next(iter(limiter.client.values))


def test_auth_limit_is_separate_and_stricter() -> None:
    settings = ServerSettings(rate_limit_requests=20, auth_rate_limit_requests=1, auth_rate_limit_window_seconds=60)
    limiter = RedisRateLimiter(settings, client=FakeRedis())
    assert limiter.check(request("/v1/auth/login")).allowed
    assert not limiter.check(request("/v1/auth/login")).allowed
    assert limiter.check(request("/v1/courses")).allowed


def test_production_raises_when_redis_is_unavailable() -> None:
    settings = ServerSettings(
        app_env="production",
        secret_key="x" * 32,
        database_url="postgresql+psycopg://user:password@host/database",
        object_storage_endpoint="https://storage.example.test",
        object_storage_access_key="access",
        object_storage_secret_key="secret",
        cors_origins="https://learn.example.test",
        redis_password="redis-secret-value-123",
        redis_url="redis://:redis-secret-value-123@redis:6379/0",
    )
    with pytest.raises(RedisError):
        RedisRateLimiter(settings, client=BrokenRedis()).check(request("/v1/courses"))


def test_ping_checks_the_shared_redis_client() -> None:
    assert RedisRateLimiter(ServerSettings(), client=FakeRedis()).ping() is True


def test_public_proxy_uses_caddy_safe_forwarding_defaults() -> None:
    caddyfile = open("docker/caddy/Caddyfile", encoding="utf-8").read()
    assert "\tlog\n" in caddyfile
    assert "reverse_proxy api:8000" in caddyfile
    assert "header_up X-Forwarded" not in caddyfile
