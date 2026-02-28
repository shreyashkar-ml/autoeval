from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import re
import subprocess
from threading import Thread
import time
from typing import Any

from .agent_contract import TaskEnvelope
from .config import utc_now_iso


@dataclass
class ProviderResponse:
    completed_sub_task_ids: list[str]
    context_ratio: float
    summary: str
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    action_requests: list[dict[str, Any]] = field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    proposed_diffs: list[str] = field(default_factory=list)
    unresolved_blockers: list[str] = field(default_factory=list)


class ProviderAdapter(ABC):
    name: str
    capabilities: dict[str, Any] = {}

    @abstractmethod
    def connect(self, repo_root: str | None = None) -> dict[str, Any]:
        """Validate provider connectivity before starting a worker session."""

    @abstractmethod
    def run(
        self,
        task_envelope: TaskEnvelope,
        feature_payload: dict[str, Any],
        session_number: int,
        structured_output: bool = True,
    ) -> ProviderResponse:
        """Execute one provider session and return structured response."""


def _parse_structured_output(value: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    if isinstance(parsed, dict):
        return parsed
    return {"raw": parsed}


def _codex_binary() -> str:
    return os.getenv("AUTOEVAL_CODEX_BIN", "codex")


def _codex_reasoning_effort() -> str | None:
    effort = os.getenv("AUTOEVAL_CODEX_REASONING_EFFORT", "medium").strip()
    return effort or None


def _codex_model() -> str | None:
    model = os.getenv("AUTOEVAL_CODEX_MODEL", "gpt-5.3-codex").strip()
    return model or None


def _codex_connection_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "connected": {"type": "boolean"},
            "provider": {"type": "string"},
        },
        "required": ["connected", "provider"],
        "additionalProperties": False,
    }


def _codex_bootstrap_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "summary": {"type": "string"},
            "context_ratio": {"type": "number"},
            "completed_sub_task_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "rpi_artifacts": {
                "type": "object",
                "properties": {
                    "research": {"type": "string"},
                    "plan": {"type": "string"},
                    "feature_list": {
                        "type": "object",
                        "properties": {
                            "schema_version": {"type": "integer"},
                            "template": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "version": {"type": "string"},
                                },
                                "required": ["id", "version"],
                                "additionalProperties": False,
                            },
                            "generated_at": {"type": "string"},
                            "sub_tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "phase_id": {"type": "string"},
                                        "phase": {"type": "string"},
                                        "sub_task_description": {"type": "string"},
                                        "criteria": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "status": {"type": "boolean"},
                                    },
                                    "required": [
                                        "id",
                                        "phase_id",
                                        "phase",
                                        "sub_task_description",
                                        "criteria",
                                        "status",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["schema_version", "template", "generated_at", "sub_tasks"],
                        "additionalProperties": False,
                    },
                },
                "required": ["research", "plan", "feature_list"],
                "additionalProperties": False,
            },
        },
        "required": [
            "provider",
            "summary",
            "context_ratio",
            "completed_sub_task_ids",
            "rpi_artifacts",
        ],
        "additionalProperties": False,
    }


