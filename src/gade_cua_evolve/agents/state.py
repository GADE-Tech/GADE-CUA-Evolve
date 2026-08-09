"""State owned by an agent across one task."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentState:
    actions: list[str] = field(default_factory=list)
    responses: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    feedbacks: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.actions.clear()
        self.responses.clear()
        self.screenshots.clear()
        self.messages.clear()
        self.feedbacks.clear()

    def history_window(self, size: int) -> list[tuple[str, str]]:
        """Return screenshot/response pairs preceding the current screenshot."""
        count = min(size, len(self.responses))
        if count == 0:
            return []
        response_start = len(self.responses) - count
        screenshots = self.screenshots[response_start : response_start + count]
        return list(zip(screenshots, self.responses[response_start:], strict=True))
