import json
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any

from .agent_contract import (
    ActionRequest,
    ActionResult,
    CompletionEnvelope,
    UsageTelemetry,
    build_task_envelope,
)
from .connectors import (
    map_tool_selector_to_profile,
    record_github_operation,
    record_slack_notification,
    resolve_runtime_profiles,
)
from .config import SCHEMA_VERSION, RepoPaths, read_json, utc_now_iso, write_json
from .hooks import (
    HOOK_ACTION_REQUESTED,
    HOOK_ACTION_RESULT,
    HOOK_SESSION_END,
    HOOK_SESSION_START,
    HookManager,
)
from .policy import PolicyEngine, RuntimeApprover
from .prompts import copy_spec_to_project, get_continuation_task, get_initializer_task, load_orchestrator_prompt
from .providers import get_provider
from .rpi import build_instruction_prompts, commit_rpi_artifacts, needs_rpi_bootstrap
from .security import validate_command
from .tracker import completion_counts, load_feature_list, update_sub_task_status

DANGEROUS_RUN_PATTERNS = (
    "rm -rf /",
    "mkfs",
    "shutdown",
    "reboot",
    ":(){:|:&};:",
)
RUN_SELECTOR_ALLOWLIST = {"build", "test", "cmd"}


@dataclass
class SessionResult:
    run_id: str
    session_number: int
    completed_sub_task_ids: list[str]
    context_ratio: float
    done_count: int
    total_count: int
    action_count: int
    usage: dict[str, Any]
    snapshot_file: str
    checkpoint_file: str

    @property
    def complete(self) -> bool:
        return self.total_count > 0 and self.done_count == self.total_count


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _append_progress(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def _resolve_repo_path(repo: Path, rel_path: str) -> Path:
    candidate = (repo / rel_path).resolve()
    if repo == candidate or repo in candidate.parents:
        return candidate
    raise ValueError(f"path is outside repository boundary: {rel_path}")


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...[truncated]"


def _run_shell_command(
    repo: Path,
    cmd: str,
    timeout_sec: int,
    max_output_chars: int = 40000,
) -> dict[str, Any]:
    lowered = cmd.lower()
    for pattern in DANGEROUS_RUN_PATTERNS:
        if pattern in lowered:
            raise ValueError(f"blocked dangerous command pattern: {pattern}")

    validation = validate_command(cmd)
    if not validation.allowed:
        raise ValueError(f"blocked by security policy: {validation.reason}")

    env = dict(os.environ)
    # This does not fully disable networking; it removes common proxy shortcuts.
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy"]:
        env.pop(key, None)
    env["AUTOEVAL_SANDBOX"] = "1"

    try:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "cmd": cmd,
            "timeout_sec": timeout_sec,
            "exit_code": None,
            "stdout": "",
            "stderr": "command timed out",
        }

    return {
        "status": "completed" if proc.returncode == 0 else "failed",
        "cmd": cmd,
        "timeout_sec": timeout_sec,
        "exit_code": proc.returncode,
        "stdout": _truncate_text(proc.stdout or "", max_output_chars),
        "stderr": _truncate_text(proc.stderr or "", max_output_chars),
    }


