import json
from pathlib import Path
import shutil
from typing import Any, Callable

from .config import SCHEMA_VERSION, RepoPaths, ensure_repo_layout, read_json, utc_now_iso, write_json

TEMPLATE_META = {
    "research": {
        "id": "rpi_research",
        "version": "2.2.0",
        "template_file": "rpi_research.md",
        "artifact_file": "research.md",
    },
    "plan": {
        "id": "rpi_plan",
        "version": "2.2.0",
        "template_file": "rpi_plan.md",
        "artifact_file": "plan.md",
    },
    "feature_list": {
        "id": "rpi_feature_list",
        "version": "2.2.0",
        "template_file": "rpi_feature_list.md",
        "artifact_file": "feature_list.json",
    },
}

ARTIFACT_FILENAMES = ("research.md", "plan.md", "feature_list.json")


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def load_template(name: str) -> str:
    meta = TEMPLATE_META[name]
    template_file = _template_dir() / meta["template_file"]
    return template_file.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    raw = load_template(name)
    return raw.format_map(_SafeDict(context))


def _instruction_dir(paths: RepoPaths) -> Path:
    return paths.rpi_dir


def _legacy_instruction_dirs(paths: RepoPaths) -> list[Path]:
    return [
        paths.autoeval_dir / "instructions" / "rpi",
        paths.autoeval_dir / "rpi",
    ]


def build_instruction_prompts(
    paths: RepoPaths,
    task: str,
    constraints: str = "sandboxed local execution",
    acceptance_targets: str = "all requested feature criteria satisfied in target repository",
    provider_capabilities: str = "selected provider adapter capabilities via runtime contract",
) -> dict[str, str]:
    context = {
        "task": task,
        "constraints": constraints,
        "acceptance_targets": acceptance_targets,
        "provider_capabilities": provider_capabilities,
    }
    return {
        "research": render_template("research", context),
        "plan": render_template("plan", context),
        "feature_list": load_template("feature_list"),
    }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _render_pending_artifact(artifact_type: str, template_name: str, task: str) -> str:
    template = TEMPLATE_META[template_name]
    title = artifact_type.capitalize()
    return (
        f"<!-- artifact_type: {artifact_type} -->\n"
        "<!-- artifact_state: awaiting_provider_bootstrap -->\n"
        f"<!-- expected_template: {template['id']}@{template['version']} -->\n"
        f"<!-- generated_at: {utc_now_iso()} -->\n\n"
        f"# {title}\n\n"
        "This artifact is waiting for provider bootstrap generation.\n"
        f"Requested task: {task}\n"
    )


def _cleanup_legacy_rpi_layout(paths: RepoPaths, migrate: bool = True) -> None:
    target_dir = _instruction_dir(paths)
    target_dir.mkdir(parents=True, exist_ok=True)

    legacy_rpi_dir = paths.autoeval_dir / "rpi"
    if migrate and legacy_rpi_dir.exists():
        for filename in ARTIFACT_FILENAMES:
            src = legacy_rpi_dir / filename
            dst = target_dir / filename
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))

    for legacy_dir in _legacy_instruction_dirs(paths):
        if legacy_dir.exists():
            shutil.rmtree(legacy_dir)

    stale_files = [
        target_dir / "implementation.md",
        paths.autoeval_dir / "rpi" / "implementation.md",
        paths.autoeval_dir / "instructions" / "rpi" / "rpi_implementation.md",
    ]
    for stale_file in stale_files:
        if stale_file.exists():
            stale_file.unlink()


