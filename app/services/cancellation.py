from __future__ import annotations

from threading import Event


class OperationCancelled(RuntimeError):
    """Raised when a user or timeout cancels a long-running operation."""


class CancellationToken:
    """Thread-safe cancellation token shared by UI workers and async clients."""

    def __init__(self) -> None:
        self._event = Event()
        self.reason = ""

    def cancel(self, reason: str = "Cancelled by user") -> None:
        self.reason = reason
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self) -> None:
        self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OperationCancelled(self.reason or "Operation cancelled")
