"""Backward-compatible import path for the multi-agent supervisor."""

from ai.agents.orchestrator import LearningOrchestrator
from ai.agents.specialists import (
    LearningPlanSpecialist,
    QuestionSpecialist,
    ReportSpecialist,
    ResourceAnalysisSpecialist,
    SpecialistResult,
)

__all__ = [
    "LearningOrchestrator",
    "LearningPlanSpecialist",
    "QuestionSpecialist",
    "ReportSpecialist",
    "ResourceAnalysisSpecialist",
    "SpecialistResult",
]