def _codex_session_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "summary": {"type": "string"},
            "context_ratio": {"type": "number"},
            "completed_sub_task_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "action_requests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "selector": {"type": ["string", "null"]},
                        "requested_by": {"type": "string"},
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": ["string", "null"]},
                                "max_bytes": {"type": ["integer", "null"]},
                                "content": {"type": ["string", "null"]},
                                "selector": {"type": ["string", "null"]},
                                "cmd": {"type": ["string", "null"]},
                                "timeout_sec": {"type": ["integer", "null"]},
                                "channel": {"type": ["string", "null"]},
                                "message": {"type": ["string", "null"]},
                                "operation": {"type": ["string", "null"]},
                                "summary": {"type": ["string", "null"]},
                                "namespace": {"type": ["string", "null"]},
                                "metadata": {
                                    "type": "object",
                                    "properties": {
                                        "issue_id": {"type": ["string", "null"]},
                                        "files": {
                                            "type": ["array", "null"],
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["issue_id", "files"],
                                    "additionalProperties": False,
                                },
                            },
                            "required": [
                                "path",
                                "max_bytes",
                                "content",
                                "selector",
                                "cmd",
                                "timeout_sec",
                                "channel",
                                "message",
                                "operation",
                                "summary",
                                "namespace",
                                "metadata",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["type", "selector", "requested_by", "parameters"],
                    "additionalProperties": False,
                },
            },
            "proposed_diffs": {"type": "array", "items": {"type": "string"}},
            "unresolved_blockers": {"type": "array", "items": {"type": "string"}},
            "rpi_artifacts": {
                "type": "object",
                "properties": {
                    "research": {"type": ["string", "null"]},
                    "plan": {"type": ["string", "null"]},
                    "feature_list": {
                        "type": ["object", "null"],
                        "properties": {
                            "schema_version": {"type": "integer"},
                            "template": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "version": {"type": "string"},
                                },
                                "required": ["id", "version"],
                                "additionalProperties": False,
                            },
                            "generated_at": {"type": "string"},
                            "sub_tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "phase_id": {"type": "string"},
                                        "phase": {"type": "string"},
                                        "sub_task_description": {"type": "string"},
                                        "criteria": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "status": {"type": "boolean"},
                                    },
                                    "required": [
                                        "id",
                                        "phase_id",
                                        "phase",
                                        "sub_task_description",
                                        "criteria",
                                        "status",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["schema_version", "template", "generated_at", "sub_tasks"],
                        "additionalProperties": False,
                    },
                },
                "required": ["research", "plan", "feature_list"],
                "additionalProperties": False,
            },
            "usage": {
                "type": "object",
                "properties": {
                    "input_tokens": {"type": "integer"},
                    "output_tokens": {"type": "integer"},
                    "total_tokens": {"type": "integer"},
                    "estimated_cost_usd": {"type": "number"},
                },
                "required": [
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "estimated_cost_usd",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "provider",
            "summary",
            "context_ratio",
            "completed_sub_task_ids",
            "action_requests",
            "proposed_diffs",
            "unresolved_blockers",
            "rpi_artifacts",
            "usage",
        ],
        "additionalProperties": False,
    }


def _extract_requested_task(task_envelope: TaskEnvelope) -> str:
    requested = task_envelope.metadata.get("requested_task")
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    match = re.search(r"for task:\s*`([^`]+)`", task_envelope.goal)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return task_envelope.goal.strip()


def _load_rpi_instructions(task_envelope: TaskEnvelope) -> dict[str, str]:
    raw = task_envelope.metadata.get("rpi_instructions")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result


def _build_codex_bootstrap_prompt(
    task_envelope: TaskEnvelope,
    feature_payload: dict[str, Any],
) -> str:
    requested_task = _extract_requested_task(task_envelope)
    instructions = _load_rpi_instructions(task_envelope)
    research_instruction = instructions.get("research", "(missing research instruction)")
    plan_instruction = instructions.get("plan", "(missing plan instruction)")
    feature_instruction = instructions.get("feature_list", "(missing feature_list instruction)")
    return (
        "You are the worker agent for autoeval bootstrap.\n"
        "Generate repository-specific RPI artifacts.\n"
        "Return JSON only, matching the schema exactly.\n"
        "Do not include any keys beyond the schema.\n"
        "Research and plan must be repository-specific and based on direct inspection.\n"
        "Feature list sub_tasks must be verifiable and status=false initially.\n\n"
        f"Requested task: {requested_task}\n\n"
        "Current feature payload JSON:\n"
        f"{json.dumps(feature_payload, indent=2)}\n\n"
        "Instruction template: research\n"
        f"{research_instruction}\n\n"
        "Instruction template: plan\n"
        f"{plan_instruction}\n\n"
        "Instruction template: feature_list\n"
        f"{feature_instruction}\n"
    )


