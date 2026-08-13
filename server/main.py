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
            "embedding_mode": "local" if ai.embedding_local_files_only else "managed_or_downloaded",
            "embedding_model": ai.embedding_model,
        }

    return app


app = create_app()
