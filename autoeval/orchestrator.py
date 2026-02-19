import json
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, RepoPaths, ensure_repo_layout, read_json, touch_state, utc_now_iso, write_json
from .executor import SessionResult, execute_session
from .memory import add_compact_note, add_decision
from .migrations import run_migrations
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


def _write_metrics(paths: RepoPaths, run_id: str, sessions: int, stuck_count: int) -> dict[str, Any]:
    done_count, total_count = completion_counts(paths.rpi_dir / "feature_list.json")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "sessions": sessions,
        "phases_done": done_count,
        "phases_total": total_count,
        "stuck_count": stuck_count,
        "completed": done_count == total_count and total_count > 0,
        "updated_at": utc_now_iso(),
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

    metrics = _write_metrics(paths, active_run_id, sessions=sessions, stuck_count=stuck_count)
    return {
        "run_id": active_run_id,
        "metrics": metrics,
        "context_threshold": context_threshold,
        "provider": provider,
    }


def resume_task(
    paths: RepoPaths,
    task: str = "resume",
    provider: str = "codex",
    run_id: str | None = None,
    context_threshold: float = 0.6,
    max_sessions: int = 30,
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
    )


def status(paths: RepoPaths, run_id: str | None = None) -> dict[str, Any]:
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id")

    done_count, total_count = completion_counts(paths.rpi_dir / "feature_list.json")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": active_run,
        "provider": state.get("provider", "codex"),
        "done_count": done_count,
        "total_count": total_count,
        "completed": done_count == total_count and total_count > 0,
    }

    if active_run:
        metrics_file = paths.runs_dir / active_run / "metrics.json"
        if metrics_file.exists():
            payload["metrics"] = read_json(metrics_file, {})

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
        "created_at": utc_now_iso(),
        "status": "requested",
    }
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
