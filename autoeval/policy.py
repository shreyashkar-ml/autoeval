from __future__ import annotations

from typing import Any, Callable

from .agent_contract import ActionRequest, PolicyDecision, TaskEnvelope

RuntimeApprover = Callable[[ActionRequest], bool | tuple[bool, str] | dict[str, Any]]

HIGH_RISK_ACTIONS = {"run", "cmd", "mcp_call", "github"}
NETWORK_TOKENS = ("http://", "https://", "curl ", "wget ", "pip install", "npm install")


def _allowed_action(task_envelope: TaskEnvelope, request: ActionRequest) -> tuple[bool, str]:
    for action in task_envelope.allowed_actions:
        if action.type != request.type:
            continue
        if action.selectors and request.selector and request.selector not in action.selectors:
            continue
        return True, "action allowed by task envelope"
    return False, f"action type not allowed: {request.type}"


def _network_violation(task_envelope: TaskEnvelope, request: ActionRequest) -> str | None:
    constraints = task_envelope.context.constraints
    if not constraints.no_network:
        return None
    cmd = str(request.parameters.get("cmd", "")).lower()
    if any(token in cmd for token in NETWORK_TOKENS):
        return "network command blocked by no_network constraint"
    return None


def _repo_edit_violation(task_envelope: TaskEnvelope, request: ActionRequest) -> str | None:
    constraints = task_envelope.context.constraints
    if request.type in {"write_file", "propose_patch"} and not constraints.allow_repo_edits:
        return "repo edits blocked by allow_repo_edits=false"
    return None


class PolicyEngine:
    def __init__(self, runtime_approver: RuntimeApprover | None = None) -> None:
        self.runtime_approver = runtime_approver

    def evaluate(self, task_envelope: TaskEnvelope, request: ActionRequest) -> PolicyDecision:
        allowed, reason = _allowed_action(task_envelope, request)
        if not allowed:
            return PolicyDecision(
                allowed=False,
                reason=reason,
                policy_stage="static",
                needs_orchestrator_verification=True,
                runtime_approval_required=False,
            )

        violation = _repo_edit_violation(task_envelope, request)
        if violation:
            return PolicyDecision(
                allowed=False,
                reason=violation,
                policy_stage="static",
                needs_orchestrator_verification=True,
                runtime_approval_required=False,
            )

        violation = _network_violation(task_envelope, request)
        if violation:
            return PolicyDecision(
                allowed=False,
                reason=violation,
                policy_stage="static",
                needs_orchestrator_verification=True,
                runtime_approval_required=False,
            )

        runtime_required = request.type in HIGH_RISK_ACTIONS
        if not runtime_required or self.runtime_approver is None:
            return PolicyDecision(
                allowed=True,
                reason="approved by static policy",
                policy_stage="static",
                needs_orchestrator_verification=True,
                runtime_approval_required=runtime_required,
            )

        response = self.runtime_approver(request)
        if isinstance(response, bool):
            approved = response
            runtime_reason = "runtime approver decision"
            mutation: dict[str, Any] = {}
        elif isinstance(response, tuple):
            approved = bool(response[0])
            runtime_reason = str(response[1])
            mutation = {}
        else:
            approved = bool(response.get("allowed", False))
            runtime_reason = str(response.get("reason", "runtime approver decision"))
            mutation = dict(response.get("mutated_parameters", {}))

        if mutation:
            request.parameters.update(mutation)

        return PolicyDecision(
            allowed=approved,
            reason=runtime_reason,
            policy_stage="runtime",
            needs_orchestrator_verification=True,
            runtime_approval_required=True,
            metadata={"mutated_parameters": sorted(mutation.keys()) if mutation else []},
        )


def evaluate_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = dict(payload.get("action", {}))
    action_type = str(action.get("type", ""))
    constraints = dict(payload.get("constraints", {}))
    allowed = set(payload.get("allowed_actions", []))

    allow_repo_edits = bool(constraints.get("allow_repo_edits", False))
    action_allowed = action_type in allowed
    if action_type in {"write_file", "propose_patch"} and not allow_repo_edits:
        action_allowed = False

    needs_verification = action_type in {"write_file", "propose_patch", "run", "cmd", "mcp_call"}
    return {
        "allowed": action_allowed,
        "needs_orchestrator_verification": needs_verification,
        "reason": "allowed" if action_allowed else "blocked",
    }
