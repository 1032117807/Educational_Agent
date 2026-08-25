from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from server.config import get_server_settings
from server.db import check_database
from server.routers import router
from server.rate_limit import RedisRateLimiter, rate_limit_response
from server.storage import S3ObjectStorage


def create_app() -> FastAPI:
    settings = get_server_settings()
    app = FastAPI(title="Personal Learning API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    limiter = RedisRateLimiter(settings)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if not settings.rate_limit_enabled or request.method in {"OPTIONS", "HEAD"} or request.url.path.startswith("/health/"):
                return await call_next(request)
            try:
                decision = limiter.check(request)
            except Exception:
                if settings.app_env.lower() in {"production", "prod"}:
                    return JSONResponse(status_code=503, content={"detail": "rate limiter unavailable"})
                return await call_next(request)
            if not decision.allowed:
                return rate_limit_response(decision)
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            return response

    app.add_middleware(RateLimitMiddleware)

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        """Apply one safe browser policy to both the web shell and the API."""

        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Content-Security-Policy", (
                "default-src 'self'; base-uri 'self'; object-src 'none'; "
                "frame-ancestors 'none'; form-action 'self'; connect-src 'self'; "
                "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self'"
            ))
            # API responses can contain learning history and bearer-authenticated
            # data. Do not permit browsers or intermediaries to retain them.
            if request.url.path.startswith("/v1/"):
                response.headers.setdefault("Cache-Control", "no-store")
            # The shell points at mutable application scripts. Revalidate them
            # on each navigation so a deployment never leaves a user on an old
            # learning workflow merely because a query version was missed.
            if request.url.path in {"/web/", "/web/index.html", "/web/app.js", "/web/agent-runtime.js", "/web/mathjax-config.js"}:
                response.headers.setdefault("Cache-Control", "no-cache")
            if settings.app_env.lower() in {"production", "prod"}:
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            return response

    # Add last so even rate-limit and error responses receive these headers.
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(router)
    web_directory = Path(__file__).with_name("web")
    app.mount("/web", StaticFiles(directory=web_directory, html=True), name="web")

    @app.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        try:
            available = check_database(settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        if not available:
            raise HTTPException(status_code=503, detail="database unavailable")
        if settings.app_env.lower() in {"production", "prod"}:
            try:
                if not limiter.ping():
                    raise RuntimeError("Redis ping returned false")
            except Exception as exc:
                raise HTTPException(status_code=503, detail="redis unavailable") from exc
            try:
                if not S3ObjectStorage(settings).check():
                    raise RuntimeError("object storage check returned false")
            except Exception as exc:
                raise HTTPException(status_code=503, detail="object storage unavailable") from exc
        return {"status": "ready"}

    @app.get("/health/config", tags=["health"])
    def configuration() -> dict[str, object]:
        """Non-secret deployment diagnostics for operators."""
        from ai.config import get_ai_settings
        ai = get_ai_settings()
        return {
            "environment": settings.app_env,
            "database_configured": "change-me" not in settings.database_url,
            "object_storage_configured": bool(settings.object_storage_endpoint and settings.object_storage_access_key and settings.object_storage_secret_key),
            "chat_model_configured": bool(ai.enabled and ai.api_key.strip()),
            "rate_limit_enabled": settings.rate_limit_enabled,
            "web_coding_enabled": settings.web_coding_enabled,
            "embedding_mode": "local" if ai.embedding_local_files_only else "managed_or_downloaded",
            "embedding_model": ai.embedding_model,
        }

    return app


app = create_app()
