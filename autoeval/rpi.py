from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, RepoPaths, ensure_repo_layout, read_json, utc_now_iso, write_json

TEMPLATE_META = {
    "rpi_research": {"id": "rpi_research", "version": "1.0.0", "file": "rpi_research.md"},
    "rpi_plan": {"id": "rpi_plan", "version": "1.0.0", "file": "rpi_plan.md"},
    "rpi_feature_list": {
        "id": "rpi_feature_list",
        "version": "1.0.0",
        "file": "rpi_feature_list.md",
    },
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def load_template(name: str) -> str:
    meta = TEMPLATE_META[name]
    template_file = _template_dir() / meta["file"]
    return template_file.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    raw = load_template(name)
    return raw.format_map(_SafeDict(context))


def repo_snapshot(repo: Path, max_depth: int = 3) -> str:
    lines: list[str] = []
    base_depth = len(repo.parts)
    for path in sorted(repo.rglob("*")):
        if ".git" in path.parts or ".autoeval" in path.parts:
            continue
        depth = len(path.parts) - base_depth
        if depth > max_depth:
            continue
        rel = path.relative_to(repo)
        prefix = "  " * max(depth - 1, 0)
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{prefix}- {rel}{suffix}")
    return "\n".join(lines) if lines else "- (empty repo snapshot)"


def _default_feature_list() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "template": TEMPLATE_META["rpi_feature_list"],
        "generated_at": utc_now_iso(),
        "sub_tasks": [
            {
                "id": "phase1_rpi_init_engine",
                "phase": "Phase 1",
                "sub_task_description": "RPI initialization engine",
                "criteria": [
                    "Create research.md, plan.md, feature_list.json",
                    "Record template id/version metadata",
                    "Do not overwrite existing user-managed files on rerun",
                ],
                "status": False,
            },
            {
                "id": "phase2_codex_execution_loop",
                "phase": "Phase 2",
                "sub_task_description": "Single-provider execution with resume",
                "criteria": [
                    "Write events.jsonl/progress.md/session_meta.json",
                    "Resume runs continue from last state",
                ],
                "status": False,
            },
            {
                "id": "phase3_mcp_and_browser_mvp",
                "phase": "Phase 3",
                "sub_task_description": "MCP lifecycle and browser evidence",
                "criteria": [
                    "Manage profiles in user and project scope",
                    "Persist preflight health snapshots",
                    "Write browser artifacts for scenario execution",
                ],
                "status": False,
            },
            {
                "id": "phase4_reliability_intervention_review",
                "phase": "Phase 4",
                "sub_task_description": "Rollover/intervention/review",
                "criteria": [
                    "Context rollover writes handoff",
                    "Intervention writes structured event",
                    "Review emits structured findings",
                ],
                "status": False,
            },
            {
                "id": "phase5_mvp_freeze_and_demo",
                "phase": "Phase 5",
                "sub_task_description": "Smoke-ready MVP with docs and checks",
                "criteria": [
                    "Quickstart docs included",
                    "Smoke flow succeeds in clean repo",
                    "Run metrics persisted",
                ],
                "status": False,
            },
        ],
    }


def init_rpi_artifacts(
    paths: RepoPaths,
    task: str,
    constraints: str = "sandboxed local execution",
    acceptance_targets: str = "phase1-phase5 feature completion",
    force: bool = False,
) -> dict[str, Any]:
    ensure_repo_layout(paths)
    context = {
        "task": task,
        "repo_snapshot": repo_snapshot(paths.repo),
        "constraints": constraints,
        "acceptance_targets": acceptance_targets,
    }

    outputs: dict[str, Any] = {"created": [], "skipped": []}

    research_file = paths.rpi_dir / "research.md"
    if force or not research_file.exists():
        research_file.write_text(render_template("rpi_research", context), encoding="utf-8")
        outputs["created"].append(str(research_file))
    else:
        outputs["skipped"].append(str(research_file))

    plan_file = paths.rpi_dir / "plan.md"
    if force or not plan_file.exists():
        plan_file.write_text(render_template("rpi_plan", context), encoding="utf-8")
        outputs["created"].append(str(plan_file))
    else:
        outputs["skipped"].append(str(plan_file))

    feature_file = paths.rpi_dir / "feature_list.json"
    if force or not feature_file.exists():
        write_json(feature_file, _default_feature_list())
        outputs["created"].append(str(feature_file))
    else:
        outputs["skipped"].append(str(feature_file))

    return outputs


def is_rpi_initialized(paths: RepoPaths) -> bool:
    needed = [
        paths.rpi_dir / "research.md",
        paths.rpi_dir / "plan.md",
        paths.rpi_dir / "feature_list.json",
    ]
    return all(item.exists() for item in needed)


def load_feature_list(paths: RepoPaths) -> dict[str, Any]:
    return read_json(paths.rpi_dir / "feature_list.json", _default_feature_list())