def _execute_action(
    paths: RepoPaths,
    run_id: str,
    request: ActionRequest,
    max_runtime_sec: int,
) -> ActionResult:
    started_at = utc_now_iso()
    output: dict[str, Any] = {}
    error: str | None = None
    status = "completed"

    try:
        if request.type == "read_file":
            rel_path = str(request.parameters.get("path", ""))
            max_bytes = int(request.parameters.get("max_bytes", 200000))
            file_path = _resolve_repo_path(paths.repo, rel_path)
            data = file_path.read_bytes()[:max_bytes]
            output = {
                "path": str(file_path.relative_to(paths.repo)),
                "bytes": len(data),
                "preview": data.decode("utf-8", errors="replace"),
            }
        elif request.type == "write_file":
            rel_path = str(request.parameters.get("path", ""))
            content = str(request.parameters.get("content", ""))
            file_path = _resolve_repo_path(paths.repo, rel_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            output = {
                "path": str(file_path.relative_to(paths.repo)),
                "bytes_written": len(content.encode("utf-8")),
            }
        elif request.type == "run":
            selector = str(request.selector or request.parameters.get("selector", "cmd"))
            if selector not in RUN_SELECTOR_ALLOWLIST:
                raise ValueError(f"unsupported run selector: {selector}")
            cmd = str(request.parameters.get("cmd", "")).strip()
            if not cmd:
                raise ValueError("run action requires non-empty cmd")
            requested_timeout = int(request.parameters.get("timeout_sec", max_runtime_sec))
            timeout_sec = max(1, min(requested_timeout, max_runtime_sec))
            result = _run_shell_command(
                repo=paths.repo,
                cmd=cmd,
                timeout_sec=timeout_sec,
            )
            output = {"selector": selector, **result}
            if result["status"] != "completed":
                status = "failed"
        elif request.type == "propose_patch":
            output = {
                "format": request.parameters.get("format", "unified_diff"),
                "patch": str(request.parameters.get("patch", "")),
            }
        elif request.type == "mcp_call":
            runtime_profiles = resolve_runtime_profiles(paths)
            selected = map_tool_selector_to_profile(
                paths=paths,
                selector=request.selector,
                namespace=request.parameters.get("namespace"),
            )
            namespace = str(request.parameters.get("namespace", ""))
            if namespace == "slack" and request.parameters.get("message"):
                slack_entry = record_slack_notification(
                    paths=paths,
                    run_id=run_id,
                    channel=str(request.parameters.get("channel", "new-channel")),
                    message=str(request.parameters.get("message", "")),
                    requested_by=request.requested_by,
                )
            else:
                slack_entry = None
            output = {
                "available_profiles": sorted(runtime_profiles.keys()),
                "count": len(runtime_profiles),
                "selected_profile": selected,
                "slack_notification": slack_entry,
            }
        elif request.type == "notify":
            channel = str(request.parameters.get("channel", "new-channel"))
            message = str(request.parameters.get("message", "")).strip()
            if not message:
                raise ValueError("notify action requires a non-empty message")
            output = record_slack_notification(
                paths=paths,
                run_id=run_id,
                channel=channel,
                message=message,
                requested_by=request.requested_by,
            )
        elif request.type == "github":
            operation = str(request.selector or request.parameters.get("operation", "commit"))
            summary = str(request.parameters.get("summary", "")).strip()
            if not summary:
                raise ValueError("github action requires a non-empty summary")
            output = record_github_operation(
                paths=paths,
                run_id=run_id,
                operation=operation,
                summary=summary,
                requested_by=request.requested_by,
                metadata=dict(request.parameters.get("metadata", {})),
            )
        else:
            output = {"note": "no-op action handler for MVP", "action_type": request.type}
    except Exception as exc:
        status = "failed"
        error = str(exc)

    finished_at = utc_now_iso()
    return ActionResult(
        action_id=request.action_id,
        status=status,
        output=output,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )


def _update_usage(
    paths: RepoPaths,
    run_id: str,
    session_number: int,
    provider_name: str,
    usage: dict[str, Any],
    action_count: int,
) -> None:
    usage_file = paths.runs_dir / run_id / "usage.json"
    payload = read_json(
        usage_file,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "sessions": [],
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "actions": 0,
            },
        },
    )

    normalized = UsageTelemetry(**usage).model_dump()
    payload.setdefault("sessions", []).append(
        {
            "session_number": session_number,
            "provider": provider_name,
            "usage": normalized,
            "actions": action_count,
            "created_at": utc_now_iso(),
        }
    )

    totals = payload.setdefault("totals", {})
    totals["input_tokens"] = int(totals.get("input_tokens", 0)) + int(normalized["input_tokens"])
    totals["output_tokens"] = int(totals.get("output_tokens", 0)) + int(normalized["output_tokens"])
    totals["total_tokens"] = int(totals.get("total_tokens", 0)) + int(normalized["total_tokens"])
    totals["estimated_cost_usd"] = float(totals.get("estimated_cost_usd", 0.0)) + float(
        normalized["estimated_cost_usd"]
    )
    totals["actions"] = int(totals.get("actions", 0)) + action_count
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = utc_now_iso()
    write_json(usage_file, payload)


def _write_snapshot(
    paths: RepoPaths,
    run_id: str,
    session_number: int,
    completion: CompletionEnvelope,
    done_count: int,
    total_count: int,
    action_count: int,
) -> Path:
    snapshot_file = paths.runs_dir / run_id / "snapshots" / f"session_{session_number}.json"
    write_json(
        snapshot_file,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "session_number": session_number,
            "done_count": done_count,
            "total_count": total_count,
            "action_count": action_count,
            "completion": completion.model_dump(),
            "created_at": utc_now_iso(),
        },
    )
    return snapshot_file


def _write_checkpoint(
    paths: RepoPaths,
    run_id: str,
    session_number: int,
    done_count: int,
    total_count: int,
) -> Path:
    checkpoint_file = paths.runs_dir / run_id / "checkpoints" / f"ckpt_session_{session_number}.json"
    write_json(
        checkpoint_file,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "session_number": session_number,
            "done_count": done_count,
            "total_count": total_count,
            "checkpoint_note": "groundwork checkpoint for rewind/fork workflows",
            "created_at": utc_now_iso(),
        },
    )
    return checkpoint_file


