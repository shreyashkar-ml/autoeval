from pathlib import Path

from .config import RepoPaths, utc_now_iso


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        path.write_text(line, encoding="utf-8")


def add_compact_note(paths: RepoPaths, run_id: str, note: str) -> None:
    note_file = paths.memory_dir / "compact_notes.md"
    _append_line(note_file, f"- {utc_now_iso()} run={run_id} {note}\n")


def add_decision(paths: RepoPaths, run_id: str, decision: str) -> None:
    decision_file = paths.memory_dir / "decisions.md"
    _append_line(decision_file, f"- {utc_now_iso()} run={run_id} {decision}\n")
