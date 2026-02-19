from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderResponse:
    completed_sub_task_ids: list[str]
    context_ratio: float
    summary: str
    raw_events: list[dict[str, Any]]


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    def run(self, task: str, feature_payload: dict[str, Any], session_number: int) -> ProviderResponse:
        """Execute one provider session and return structured response."""


class CodexProvider(ProviderAdapter):
    name = "codex"

    def run(self, task: str, feature_payload: dict[str, Any], session_number: int) -> ProviderResponse:
        pending = [
            item["id"]
            for item in feature_payload.get("sub_tasks", [])
            if not bool(item.get("status"))
        ]
        completed = [pending[0]] if pending else []
        # Placeholder until real provider telemetry is wired:
        # fixed representational value for "remaining context".
        context_ratio = 1.0
        summary = (
            f"session {session_number} processed task='{task}' completed={completed or ['none']}"
        )
        return ProviderResponse(
            completed_sub_task_ids=completed,
            context_ratio=context_ratio,
            summary=summary,
            raw_events=[
                {
                    "type": "provider_output",
                    "provider": self.name,
                    "session_number": session_number,
                    "summary": summary,
                }
            ],
        )


def get_provider(name: str) -> ProviderAdapter:
    key = name.strip().lower()
    if key == "codex":
        return CodexProvider()
    raise ValueError(f"unsupported provider: {name}")
