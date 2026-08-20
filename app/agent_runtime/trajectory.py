"""Inspectable Agent trajectory without hidden chain-of-thought."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TrajectoryEvent:
    event_type: str
    payload: dict[str, Any]


@dataclass
class AgentTrajectory:
    events: list[TrajectoryEvent] = field(default_factory=list)

    def add(self, event_type: str, **payload: Any) -> None:
        self.events.append(TrajectoryEvent(event_type, payload))

    def tool_observations(self) -> list[dict[str, Any]]:
        return [event.payload for event in self.events if event.event_type == "observation"]

    def context_events(self) -> list[dict[str, Any]]:
        """Expose only decision/action/observation summaries to the next model call."""
        return [{"type": event.event_type, **event.payload} for event in self.events[-20:]]