def execute_session(
    paths: RepoPaths,
    run_id: str,
    task: str,
    provider_name: str = "codex",
    runtime_approver: RuntimeApprover | None = None,
    hook_manager: HookManager | None = None,
    structured_output: bool = True,
) -> SessionResult:
    hook = hook_manager or HookManager()
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    events_file = run_dir / "events.jsonl"
    progress_file = run_dir / "progress.md"
    meta_file = run_dir / "session_meta.json"
    feature_file = paths.rpi_dir / "feature_list.json"

    meta = read_json(
        meta_file,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "provider": provider_name,
            "session_count": 0,
            "created_at": utc_now_iso(),
        },
    )
    session_number = int(meta.get("session_count", 0)) + 1
    provider = get_provider(provider_name)
    try:
        connection_payload = provider.connect(repo_root=str(paths.repo))
    except Exception as exc:
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "provider_connection_failed",
                "run_id": run_id,
                "session_number": session_number,
                "provider": provider_name,
                "error": str(exc),
            },
        )
        raise RuntimeError(f"provider connection failed ({provider_name}): {exc}") from exc
    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "provider_connected",
            "run_id": run_id,
            "session_number": session_number,
            "provider": provider_name,
            "connection": connection_payload,
        },
    )
    copy_spec_to_project(paths.repo)
    prompt_mode = "initializer" if session_number == 1 else "continuation"
    prompt_task = (
        get_initializer_task(paths.repo, task)
        if session_number == 1
        else get_continuation_task(paths.repo, task)
    )

    feature_payload = load_feature_list(feature_file)
    rpi_instructions = build_instruction_prompts(paths=paths, task=task)
    rpi_bootstrap_pending = needs_rpi_bootstrap(paths)
    task_envelope = build_task_envelope(
        run_id=run_id,
        session_number=session_number,
        task=prompt_task,
        feature_payload=feature_payload,
        provider_capabilities=getattr(provider, "capabilities", {}),
        rpi_instructions=rpi_instructions,
        requested_task=task,
        repo_root=str(paths.repo),
        rpi_bootstrap_pending=rpi_bootstrap_pending,
    )

    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "session_started",
            "run_id": run_id,
            "session_number": session_number,
            "provider": provider_name,
            "task": task,
            "prompt_mode": prompt_mode,
            "task_id": task_envelope.task_id,
            "contract_version": task_envelope.contract_version,
            "rpi_bootstrap_pending": rpi_bootstrap_pending,
            "rpi_instruction_templates": sorted(rpi_instructions.keys()),
        },
    )
    hook.emit(
        HOOK_SESSION_START,
        {
            "run_id": run_id,
            "session_number": session_number,
            "provider": provider_name,
            "task_envelope": task_envelope.model_dump(),
            "orchestrator_prompt": load_orchestrator_prompt(),
            "prompt_mode": prompt_mode,
        },
    )

    response = provider.run(
        task_envelope=task_envelope,
        feature_payload=feature_payload,
        session_number=session_number,
        structured_output=structured_output,
    )

    committed_rpi_artifacts: list[str] = []
    if response.structured_output is not None:
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "structured_output_parsed",
                "run_id": run_id,
                "session_number": session_number,
                "provider": provider_name,
                "payload": response.structured_output,
            },
        )
        if isinstance(response.structured_output, dict):
            rpi_artifacts = response.structured_output.get("rpi_artifacts")
            if isinstance(rpi_artifacts, dict):
                try:
                    committed_rpi_artifacts = commit_rpi_artifacts(paths, rpi_artifacts)
                except Exception as exc:
                    _append_jsonl(
                        events_file,
                        {
                            "ts": utc_now_iso(),
                            "type": "rpi_artifacts_commit_failed",
                            "run_id": run_id,
                            "session_number": session_number,
                            "provider": provider_name,
                            "error": str(exc),
                        },
                    )
                else:
                    if committed_rpi_artifacts:
                        _append_jsonl(
                            events_file,
                            {
                                "ts": utc_now_iso(),
                                "type": "rpi_artifacts_committed",
                                "run_id": run_id,
                                "session_number": session_number,
                                "provider": provider_name,
                                "artifacts": committed_rpi_artifacts,
                                "source": "provider",
                            },
                        )

    policy_engine = PolicyEngine(runtime_approver=runtime_approver)
    action_results: list[ActionResult] = []

    for index, raw_request in enumerate(response.action_requests):
        request = ActionRequest(
            action_id=f"{run_id}-s{session_number}-a{index + 1}",
            type=str(raw_request.get("type", "unknown")),
            selector=raw_request.get("selector"),
            parameters=dict(raw_request.get("parameters", {})),
            requested_by=str(raw_request.get("requested_by", "worker")),
        )

        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "action_requested",
                "run_id": run_id,
                "session_number": session_number,
                "request": request.model_dump(),
            },
        )
        hook.emit(
            HOOK_ACTION_REQUESTED,
            {
                "run_id": run_id,
                "session_number": session_number,
                "request": request.model_dump(),
            },
        )

        decision = policy_engine.evaluate(task_envelope, request)
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "action_approved" if decision.allowed else "action_denied",
                "run_id": run_id,
                "session_number": session_number,
                "request": request.model_dump(),
                "decision": decision.model_dump(),
            },
        )

        if decision.allowed:
            action_result = _execute_action(
                paths=paths,
                run_id=run_id,
                request=request,
                max_runtime_sec=task_envelope.context.constraints.max_runtime_sec,
            )
        else:
            now = utc_now_iso()
            action_result = ActionResult(
                action_id=request.action_id,
                status="denied",
                output={},
                error=decision.reason,
                started_at=now,
                finished_at=now,
            )

        action_results.append(action_result)
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "action_result",
                "run_id": run_id,
                "session_number": session_number,
                "result": action_result.model_dump(),
            },
        )
        hook.emit(
            HOOK_ACTION_RESULT,
            {
                "run_id": run_id,
                "session_number": session_number,
                "result": action_result.model_dump(),
            },
        )

    for event in response.raw_events:
        _append_jsonl(events_file, {"ts": utc_now_iso(), **event})

    blocked = any(item.status in {"denied", "failed"} for item in action_results)
    completed_ids = [] if blocked else list(response.completed_sub_task_ids)
    if blocked and response.completed_sub_task_ids:
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "completion_blocked",
                "run_id": run_id,
                "session_number": session_number,
                "reason": "action failure or denial",
                "requested_completed_ids": response.completed_sub_task_ids,
            },
        )

    for task_id in completed_ids:
        update_sub_task_status(feature_file, task_id, True)
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "sub_task_completed",
                "run_id": run_id,
                "session_number": session_number,
                "sub_task_id": task_id,
            },
        )

    done_count, total_count = completion_counts(feature_file)
    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "session_finished",
            "run_id": run_id,
            "session_number": session_number,
            "context_ratio": response.context_ratio,
            "action_count": len(action_results),
            "usage": UsageTelemetry(**response.usage).model_dump(),
            "done_count": done_count,
            "total_count": total_count,
        },
    )

    completion = CompletionEnvelope(
        completed_sub_task_ids=completed_ids,
        summary=response.summary,
        evidence={
            "raw_event_count": len(response.raw_events),
            "action_count": len(action_results),
        },
        unresolved_blockers=list(response.unresolved_blockers),
        proposed_diffs=list(response.proposed_diffs),
        context_ratio=response.context_ratio,
        usage=UsageTelemetry(**response.usage),
    )

    progress_block = (
        f"## Session {session_number}\n"
        f"- timestamp: {utc_now_iso()}\n"
        f"- completed: {completed_ids or ['none']}\n"
        f"- done/total: {done_count}/{total_count}\n"
        f"- actions: {len(action_results)}\n"
        f"- usage_tokens: {completion.usage.total_tokens}\n"
        f"- context_ratio: {response.context_ratio}\n\n"
    )
    _append_progress(progress_file, progress_block)

    meta["schema_version"] = SCHEMA_VERSION
    meta["provider"] = provider_name
    meta["session_count"] = session_number
    meta["last_context_ratio"] = response.context_ratio
    meta["last_completed_ids"] = completed_ids
    meta["last_usage"] = completion.usage.model_dump()
    meta["last_action_count"] = len(action_results)
    meta["contract_version"] = task_envelope.contract_version
    meta["updated_at"] = utc_now_iso()
    write_json(meta_file, meta)

    _update_usage(
        paths=paths,
        run_id=run_id,
        session_number=session_number,
        provider_name=provider_name,
        usage=response.usage,
        action_count=len(action_results),
    )
    snapshot_file = _write_snapshot(
        paths=paths,
        run_id=run_id,
        session_number=session_number,
        completion=completion,
        done_count=done_count,
        total_count=total_count,
        action_count=len(action_results),
    )
    checkpoint_file = _write_checkpoint(
        paths=paths,
        run_id=run_id,
        session_number=session_number,
        done_count=done_count,
        total_count=total_count,
    )
    hook.emit(
        HOOK_SESSION_END,
        {
            "run_id": run_id,
            "session_number": session_number,
            "done_count": done_count,
            "total_count": total_count,
            "actions": len(action_results),
            "usage": completion.usage.model_dump(),
            "rpi_artifacts": committed_rpi_artifacts,
        },
    )

    return SessionResult(
        run_id=run_id,
        session_number=session_number,
        completed_sub_task_ids=completed_ids,
        context_ratio=response.context_ratio,
        done_count=done_count,
        total_count=total_count,
        action_count=len(action_results),
        usage=completion.usage.model_dump(),
        snapshot_file=str(snapshot_file),
        checkpoint_file=str(checkpoint_file),
    )
