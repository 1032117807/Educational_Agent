"""Compatibility entry point for ``uvicorn server.api:app``."""

from server.main import app

__all__ = ["app"]
