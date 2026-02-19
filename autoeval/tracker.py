from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, read_json, utc_now_iso, write_json

IMMUTABLE_FIELDS = ("phase", "sub_task_description", "criteria")


def load_feature_list(feature_file: Path) -> dict[str, Any]:
    return read_json(feature_file, {"schema_version": SCHEMA_VERSION, "sub_tasks": []})


def save_feature_list(feature_file: Path, payload: dict[str, Any]) -> None:
    payload["schema_version"] = SCHEMA_VERSION
    write_json(feature_file, payload)


def _tasks_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in payload.get("sub_tasks", [])}


def assert_status_only_mutation(before: dict[str, Any], after: dict[str, Any]) -> None:
    before_ids = [item["id"] for item in before.get("sub_tasks", [])]
    after_ids = [item["id"] for item in after.get("sub_tasks", [])]
    if before_ids != after_ids:
        raise ValueError("sub_task ids/order cannot change")

    before_tasks = _tasks_by_id(before)
    after_tasks = _tasks_by_id(after)

    for task_id in before_ids:
        old = before_tasks[task_id]
        new = after_tasks[task_id]
        for field in IMMUTABLE_FIELDS:
            if old.get(field) != new.get(field):
                raise ValueError(f"immutable field changed for {task_id}: {field}")
        old_keys = set(old.keys()) - {"status"}
        new_keys = set(new.keys()) - {"status"}
        if old_keys != new_keys:
            raise ValueError(f"non-status fields changed for {task_id}")


def update_sub_task_status(feature_file: Path, task_id: str, status: bool) -> dict[str, Any]:
    payload = load_feature_list(feature_file)
    found = False
    for task in payload.get("sub_tasks", []):
        if task.get("id") == task_id:
            task["status"] = bool(status)
            found = True
            break
    if not found:
        raise KeyError(f"unknown sub task: {task_id}")
    save_feature_list(feature_file, payload)
    return payload


def all_completed(feature_file: Path) -> bool:
    payload = load_feature_list(feature_file)
    tasks = payload.get("sub_tasks", [])
    return bool(tasks) and all(bool(task.get("status")) for task in tasks)


def completion_counts(feature_file: Path) -> tuple[int, int]:
    payload = load_feature_list(feature_file)
    done = sum(1 for task in payload.get("sub_tasks", []) if task.get("status"))
    total = len(payload.get("sub_tasks", []))
    return done, total


def _next_rebaseline_file(feature_file: Path) -> Path:
    rpi_dir = feature_file.parent
    numbers = []
    for item in rpi_dir.glob("feature_list.v*.json"):
        stem = item.stem
        try:
            numbers.append(int(stem.split(".v", 1)[1]))
        except (IndexError, ValueError):
            continue
    next_number = max(numbers, default=0) + 1
    return rpi_dir / f"feature_list.v{next_number}.json"


def rebaseline_feature_list(
    feature_file: Path,
    candidate_payload: dict[str, Any],
    reviewer: str,
    change_note: str,
) -> Path:
    out_file = _next_rebaseline_file(feature_file)
    payload = dict(candidate_payload)
    payload["schema_version"] = SCHEMA_VERSION
    payload["rebaseline"] = {
        "reviewer": reviewer,
        "change_note": change_note,
        "created_at": utc_now_iso(),
        "source_file": str(feature_file),
    }
    write_json(out_file, payload)

    notes_file = feature_file.parent / "rebaseline_notes.md"
    note = (
        f"- {utc_now_iso()} reviewer={reviewer} file={out_file.name} note={change_note}\n"
    )
    if notes_file.exists():
        with notes_file.open("a", encoding="utf-8") as handle:
            handle.write(note)
    else:
        notes_file.write_text("# Rebaseline Notes\n\n" + note, encoding="utf-8")

    return out_file
