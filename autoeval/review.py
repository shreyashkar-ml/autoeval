from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, RepoPaths, read_json, utc_now_iso, write_json


def _review_dir(paths: RepoPaths, run_id: str) -> Path:
    path = paths.runs_dir / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_review(paths: RepoPaths, severity: str = "medium", run_id: str | None = None) -> dict[str, Any]:
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id") or "review_only"
    run_dir = _review_dir(paths, active_run)

    findings: list[dict[str, Any]] = []

    feature_file = paths.rpi_dir / "feature_list.json"
    feature_payload = read_json(feature_file, {"sub_tasks": []})
    for task in feature_payload.get("sub_tasks", []):
        if not bool(task.get("status")):
            findings.append(
                {
                    "severity": severity,
                    "file": str(feature_file),
                    "summary": f"Sub-task incomplete: {task.get('id')}",
                    "evidence": {"status": task.get("status"), "phase": task.get("phase")},
                }
            )

    events_file = run_dir / "events.jsonl"
    if not events_file.exists():
        findings.append(
            {
                "severity": "medium",
                "file": str(events_file),
                "summary": "No event log found for run",
                "evidence": {"exists": False},
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": active_run,
        "created_at": utc_now_iso(),
        "severity": severity,
        "findings": findings,
    }
    write_json(run_dir / "review.json", report)
    return report