def _default_feature_list() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "template": {
            "id": TEMPLATE_META["feature_list"]["id"],
            "version": TEMPLATE_META["feature_list"]["version"],
        },
        "generated_at": utc_now_iso(),
        "sub_tasks": [
            {
                "id": "research_baseline",
                "phase_id": "phase_0",
                "phase": "Research",
                "sub_task_description": "Establish repository baseline and execution constraints",
                "criteria": [
                    "Research artifact captures system architecture, dependencies, and request trace",
                    "Known risks and unknowns are listed with concrete follow-up questions",
                ],
                "status": False,
            },
            {
                "id": "plan_decomposition",
                "phase_id": "phase_1",
                "phase": "Planning",
                "sub_task_description": "Break request into phased, testable implementation milestones",
                "criteria": [
                    "Plan defines ordered phases and explicit success criteria per phase",
                    "Plan includes test strategy and rollback/mitigation notes",
                ],
                "status": False,
            },
            {
                "id": "implementation_execution",
                "phase_id": "phase_2",
                "phase": "Implementation",
                "sub_task_description": "Execute scoped code and configuration changes",
                "criteria": [
                    "Changes are mapped to planned subtasks and tracked with evidence",
                    "Any required tooling/integration setup is documented in-line",
                ],
                "status": False,
            },
            {
                "id": "verification_and_handoff",
                "phase_id": "phase_3",
                "phase": "Validation",
                "sub_task_description": "Validate outcomes and prepare handoff artifacts",
                "criteria": [
                    "Automated and/or manual validations are attached to each implemented subtask",
                    "Final summary includes remaining gaps and next actions",
                ],
                "status": False,
            },
        ],
    }


def _default_feature_task_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _default_feature_list()["sub_tasks"]}


def _is_default_feature_payload(payload: dict[str, Any]) -> bool:
    tasks = payload.get("sub_tasks", [])
    if not isinstance(tasks, list):
        return False
    defaults = _default_feature_task_map()
    if len(tasks) != len(defaults):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        task_id = str(task.get("id", ""))
        default = defaults.get(task_id)
        if default is None:
            return False
        for field in ("phase_id", "phase", "sub_task_description", "criteria"):
            if task.get(field) != default.get(field):
                return False
    return True


def needs_rpi_bootstrap(paths: RepoPaths) -> bool:
    research_file = paths.rpi_dir / "research.md"
    plan_file = paths.rpi_dir / "plan.md"
    feature_file = paths.rpi_dir / "feature_list.json"

    if not all(file_path.exists() for file_path in (research_file, plan_file, feature_file)):
        return True

    research_text = research_file.read_text(encoding="utf-8")
    plan_text = plan_file.read_text(encoding="utf-8")

    if (
        "artifact_state: awaiting_provider_bootstrap" in research_text
        or "generated_from_template: rpi_research@" in research_text
        or "Research Artifact Instruction" in research_text
    ):
        return True
    if (
        "artifact_state: awaiting_provider_bootstrap" in plan_text
        or "generated_from_template: rpi_plan@" in plan_text
        or "Planning Artifact Instruction" in plan_text
    ):
        return True

    feature_payload = read_json(feature_file, _default_feature_list())
    return _is_default_feature_payload(feature_payload)


