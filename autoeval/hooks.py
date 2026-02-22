from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

HookCallback = Callable[[dict[str, Any]], None]

HOOK_SESSION_START = "session_start"
HOOK_SESSION_END = "session_end"
HOOK_ACTION_REQUESTED = "action_requested"
HOOK_ACTION_RESULT = "action_result"


class HookManager:
    def __init__(self) -> None:
        self._callbacks: dict[str, list[HookCallback]] = defaultdict(list)

    def register(self, hook_name: str, callback: HookCallback) -> None:
        self._callbacks[hook_name].append(callback)

    def emit(self, hook_name: str, payload: dict[str, Any]) -> None:
        for callback in self._callbacks.get(hook_name, []):
            callback(payload)

