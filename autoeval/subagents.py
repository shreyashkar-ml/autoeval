from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .agent_contract import AllowedAction, TaskEnvelope


class SubAgentProfile(BaseModel):
    name: str
    role: str
    model: str | None = None
    action_filter: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


DEFAULT_ORCHESTRATOR_PROFILE = SubAgentProfile(
    name="orchestrator",
    role="Coordinates specialist agents and owns completion decisions",
    model="haiku",
)

DEFAULT_CODING_PROFILE = SubAgentProfile(
    name="coding",
    role="Implements and verifies feature work",
    model="sonnet",
    action_filter=["read_file", "write_file", "run", "mcp_call"],
    metadata={"verification_gate": True, "screenshot_evidence_required": True},
)

DEFAULT_GITHUB_PROFILE = SubAgentProfile(
    name="github",
    role="Handles git commits and PR lifecycle",
    model="haiku",
    action_filter=["github", "run", "read_file"],
)

DEFAULT_SLACK_PROFILE = SubAgentProfile(
    name="slack",
    role="Posts milestone updates and blockers",
    model="haiku",
    action_filter=["notify", "mcp_call"],
    metadata={"default_channel": "new-channel"},
)


def default_subagent_profiles(include_orchestrator: bool = True) -> list[SubAgentProfile]:
    profiles = [DEFAULT_CODING_PROFILE, DEFAULT_GITHUB_PROFILE, DEFAULT_SLACK_PROFILE]
    if include_orchestrator:
        return [DEFAULT_ORCHESTRATOR_PROFILE, *profiles]
    return profiles


def reference_issue_context(sub_task_id: str, task_goal: str) -> dict[str, Any]:
    return {
        "issue_id": sub_task_id,
        "title": f"Implement {sub_task_id.replace('_', ' ')}",
        "description": f"Execute planned work for {sub_task_id} in service of: {task_goal}",
        "test_steps": [
            "Run verification gate before feature work",
            "Apply code changes scoped to issue context",
            "Capture evidence and report affected files",
        ],
    }


def reference_delegation_trace(sub_task_id: str, task_goal: str) -> list[dict[str, Any]]:
    issue = reference_issue_context(sub_task_id, task_goal)
    return [
        {
            "agent": "orchestrator",
            "step": "prepare_issue_context",
            "payload": issue,
        },
        {
            "agent": "coding",
            "step": "verification_gate",
            "payload": {
                "required": True,
                "issue_id": sub_task_id,
            },
        },
        {
            "agent": "coding",
            "step": "implement_feature",
            "payload": issue,
        },
        {
            "agent": "github",
            "step": "commit_changes",
            "payload": {
                "issue_id": sub_task_id,
                "commit_hint": f"feat: complete {sub_task_id}",
            },
        },
        {
            "agent": "slack",
            "step": "notify_completion",
            "payload": {
                "channel": DEFAULT_SLACK_PROFILE.metadata.get("default_channel", "new-channel"),
                "message": f":white_check_mark: completed {sub_task_id}",
            },
        },
    ]


def derive_sub_agent_envelope(
    parent: TaskEnvelope,
    profile: SubAgentProfile,
    goal_suffix: str,
) -> TaskEnvelope:
    allowed_actions: list[AllowedAction] = []
    for action in parent.allowed_actions:
        if profile.action_filter and action.type not in profile.action_filter:
            continue
        allowed_actions.append(action)

    return TaskEnvelope(
        contract_version=parent.contract_version,
        task_id=f"{parent.task_id}:subagent:{profile.name}",
        repo_snapshot_id=parent.repo_snapshot_id,
        goal=f"{parent.goal} - {goal_suffix}",
        context=parent.context,
        allowed_actions=allowed_actions,
        success_criteria=parent.success_criteria,
        provider_capabilities=parent.provider_capabilities,
        metadata={
            **parent.metadata,
            "subagent_profile": profile.model_dump(),
            "parent_task_id": parent.task_id,
        },
    )