def _normalize_markdown(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    return normalized + "\n"


def _normalize_feature_task(raw: dict[str, Any], index: int) -> dict[str, Any]:
    task_id = str(raw.get("id") or f"phase_{index + 1}_subtask_{index + 1}")
    phase_id = str(raw.get("phase_id") or f"phase_{index + 1}")
    phase = str(raw.get("phase") or phase_id.replace("_", " ").title())
    description = str(raw.get("sub_task_description") or f"Execute {task_id}")
    criteria_raw = raw.get("criteria", [])
    if isinstance(criteria_raw, list):
        criteria = [str(item) for item in criteria_raw if str(item).strip()]
    else:
        criteria = [str(criteria_raw)] if str(criteria_raw).strip() else []
    if not criteria:
        criteria = [f"Evidence recorded for {task_id}"]
    return {
        "id": task_id,
        "phase_id": phase_id,
        "phase": phase,
        "sub_task_description": description,
        "criteria": criteria,
        "status": bool(raw.get("status", False)),
    }


def _normalize_feature_payload(payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template", {})
    version = (
        str(template.get("version"))
        if isinstance(template, dict) and template.get("version")
        else TEMPLATE_META["feature_list"]["version"]
    )
    raw_tasks = payload.get("sub_tasks", [])
    if not isinstance(raw_tasks, list):
        raw_tasks = []
    tasks = [
        _normalize_feature_task(item if isinstance(item, dict) else {}, index)
        for index, item in enumerate(raw_tasks)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "template": {"id": TEMPLATE_META["feature_list"]["id"], "version": version},
        "generated_at": str(payload.get("generated_at") or utc_now_iso()),
        "sub_tasks": tasks,
    }


def commit_rpi_artifacts(paths: RepoPaths, payload: dict[str, Any]) -> list[str]:
    ensure_repo_layout(paths)
    _cleanup_legacy_rpi_layout(paths, migrate=True)
    written: list[str] = []

    file_map = {
        "research": paths.rpi_dir / "research.md",
        "plan": paths.rpi_dir / "plan.md",
    }
    for key, file_path in file_map.items():
        value = payload.get(key)
        if isinstance(value, str):
            normalized = _normalize_markdown(value)
            if normalized:
                file_path.write_text(normalized, encoding="utf-8")
                written.append(str(file_path))

    feature_payload = payload.get("feature_list")
    if isinstance(feature_payload, dict):
        write_json(paths.rpi_dir / "feature_list.json", _normalize_feature_payload(feature_payload))
        written.append(str(paths.rpi_dir / "feature_list.json"))

    return written


def init_rpi_artifacts(
    paths: RepoPaths,
    task: str,
    constraints: str = "sandboxed local execution",
    acceptance_targets: str = "all requested feature criteria satisfied in target repository",
    provider_capabilities: str = "selected provider adapter capabilities via runtime contract",
    force: bool = False,
) -> dict[str, Any]:
    ensure_repo_layout(paths)
    _cleanup_legacy_rpi_layout(paths, migrate=not force)
    _instruction_dir(paths).mkdir(parents=True, exist_ok=True)

    outputs: dict[str, Any] = {"created": [], "skipped": []}

    research_file = paths.rpi_dir / "research.md"
    if force or not research_file.exists():
        research_file.write_text(
            _render_pending_artifact("research", "research", task),
            encoding="utf-8",
        )
        outputs["created"].append(str(research_file))
    else:
        outputs["skipped"].append(str(research_file))

    plan_file = paths.rpi_dir / "plan.md"
    if force or not plan_file.exists():
        plan_file.write_text(
            _render_pending_artifact("plan", "plan", task),
            encoding="utf-8",
        )
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


def bootstrap_rpi_with_provider(
    paths: RepoPaths,
    task: str,
    provider_name: str = "codex",
    force: bool = False,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def _status(message: str) -> None:
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            return

    ensure_repo_layout(paths)
    _cleanup_legacy_rpi_layout(paths, migrate=True)
    pending = needs_rpi_bootstrap(paths)
    skip_generation = (not force) and (not pending)

    from .agent_contract import build_task_envelope
    from .providers import get_provider

    provider = get_provider(provider_name)
    feature_payload = read_json(paths.rpi_dir / "feature_list.json", _default_feature_list())
    instructions = build_instruction_prompts(paths=paths, task=task)
    run_id = f"rpi_bootstrap_{utc_now_iso().replace(':', '').replace('-', '').replace('+', '_')}"
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    events_file = run_dir / "events.jsonl"

    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "provider_connection_started",
            "run_id": run_id,
            "provider": provider_name,
            "task": task,
            "instruction_templates": sorted(instructions.keys()),
        },
    )
    _status("connecting_provider")

    try:
        connection_payload = provider.connect(repo_root=str(paths.repo))
    except Exception as exc:
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "provider_connection_failed",
                "run_id": run_id,
                "provider": provider_name,
                "error": str(exc),
            },
        )
        _status("provider_connection_failed")
        return {
            "ok": False,
            "skipped": False,
            "provider": provider_name,
            "run_id": run_id,
            "connected": None,
            "error": str(exc),
            "artifacts_written": [],
        }

    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "provider_connected",
            "run_id": run_id,
            "provider": provider_name,
            "connection": connection_payload,
        },
    )
    _status("provider_connected")

    if skip_generation:
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "rpi_bootstrap_skipped",
                "run_id": run_id,
                "provider": provider_name,
                "reason": "rpi artifacts already generated",
            },
        )
        _status("rpi_bootstrap_skipped")
        return {
            "ok": True,
            "skipped": True,
            "provider": provider_name,
            "reason": "rpi artifacts already generated",
            "run_id": run_id,
            "connected": connection_payload,
            "artifacts_written": [],
        }

    envelope = build_task_envelope(
        run_id=run_id,
        session_number=0,
        task=f"Bootstrap RPI artifacts for task: {task}",
        feature_payload=feature_payload,
        provider_capabilities=getattr(provider, "capabilities", {}),
        rpi_instructions=instructions,
        requested_task=task,
        repo_root=str(paths.repo),
        rpi_bootstrap_pending=True,
    )
    envelope_file = run_dir / "prompts" / "rpi_bootstrap_envelope.json"
    write_json(envelope_file, envelope.model_dump())

    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "provider_bootstrap_requested",
            "run_id": run_id,
            "provider": provider_name,
            "task_id": envelope.task_id,
            "instruction_templates": sorted(instructions.keys()),
            "task_envelope_file": str(envelope_file),
        },
    )
    _status("provider_bootstrap_requested")

    response = provider.run(
        task_envelope=envelope,
        feature_payload=feature_payload,
        session_number=0,
        structured_output=True,
    )
    structured = response.structured_output if isinstance(response.structured_output, dict) else {}
    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "provider_bootstrap_response",
            "run_id": run_id,
            "provider": provider_name,
            "structured_keys": sorted(structured.keys()),
            "usage": response.usage,
        },
    )
    _status("provider_bootstrap_response")

    rpi_payload = structured.get("rpi_artifacts")
    if not isinstance(rpi_payload, dict):
        error = "provider did not return structured_output.rpi_artifacts"
        _append_jsonl(
            events_file,
            {
                "ts": utc_now_iso(),
                "type": "rpi_bootstrap_failed",
                "run_id": run_id,
                "provider": provider_name,
                "error": error,
            },
        )
        _status("rpi_bootstrap_failed")
        return {
            "ok": False,
            "skipped": False,
            "provider": provider_name,
            "run_id": run_id,
            "connected": connection_payload,
            "error": error,
            "artifacts_written": [],
        }

    _status("writing_rpi_artifacts")
    artifacts_written = commit_rpi_artifacts(paths, rpi_payload)
    _append_jsonl(
        events_file,
        {
            "ts": utc_now_iso(),
            "type": "rpi_artifacts_committed",
            "run_id": run_id,
            "provider": provider_name,
            "artifacts": artifacts_written,
            "source": "provider_bootstrap",
        },
    )
    _status("rpi_bootstrap_completed")

    progress = (
        "# RPI Bootstrap\n"
        f"- provider: {provider_name}\n"
        f"- connected: {bool(connection_payload)}\n"
        f"- artifacts_written: {len(artifacts_written)}\n"
        f"- timestamp: {utc_now_iso()}\n"
    )
    (run_dir / "progress.md").write_text(progress, encoding="utf-8")
    write_json(
        run_dir / "session_meta.json",
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "provider": provider_name,
            "mode": "rpi_bootstrap",
            "session_count": 1,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
    )
    write_json(
        run_dir / "usage.json",
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "sessions": [
                {
                    "session_number": 0,
                    "provider": provider_name,
                    "usage": response.usage,
                    "actions": 0,
                    "created_at": utc_now_iso(),
                }
            ],
            "totals": {
                "input_tokens": int(response.usage.get("input_tokens", 0)),
                "output_tokens": int(response.usage.get("output_tokens", 0)),
                "total_tokens": int(response.usage.get("total_tokens", 0)),
                "estimated_cost_usd": float(response.usage.get("estimated_cost_usd", 0.0)),
                "actions": 0,
            },
            "updated_at": utc_now_iso(),
        },
    )

    return {
        "ok": True,
        "skipped": False,
        "provider": provider_name,
        "run_id": run_id,
        "connected": connection_payload,
        "artifacts_written": artifacts_written,
    }


def is_rpi_initialized(paths: RepoPaths) -> bool:
    needed = [
        paths.rpi_dir / "research.md",
        paths.rpi_dir / "plan.md",
        paths.rpi_dir / "feature_list.json",
    ]
    return all(item.exists() for item in needed)


def load_feature_list(paths: RepoPaths) -> dict[str, Any]:
    return read_json(paths.rpi_dir / "feature_list.json", _default_feature_list())
