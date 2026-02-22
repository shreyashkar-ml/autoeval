from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0"


class AllowedAction(BaseModel):
    type: str
    selectors: list[str] = Field(default_factory=list)
    format: str | None = None
    max_bytes: int | None = None


class TaskConstraints(BaseModel):
    no_network: bool = True
    max_runtime_sec: int = 900
    allow_repo_edits: bool = True
    sandbox_mode: str = "workspace-write"


class TaskContext(BaseModel):
    repo_map: str | None = None
    symbol_index: str | None = None
    recent_runs: list[str] = Field(default_factory=list)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskEnvelope(BaseModel):
    contract_version: str = CONTRACT_VERSION
    task_id: str
    repo_snapshot_id: str
    goal: str
    context: TaskContext
    allowed_actions: list[AllowedAction]
    success_criteria: list[str]
    provider_capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionRequest(BaseModel):
    action_id: str
    type: str
    selector: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "worker"


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    policy_stage: str = "static"
    needs_orchestrator_verification: bool = True
    runtime_approval_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    action_id: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class UsageTelemetry(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class CompletionEnvelope(BaseModel):
    completed_sub_task_ids: list[str] = Field(default_factory=list)
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    unresolved_blockers: list[str] = Field(default_factory=list)
    proposed_diffs: list[str] = Field(default_factory=list)
    context_ratio: float = 1.0
    usage: UsageTelemetry = Field(default_factory=UsageTelemetry)


def default_allowed_actions() -> list[AllowedAction]:
    return [
        AllowedAction(type="read_file", max_bytes=200000),
        AllowedAction(type="write_file"),
        AllowedAction(type="propose_patch", format="unified_diff"),
        AllowedAction(type="run", selectors=["build", "test", "cmd"]),
        AllowedAction(type="mcp_call"),
        AllowedAction(type="notify", selectors=["slack"]),
        AllowedAction(type="github", selectors=["commit", "create_pr", "push"]),
    ]


def success_criteria_from_feature_payload(feature_payload: dict[str, Any]) -> list[str]:
    criteria: list[str] = []
    for item in feature_payload.get("sub_tasks", []):
        for criterion in item.get("criteria", []):
            if criterion not in criteria:
                criteria.append(criterion)
    return criteria or ["all_sub_tasks_completed"]


def build_task_envelope(
    run_id: str,
    session_number: int,
    task: str,
    feature_payload: dict[str, Any],
    provider_capabilities: dict[str, Any] | None = None,
    rpi_instructions: dict[str, str] | None = None,
    requested_task: str | None = None,
    repo_root: str | None = None,
    rpi_bootstrap_pending: bool = False,
) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=f"{run_id}:session:{session_number}",
        repo_snapshot_id=run_id,
        goal=task,
        context=TaskContext(
            repo_map="artifact://repo_map.json",
            symbol_index="artifact://symbols.parquet",
            recent_runs=[f"artifact://{run_id}/events.jsonl"],
            constraints=TaskConstraints(),
        ),
        allowed_actions=default_allowed_actions(),
        success_criteria=success_criteria_from_feature_payload(feature_payload),
        provider_capabilities=provider_capabilities or {},
        metadata={
            "workflow_model": "research-plan-implementation",
            "feature_count": len(feature_payload.get("sub_tasks", [])),
            "feature_list_path": ".autoeval/instructions/feature_list.json",
            "completion_signal": "PROJECT_COMPLETE:",
            "orchestration_pattern": "orchestrator->coding->github->slack",
            "requested_task": requested_task or task,
            "repo_root": repo_root or ".",
            "rpi_bootstrap_pending": bool(rpi_bootstrap_pending),
            "rpi_instructions": rpi_instructions or {},
        },
    )


def contract_schema() -> dict[str, Any]:
    return TaskEnvelope.model_json_schema()


def contract_schema_file() -> Path:
    base = Path(__file__).resolve().parent
    return base / "schemas" / "agent_contract.v1.json"
