from __future__ import annotations

import hashlib
from dataclasses import dataclass

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - exercised only before production install
    class RedisError(RuntimeError):
        pass

    class Redis:  # type: ignore[no-redef]
        @classmethod
        def from_url(cls, url: str, decode_responses: bool = True):
            raise RedisError("redis package is required for rate limiting")
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from server.config import ServerSettings


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int


class RedisRateLimiter:
    """Fixed-window limiter using Redis INCR + EXPIRE.

    The key contains a one-way hash of the client address and never stores raw
    IP addresses. Redis failures fail open only outside production; production
    rejects the request so the security control cannot silently disappear.
    """

    def __init__(self, settings: ServerSettings, client: Redis | None = None) -> None:
        self.settings = settings
        self.client = client

    def _client(self) -> Redis:
        if self.client is None:
            self.client = Redis.from_url(self.settings.redis_url, decode_responses=True)
        return self.client

    @staticmethod
    def client_key(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        host = forwarded or (request.client.host if request.client else "unknown")
        return hashlib.sha256(host.encode("utf-8")).hexdigest()[:32]

    def check(self, request: Request) -> RateLimitDecision:
        limit = self.settings.auth_rate_limit_requests if request.url.path.startswith("/v1/auth/") else self.settings.rate_limit_requests
        window = self.settings.auth_rate_limit_window_seconds if request.url.path.startswith("/v1/auth/") else self.settings.rate_limit_window_seconds
        bucket = int(__import__("time").time() // window)
        key = f"learning:ratelimit:{'auth' if request.url.path.startswith('/v1/auth/') else 'api'}:{self.client_key(request)}:{bucket}"
        try:
            client = self._client()
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, window + 1)
            return RateLimitDecision(count <= limit, max(0, limit - count), window - (int(__import__("time").time()) % window))
        except RedisError:
            if self.settings.app_env.lower() in {"production", "prod"}:
                raise
            return RateLimitDecision(True, limit, 0)

    def ping(self) -> bool:
        """Verify the shared Redis dependency used by production rate limits."""
        return bool(self._client().ping())


def rate_limit_response(decision: RateLimitDecision) -> Response:
    response = JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
    response.headers["Retry-After"] = str(decision.retry_after)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    return response
