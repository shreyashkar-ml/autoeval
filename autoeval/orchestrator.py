import json
from pathlib import Path
import shutil
from typing import Any

from .config import SCHEMA_VERSION, RepoPaths, ensure_repo_layout, read_json, touch_state, utc_now_iso, write_json
from .evals import EvalCheck, run_eval_suite
from .executor import SessionResult, execute_session
from .hooks import HookManager
from .memory import add_compact_note, add_decision
from .migrations import run_migrations
from .policy import RuntimeApprover
from .providers import provider_capability_matrix
from .rpi import init_rpi_artifacts, is_rpi_initialized
from .tracker import all_completed, completion_counts


def _append_event(run_dir: Path, payload: dict[str, Any]) -> None:
    event_file = run_dir / "events.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    with event_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": utc_now_iso(), **payload}, sort_keys=True))
        handle.write("\n")


def _next_run_id(paths: RepoPaths) -> str:
    token = utc_now_iso().replace(":", "").replace("-", "").replace("+", "_")
    return f"run_{token}"


def _usage_totals(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    usage_file = paths.runs_dir / run_id / "usage.json"
    if not usage_file.exists():
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "actions": 0,
        }
    payload = read_json(usage_file, {})
    totals = payload.get("totals", {})
    return {
        "input_tokens": int(totals.get("input_tokens", 0)),
        "output_tokens": int(totals.get("output_tokens", 0)),
        "total_tokens": int(totals.get("total_tokens", 0)),
        "estimated_cost_usd": float(totals.get("estimated_cost_usd", 0.0)),
        "actions": int(totals.get("actions", 0)),
    }


def _write_metrics(
    paths: RepoPaths,
    run_id: str,
    sessions: int,
    stuck_count: int,
    completed_override: bool | None = None,
    eval_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    done_count, total_count = completion_counts(paths.rpi_dir / "feature_list.json")
    usage = _usage_totals(paths, run_id)
    completed = done_count == total_count and total_count > 0
    if completed_override is not None:
        completed = bool(completed_override)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "sessions": sessions,
        "phases_done": done_count,
        "phases_total": total_count,
        "stuck_count": stuck_count,
        "completed": completed,
        "usage": usage,
        "updated_at": utc_now_iso(),
    }
    if eval_report is not None:
        payload["eval"] = {
            "passed": bool(eval_report.get("passed", False)),
            "profile": str(eval_report.get("profile", "default")),
            "report_file": str(paths.runs_dir / run_id / "evals" / "report.json"),
        }
    write_json(paths.runs_dir / run_id / "metrics.json", payload)
    return payload


def run_task(
    paths: RepoPaths,
    task: str,
    provider: str = "codex",
    run_id: str | None = None,
    context_threshold: float = 0.6,
    max_sessions: int = 30,
    runtime_approver: RuntimeApprover | None = None,
    hook_manager: HookManager | None = None,
    structured_output: bool = True,
    eval_profile: str = "default",
    require_eval_pass: bool = True,
    eval_checks: list[EvalCheck] | None = None,
) -> dict[str, Any]:
    ensure_repo_layout(paths)
    run_migrations(paths)

    if not is_rpi_initialized(paths):
        init_rpi_artifacts(paths, task=task)

    active_run_id = run_id or _next_run_id(paths)
    run_dir = paths.runs_dir / active_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    touch_state(paths, last_run_id=active_run_id, provider=provider)

    no_progress = 0
    stuck_count = 0
    sessions = 0

    feature_file = paths.rpi_dir / "feature_list.json"
    while not all_completed(feature_file):
        before_done, _ = completion_counts(feature_file)
        result: SessionResult = execute_session(
            paths=paths,
            run_id=active_run_id,
            task=task,
            provider_name=provider,
            runtime_approver=runtime_approver,
            hook_manager=hook_manager,
            structured_output=structured_output,
        )
        sessions += 1

        add_compact_note(
            paths,
            active_run_id,
            f"session={result.session_number} done={result.done_count}/{result.total_count}",
        )

        # context_ratio means remaining context; rollover when remaining is low.
        if result.context_ratio <= context_threshold:
            add_decision(
                paths,
                active_run_id,
                (
                    f"context remaining ratio {result.context_ratio} reached threshold "
                    f"{context_threshold}; rollover"
                ),
            )
            _append_event(
                run_dir,
                {
                    "type": "context_rollover",
                    "run_id": active_run_id,
                    "session_number": result.session_number,
                    "context_ratio": result.context_ratio,
                    "threshold": context_threshold,
                },
            )

        after_done = result.done_count
        if after_done == before_done:
            no_progress += 1
        else:
            no_progress = 0

        if no_progress >= 3:
            stuck_count += 1
            _append_event(
                run_dir,
                {
                    "type": "stuck_detected",
                    "run_id": active_run_id,
                    "session_number": result.session_number,
                    "reason": "no progress in 3 consecutive sessions",
                },
            )
            break

        if result.complete:
            break

        if sessions >= max_sessions:
            _append_event(
                run_dir,
                {
                    "type": "max_sessions_reached",
                    "run_id": active_run_id,
                    "max_sessions": max_sessions,
                },
            )
            break

    eval_report: dict[str, Any] | None = None
    completion_candidate = all_completed(feature_file)
    completed_override: bool | None = None

    if completion_candidate:
        eval_report = run_eval_suite(
            paths=paths,
            run_id=active_run_id,
            profile=eval_profile,
            extra_checks=eval_checks,
        )
        _append_event(
            run_dir,
            {
                "type": "eval_completed",
                "run_id": active_run_id,
                "profile": eval_profile,
                "passed": bool(eval_report.get("passed", False)),
            },
        )
        if require_eval_pass and not bool(eval_report.get("passed", False)):
            completed_override = False
            add_decision(
                paths,
                active_run_id,
                "evaluation gate failed; run marked incomplete until eval checks pass",
            )
            _append_event(
                run_dir,
                {
                    "type": "eval_gate_blocked_completion",
                    "run_id": active_run_id,
                    "profile": eval_profile,
                },
            )

    metrics = _write_metrics(
        paths,
        active_run_id,
        sessions=sessions,
        stuck_count=stuck_count,
        completed_override=completed_override,
        eval_report=eval_report,
    )
    return {
        "run_id": active_run_id,
        "metrics": metrics,
        "context_threshold": context_threshold,
        "provider": provider,
        "eval": eval_report,
    }


