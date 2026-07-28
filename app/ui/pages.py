"""Compatibility exports for core application pages."""

from app.ui.components import page_title, stat_card
from app.ui.courses_page import CoursesPage
from app.ui.dashboard_page import DashboardPage
from app.ui.plan_page import PlanPage
from app.ui.settings_page import SettingsPage

__all__ = [
    "CoursesPage",
    "DashboardPage",
    "PlanPage",
    "SettingsPage",
    "page_title",
    "stat_card",
]
