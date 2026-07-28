"""Compatibility exports for domain services.

Concrete implementations live in focused service modules.
"""

from app.services.analytics import AnalyticsService
from app.services.assessment import QuestionService, ReviewService
from app.services.maintenance import JobService, MaintenanceService
from app.services.resources import ResourceService

__all__ = [
    "AnalyticsService",
    "JobService",
    "MaintenanceService",
    "QuestionService",
    "ResourceService",
    "ReviewService",
]