def resume_task(
    paths: RepoPaths,
    task: str = "resume",
    provider: str = "codex",
    run_id: str | None = None,
    context_threshold: float = 0.6,
    max_sessions: int = 30,
    runtime_approver: RuntimeApprover | None = None,
    hook_manager: HookManager | None = None,
    structured_output: bool = True,
    eval_profile: str = "default",
    require_eval_pass: bool = True,
    eval_checks: list[EvalCheck] | None = None,
) -> dict[str, Any]:
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id")
    if not active_run:
        raise ValueError("no previous run found")
    return run_task(
        paths=paths,
        task=task,
        provider=provider,
        run_id=active_run,
        context_threshold=context_threshold,
        max_sessions=max_sessions,
        runtime_approver=runtime_approver,
        hook_manager=hook_manager,
        structured_output=structured_output,
        eval_profile=eval_profile,
        require_eval_pass=require_eval_pass,
        eval_checks=eval_checks,
    )


def status(paths: RepoPaths, run_id: str | None = None) -> dict[str, Any]:
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id")

    done_count, total_count = completion_counts(paths.rpi_dir / "feature_list.json")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": state.get("contract_version", "1.0"),
        "run_id": active_run,
        "provider": state.get("provider", "codex"),
        "provider_capabilities": provider_capability_matrix().get(state.get("provider", "codex"), {}),
        "done_count": done_count,
        "total_count": total_count,
        "completed": done_count == total_count and total_count > 0,
    }

    if active_run:
        metrics_file = paths.runs_dir / active_run / "metrics.json"
        if metrics_file.exists():
            payload["metrics"] = read_json(metrics_file, {})
        usage_file = paths.runs_dir / active_run / "usage.json"
        if usage_file.exists():
            payload["usage"] = read_json(usage_file, {}).get("totals", {})

    return payload


def intervene(paths: RepoPaths, reason: str, run_id: str | None = None) -> dict[str, Any]:
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id") or _next_run_id(paths)
    run_dir = paths.runs_dir / active_run
    run_dir.mkdir(parents=True, exist_ok=True)

    intervention_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": active_run,
        "reason": reason,
        "latest_snapshot": None,
        "created_at": utc_now_iso(),
        "status": "requested",
    }
    snapshots_dir = run_dir / "snapshots"
    if snapshots_dir.exists():
        latest = sorted(snapshots_dir.glob("session_*.json"))
        if latest:
            intervention_payload["latest_snapshot"] = str(latest[-1])
    write_json(run_dir / "intervention.json", intervention_payload)
    _append_event(
        run_dir,
        {
            "type": "intervention_requested",
            "run_id": active_run,
            "reason": reason,
        },
    )

    return intervention_payload


def fork_run(paths: RepoPaths, source_run_id: str, target_run_id: str | None = None) -> dict[str, Any]:
    source_dir = paths.runs_dir / source_run_id
    if not source_dir.exists():
        raise ValueError(f"source run does not exist: {source_run_id}")

    active_target = target_run_id or f"{source_run_id}_fork_{utc_now_iso().replace(':', '')}"
    target_dir = paths.runs_dir / active_target
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in [
        "events.jsonl",
        "progress.md",
        "session_meta.json",
        "usage.json",
        "metrics.json",
    ]:
        source_file = source_dir / name
        if source_file.exists():
            shutil.copy2(source_file, target_dir / name)

    for dirname in ["snapshots", "checkpoints"]:
        src = source_dir / dirname
        dst = target_dir / dirname
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_run_id": source_run_id,
        "target_run_id": active_target,
        "created_at": utc_now_iso(),
    }
    write_json(target_dir / "fork.json", payload)
    _append_event(
        target_dir,
        {
            "type": "run_forked",
            "source_run_id": source_run_id,
            "target_run_id": active_target,
        },
    )
    touch_state(paths, last_run_id=active_target)
    return payload