def _build_codex_session_prompt(
    task_envelope: TaskEnvelope,
    feature_payload: dict[str, Any],
    session_number: int,
) -> str:
    requested_task = _extract_requested_task(task_envelope)
    allowed_actions = [item.model_dump() for item in task_envelope.allowed_actions]
    instructions = _load_rpi_instructions(task_envelope)
    instruction_note = ""
    if instructions:
        instruction_note = (
            "\nRPI instruction templates:\n"
            + "\n\n".join(f"[{name}]\n{body}" for name, body in sorted(instructions.items()))
        )
    return (
        "You are the worker agent for the autoeval harness.\n"
        "Read the repository and produce a structured execution decision.\n"
        "Do not return prose outside JSON.\n"
        "Respect allowed actions, selectors, and constraints from the task envelope.\n"
        "Every action_request must include: type, selector, requested_by, parameters.\n"
        "For each action_request.parameters object, include every schema key and set unused keys to null.\n"
        "Always include `rpi_artifacts` in output.\n"
        "If task_envelope.metadata.rpi_bootstrap_pending is true, populate research/plan/feature_list.\n"
        "If task_envelope.metadata.rpi_bootstrap_pending is false, set research=null, plan=null, feature_list=null.\n"
        "Only mark completed_sub_task_ids when you also propose verification evidence via action_requests.\n\n"
        f"Session number: {session_number}\n"
        f"Requested task: {requested_task}\n\n"
        "Task envelope JSON:\n"
        f"{json.dumps(task_envelope.model_dump(), indent=2)}\n\n"
        "Current feature payload JSON:\n"
        f"{json.dumps(feature_payload, indent=2)}\n\n"
        "Allowed action schema examples:\n"
        f"{json.dumps(allowed_actions, indent=2)}\n"
        f"{instruction_note}\n"
    )


def _parse_json_object_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("codex protocol returned an empty final message")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
        if not fence:
            raise RuntimeError("codex protocol final message is not valid JSON")
        parsed = json.loads(fence.group(1))
    if not isinstance(parsed, dict):
        raise RuntimeError("codex protocol final message JSON must be an object")
    return parsed


