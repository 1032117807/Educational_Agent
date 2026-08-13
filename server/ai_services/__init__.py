"""Tenant-safe AI application services shared by HTTP and worker adapters."""

from server.ai_services.orchestration import run_ai_feature

__all__ = ["run_ai_feature"]
