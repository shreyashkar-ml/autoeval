import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, RepoPaths, read_json, utc_now_iso, write_json
from .providers import get_provider
from .tracker import completion_counts, load_feature_list, update_sub_task_status


@dataclass
class SessionResult:
    run_id: str
    session_number: int
    completed_sub_task_ids: list[str]
    context_ratio: float
    done_count: int
    total_count: int

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


def execute_session(
    paths: RepoPaths,
    run_id: str,
    task: str,
    provider_name: str = "codex",
) -> SessionResult:
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

    feature_payload = load_feature_list(feature_file)
    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "session_started",
            "run_id": run_id,
            "session_number": session_number,
            "provider": provider_name,
            "task": task,
        },
    )

    response = provider.run(task=task, feature_payload=feature_payload, session_number=session_number)

    for event in response.raw_events:
        _append_jsonl(events_file, {"ts": utc_now_iso(), **event})

    for task_id in response.completed_sub_task_ids:
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
            "done_count": done_count,
            "total_count": total_count,
        },
    )

    progress_block = (
        f"## Session {session_number}\n"
        f"- timestamp: {utc_now_iso()}\n"
        f"- completed: {response.completed_sub_task_ids or ['none']}\n"
        f"- done/total: {done_count}/{total_count}\n"
        f"- context_ratio: {response.context_ratio}\n\n"
    )
    _append_progress(progress_file, progress_block)

    meta["schema_version"] = SCHEMA_VERSION
    meta["provider"] = provider_name
    meta["session_count"] = session_number
    meta["last_context_ratio"] = response.context_ratio
    meta["last_completed_ids"] = response.completed_sub_task_ids
    meta["updated_at"] = utc_now_iso()
    write_json(meta_file, meta)

    return SessionResult(
        run_id=run_id,
        session_number=session_number,
        completed_sub_task_ids=response.completed_sub_task_ids,
        context_ratio=response.context_ratio,
        done_count=done_count,
        total_count=total_count,
    )