class _CodexProtocolRuntime:
    def __init__(
        self,
        repo_root: Path,
        sandbox_mode: str,
        timeout_sec: int = 180,
    ) -> None:
        self.repo_root = repo_root
        self.sandbox_mode = sandbox_mode
        self.timeout_sec = timeout_sec
        self.reasoning_effort = _codex_reasoning_effort()
        self.model = _codex_model()
        self._next_id = 0
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr_lines: list[str] = []
        cmd = [_codex_binary(), "app-server", "--listen", "stdio://"]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(repo_root),
        )
        if self.proc.stdin is None or self.proc.stdout is None or self.proc.stderr is None:
            raise RuntimeError("failed to start codex app-server with stdio pipes")
        self._stdout_thread = Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw_line in self.proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self._queue.put({"_malformed_line": line})
                continue
            if isinstance(payload, dict):
                self._queue.put(payload)
        self._queue.put({"_eof": True})

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw_line in self.proc.stderr:
            line = raw_line.rstrip()
            if line:
                self.stderr_lines.append(line)

    def _send(self, payload: dict[str, Any]) -> None:
        if self.proc.poll() is not None:
            raise RuntimeError(f"codex app-server exited early (code={self.proc.returncode})")
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload))
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()

    def _next_request_id(self) -> str:
        self._next_id += 1
        return f"req-{self._next_id}"

    def _dequeue(self, timeout_sec: float) -> dict[str, Any]:
        try:
            payload = self._queue.get(timeout=timeout_sec)
        except queue.Empty as exc:
            raise TimeoutError("timed out waiting for codex protocol event") from exc
        if payload.get("_eof"):
            stderr = "\n".join(self.stderr_lines[-12:])
            raise RuntimeError(
                "codex app-server stream ended unexpectedly"
                + (f": {stderr}" if stderr else "")
            )
        if payload.get("_malformed_line"):
            raise RuntimeError(f"received malformed codex protocol line: {payload['_malformed_line']}")
        return payload

    def _send_error(self, request_id: Any, message: str, code: int = -32000) -> None:
        self._send({"id": request_id, "error": {"code": code, "message": message}})

    def _handle_server_request(self, payload: dict[str, Any]) -> None:
        method = str(payload.get("method", ""))
        request_id = payload.get("id")
        if request_id is None:
            return

        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            self._send({"id": request_id, "result": {"decision": "accept"}})
            return
        if method in {"execCommandApproval", "applyPatchApproval"}:
            self._send({"id": request_id, "result": {"decision": "approved"}})
            return
        if method == "item/tool/requestUserInput":
            self._send({"id": request_id, "result": {"answers": {}}})
            return
        if method == "item/tool/call":
            self._send(
                {
                    "id": request_id,
                    "result": {
                        "success": False,
                        "contentItems": [
                            {"type": "inputText", "text": "dynamic tool calls are disabled by harness"}
                        ],
                    },
                }
            )
            return

        self._send_error(request_id, f"unsupported server request: {method}")

    def request(
        self,
        method: str,
        params: dict[str, Any] | None,
        timeout_sec: int,
        notifications: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_request_id()
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for response to {method}")
            payload = self._dequeue(remaining)
            if "method" in payload and "id" in payload and "result" not in payload and "error" not in payload:
                self._handle_server_request(payload)
                continue
            if payload.get("id") == request_id and ("result" in payload or "error" in payload):
                if "error" in payload:
                    raise RuntimeError(f"codex protocol error for {method}: {payload['error']}")
                result = payload.get("result")
                if isinstance(result, dict):
                    return result
                if result is None:
                    return {}
                raise RuntimeError(f"codex protocol result for {method} is not an object")
            if notifications is not None and "method" in payload and "id" not in payload:
                notifications.append(payload)

    def initialize(self) -> None:
        self.request(
            method="initialize",
            params={
                "clientInfo": {"name": "autoeval-harness", "version": "1.0.0"},
                "capabilities": None,
            },
            timeout_sec=self.timeout_sec,
        )

    def start_thread(self) -> str:
        result = self.request(
            method="thread/start",
            params={
                "model": self.model,
                "modelProvider": None,
                "cwd": str(self.repo_root),
                "approvalPolicy": "never",
                "sandbox": self.sandbox_mode,
                "config": None,
                "baseInstructions": None,
                "developerInstructions": None,
                "personality": None,
                "ephemeral": True,
                "experimentalRawEvents": False,
                "persistExtendedHistory": False,
            },
            timeout_sec=self.timeout_sec,
        )
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError("thread/start response missing thread object")
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("thread/start response missing thread.id")
        return thread_id

    def run_turn(
        self,
        thread_id: str,
        prompt: str,
        output_schema: dict[str, Any],
        timeout_sec: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        notifications: list[dict[str, Any]] = []
        turn_start = self.request(
            method="turn/start",
            params={
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "cwd": str(self.repo_root),
                "approvalPolicy": "never",
                "sandboxPolicy": None,
                "model": self.model,
                "effort": self.reasoning_effort,
                "summary": None,
                "personality": None,
                "outputSchema": output_schema,
                "collaborationMode": None,
            },
            timeout_sec=timeout_sec,
            notifications=notifications,
        )
        turn = turn_start.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise RuntimeError("turn/start response missing turn.id")
        turn_id = str(turn["id"])

        deadline = time.monotonic() + timeout_sec
        last_agent_message = ""
        token_usage: dict[str, Any] = {}

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for turn completion")
            payload = self._dequeue(remaining)
            if "method" in payload and "id" in payload and "result" not in payload and "error" not in payload:
                self._handle_server_request(payload)
                continue
            if "method" not in payload or "id" in payload:
                continue
            notifications.append(payload)
            method = str(payload.get("method", ""))
            params = payload.get("params", {})
            if method == "item/completed" and isinstance(params, dict):
                item = params.get("item", {})
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        last_agent_message = text
            elif method == "thread/tokenUsage/updated" and isinstance(params, dict):
                usage_obj = params.get("tokenUsage")
                if isinstance(usage_obj, dict):
                    token_usage = usage_obj
            elif method == "turn/completed" and isinstance(params, dict):
                turn_obj = params.get("turn", {})
                if isinstance(turn_obj, dict) and str(turn_obj.get("id", "")) == turn_id:
                    break

        if not last_agent_message:
            thread_read = self.request(
                method="thread/read",
                params={"threadId": thread_id, "includeTurns": True},
                timeout_sec=min(30, timeout_sec),
                notifications=notifications,
            )
            thread_obj = thread_read.get("thread", {})
            if isinstance(thread_obj, dict):
                turns = thread_obj.get("turns", [])
                if isinstance(turns, list):
                    for turn_obj in turns:
                        if not isinstance(turn_obj, dict):
                            continue
                        if str(turn_obj.get("id", "")) != turn_id:
                            continue
                        items = turn_obj.get("items", [])
                        if not isinstance(items, list):
                            continue
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "agentMessage":
                                text = item.get("text")
                                if isinstance(text, str) and text.strip():
                                    last_agent_message = text

        payload = _parse_json_object_from_text(last_agent_message)
        usage = _usage_from_token_notification(token_usage)
        meta = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "stderr": list(self.stderr_lines),
            "notification_count": len(notifications),
        }
        return payload, usage, notifications, meta


def _usage_from_token_notification(token_usage: dict[str, Any]) -> dict[str, Any]:
    last = token_usage.get("last", {}) if isinstance(token_usage, dict) else {}
    total = token_usage.get("total", {}) if isinstance(token_usage, dict) else {}
    if not isinstance(last, dict):
        last = {}
    if not isinstance(total, dict):
        total = {}
    input_tokens = int(last.get("inputTokens", total.get("inputTokens", 0)) or 0)
    output_tokens = int(last.get("outputTokens", total.get("outputTokens", 0)) or 0)
    total_tokens = int(last.get("totalTokens", total.get("totalTokens", input_tokens + output_tokens)) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": 0.0,
    }


def _run_codex_protocol_json(
    repo_root: Path,
    prompt: str,
    output_schema: dict[str, Any],
    sandbox_mode: str = "workspace-write",
    timeout_sec: int = 600,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = _CodexProtocolRuntime(
        repo_root=repo_root,
        sandbox_mode=sandbox_mode,
        timeout_sec=min(timeout_sec, 180),
    )
    try:
        runtime.initialize()
        thread_id = runtime.start_thread()
        payload, usage, notifications, meta = runtime.run_turn(
            thread_id=thread_id,
            prompt=prompt,
            output_schema=output_schema,
            timeout_sec=timeout_sec,
        )
        return payload, {
            "usage": usage,
            "notifications": notifications,
            "stderr": runtime.stderr_lines,
            **meta,
        }
    finally:
        runtime.close()


class CodexProvider(ProviderAdapter):
    name = "codex"
    capabilities = {
        "structured_output": True,
        "action_planning": True,
        "subagents": True,
        "reference_style_orchestration": True,
    }

    def connect(self, repo_root: str | None = None) -> dict[str, Any]:
        repo = Path(repo_root or ".").expanduser().resolve()
        payload, meta = _run_codex_protocol_json(
            repo_root=repo,
            prompt=(
                "Connection check for autoeval harness.\n"
                "Return JSON with connected=true and provider='codex'."
            ),
            output_schema=_codex_connection_schema(),
            sandbox_mode="read-only",
            timeout_sec=120,
        )
        if not bool(payload.get("connected", False)):
            raise RuntimeError("codex protocol connection check did not return connected=true")
        return {
            "provider": str(payload.get("provider", "codex")),
            "connected": True,
            "transport": "codex-app-server-protocol",
            "mode": "live",
            "connected_at": utc_now_iso(),
            "repo_root": str(repo),
            "protocol_thread_id": meta.get("thread_id"),
            "protocol_turn_id": meta.get("turn_id"),
        }

    def run(
        self,
        task_envelope: TaskEnvelope,
        feature_payload: dict[str, Any],
        session_number: int,
        structured_output: bool = True,
    ) -> ProviderResponse:
        repo_root = Path(str(task_envelope.metadata.get("repo_root", "."))).expanduser().resolve()
        bootstrap_pending = bool(task_envelope.metadata.get("rpi_bootstrap_pending", False))

        if bootstrap_pending:
            prompt = _build_codex_bootstrap_prompt(task_envelope, feature_payload)
            output_schema = _codex_bootstrap_schema()
            sandbox_mode = "read-only"
            timeout_sec = 600
        else:
            prompt = _build_codex_session_prompt(task_envelope, feature_payload, session_number)
            output_schema = _codex_session_schema()
            sandbox_mode = "workspace-write"
            timeout_sec = 1200

        payload, meta = _run_codex_protocol_json(
            repo_root=repo_root,
            prompt=prompt,
            output_schema=output_schema,
            sandbox_mode=sandbox_mode,
            timeout_sec=timeout_sec,
        )

        completed_raw = payload.get("completed_sub_task_ids", [])
        completed = [str(item) for item in completed_raw] if isinstance(completed_raw, list) else []
        context_ratio_raw = payload.get("context_ratio", 1.0)
        context_ratio = float(context_ratio_raw) if isinstance(context_ratio_raw, (int, float)) else 1.0
        summary = str(payload.get("summary", "codex worker session completed"))
        action_requests_raw = payload.get("action_requests", [])
        action_requests = (
            action_requests_raw if isinstance(action_requests_raw, list) else []
        ) if not bootstrap_pending else []
        structured_payload = _parse_structured_output(payload if structured_output else None)

        rpi_payload = payload.get("rpi_artifacts")
        if not isinstance(rpi_payload, dict):
            raise RuntimeError("codex response missing required rpi_artifacts object")
        if bootstrap_pending:
            if not isinstance(rpi_payload.get("research"), str) or not isinstance(
                rpi_payload.get("plan"), str
            ):
                raise RuntimeError("codex bootstrap response missing research/plan artifacts")
            if not isinstance(rpi_payload.get("feature_list"), dict):
                raise RuntimeError("codex bootstrap response missing feature_list artifact")

        usage = meta.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}

        notifications = meta.get("notifications", [])
        if not isinstance(notifications, list):
            notifications = []

        return ProviderResponse(
            completed_sub_task_ids=completed,
            context_ratio=context_ratio,
            summary=summary,
            action_requests=action_requests,
            structured_output=structured_payload,
            usage={
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
                "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
            },
            raw_events=[
                {
                    "type": "provider_live_worker_session",
                    "provider": self.name,
                    "session_number": session_number,
                    "repo_root": str(repo_root),
                    "protocol_thread_id": meta.get("thread_id"),
                    "protocol_turn_id": meta.get("turn_id"),
                    "notification_count": len(notifications),
                    "summary": summary,
                },
                {
                    "type": "provider_subagent_plan",
                    "provider": self.name,
                    "session_number": session_number,
                    "source": "protocol_bootstrap" if bootstrap_pending else "protocol_session",
                },
            ],
            proposed_diffs=list(payload.get("proposed_diffs", []))
            if isinstance(payload.get("proposed_diffs", []), list)
            else [],
            unresolved_blockers=list(payload.get("unresolved_blockers", []))
            if isinstance(payload.get("unresolved_blockers", []), list)
            else [],
        )


class ClaudeCodeProvider(ProviderAdapter):
    name = "claude-code"
    capabilities = {
        "structured_output": True,
        "action_planning": True,
        "subagents": True,
        "reference_style_orchestration": True,
    }

    def connect(self, repo_root: str | None = None) -> dict[str, Any]:
        raise RuntimeError(
            "live claude-code provider integration is not implemented yet; choose a supported provider"
        )

    def run(
        self,
        task_envelope: TaskEnvelope,
        feature_payload: dict[str, Any],
        session_number: int,
        structured_output: bool = True,
    ) -> ProviderResponse:
        raise RuntimeError(
            "live claude-code provider integration is not implemented yet; choose a supported provider"
        )


def list_supported_providers() -> list[str]:
    return sorted(["codex", "claude-code"])


def provider_capability_matrix() -> dict[str, dict[str, Any]]:
    return {
        "codex": dict(CodexProvider.capabilities),
        "claude-code": dict(ClaudeCodeProvider.capabilities),
    }


def get_provider(name: str) -> ProviderAdapter:
    key = name.strip().lower()
    if key in {"claude", "claude_code"}:
        key = "claude-code"

    if key == "codex":
        return CodexProvider()
    if key == "claude-code":
        return ClaudeCodeProvider()
    raise ValueError(f"unsupported provider: {name}")
