from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .config import SCHEMA_VERSION, RepoPaths, read_json, utc_now_iso, write_json
from .tracker import completion_counts

EvalCheck = Callable[[RepoPaths, str], dict[str, Any]]


def _run_dir(paths: RepoPaths, run_id: str) -> Path:
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _load_events(events_file: Path) -> list[dict[str, Any]]:
    if not events_file.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw_line in events_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _check_required_artifacts(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(paths, run_id)
    required = [
        run_dir / "events.jsonl",
        run_dir / "progress.md",
        run_dir / "session_meta.json",
        run_dir / "usage.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    return {
        "id": "required_artifacts",
        "passed": not missing,
        "severity": "error",
        "summary": "Required run artifacts exist",
        "evidence": {"missing": missing},
    }


def _check_action_lifecycle(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    events = _load_events(_run_dir(paths, run_id) / "events.jsonl")
    counts = {
        "action_requested": 0,
        "action_result": 0,
        "session_finished": 0,
        "provider_subagent_plan": 0,
    }
    for event in events:
        event_type = str(event.get("type", ""))
        if event_type in counts:
            counts[event_type] += 1
    passed = all(value > 0 for value in counts.values())
    return {
        "id": "action_lifecycle",
        "passed": passed,
        "severity": "error",
        "summary": "Action lifecycle and sub-agent planning events are present",
        "evidence": counts,
    }


def _check_feature_completion(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    done_count, total_count = completion_counts(paths.rpi_dir / "feature_list.json")
    return {
        "id": "feature_completion",
        "passed": total_count > 0 and done_count == total_count,
        "severity": "error",
        "summary": "Feature list is fully completed",
        "evidence": {
            "done_count": done_count,
            "total_count": total_count,
        },
    }


def _check_failed_actions(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    events = _load_events(_run_dir(paths, run_id) / "events.jsonl")
    failures = 0
    for event in events:
        if event.get("type") != "action_result":
            continue
        result = event.get("result", {})
        if isinstance(result, dict) and str(result.get("status", "")) in {"failed", "denied"}:
            failures += 1
    return {
        "id": "no_failed_actions",
        "passed": failures == 0,
        "severity": "error",
        "summary": "No denied/failed actions in final run trace",
        "evidence": {"failures": failures},
    }


def _check_reference_artifacts(paths: RepoPaths, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(paths, run_id)
    slack_file = run_dir / "communications" / "slack_messages.jsonl"
    github_file = run_dir / "vcs" / "github_operations.jsonl"

    def _has_data(path: Path) -> bool:
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())

    has_slack = _has_data(slack_file)
    has_github = _has_data(github_file)
    return {
        "id": "reference_artifacts",
        "passed": has_slack and has_github,
        "severity": "error",
        "summary": "Slack and GitHub operation artifacts are present",
        "evidence": {
            "slack_file": str(slack_file),
            "github_file": str(github_file),
            "has_slack": has_slack,
            "has_github": has_github,
        },
    }


def _normalize_check(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(result.get("id", "unknown_check")),
        "passed": bool(result.get("passed", False)),
        "severity": str(result.get("severity", "error")),
        "summary": str(result.get("summary", "")),
        "evidence": dict(result.get("evidence", {})),
    }


def default_eval_checks() -> list[EvalCheck]:
    return [
        _check_required_artifacts,
        _check_action_lifecycle,
        _check_feature_completion,
        _check_failed_actions,
        _check_reference_artifacts,
    ]


def run_eval_suite(
    paths: RepoPaths,
    run_id: str,
    profile: str = "default",
    extra_checks: list[EvalCheck] | None = None,
) -> dict[str, Any]:
    _run_dir(paths, run_id)
    checks = default_eval_checks() + list(extra_checks or [])

    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            raw_result = check(paths, run_id)
        except Exception as exc:
            raw_result = {
                "id": getattr(check, "__name__", "eval_check"),
                "passed": False,
                "severity": "error",
                "summary": "Eval check raised an exception",
                "evidence": {"error": str(exc)},
            }
        results.append(_normalize_check(raw_result))

    passed = all(item["passed"] for item in results)
    failures = [item["id"] for item in results if not item["passed"]]
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "profile": profile,
        "created_at": utc_now_iso(),
        "passed": passed,
        "checks": results,
        "summary": {
            "total_checks": len(results),
            "passed_checks": sum(1 for item in results if item["passed"]),
            "failed_checks": failures,
        },
    }
    write_json(paths.runs_dir / run_id / "evals" / "report.json", report)
    return report


def load_latest_eval_report(paths: RepoPaths, run_id: str) -> dict[str, Any] | None:
    report_file = paths.runs_dir / run_id / "evals" / "report.json"
    if not report_file.exists():
        return None
    return read_json(report_file, {})
