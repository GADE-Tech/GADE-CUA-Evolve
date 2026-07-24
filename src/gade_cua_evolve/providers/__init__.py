"""Computer environment provider interfaces and implementations."""

from .base import AgentObservation, BaseComputerProvider, ExecutionResult
from .local_stub import LocalStubComputerProvider

__all__ = [
    "AgentObservation",
    "BaseComputerProvider",
    "ExecutionResult",
    "LocalStubComputerProvider",
]
