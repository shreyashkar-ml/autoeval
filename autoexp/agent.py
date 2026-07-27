"""Versioned protocol shared by native coding-agent adapters."""

from __future__ import annotations

import io
import json
import re
import sys
import time
import uuid
import webbrowser
from contextlib import redirect_stdout
from pathlib import Path

from .review import create_review_session, review_session_by_id
from .store import db
from .workspace import (
    experiment_entry, list_experiments, now, register_repository, resolve_root,
)


PROTOCOL_VERSION = 1
AGENTS = {"claude", "codex", "opencode", "pi"}
WORKFLOW_INSTRUCTION = """\
Use Autoexp for this repository and run every Autoexp command through the
supplied argv prefix. Do not create repository-local Autoexp configuration,
run directories, or generated reports.

Inspect the repository and objective first. Use Standard mode unless one stable
scalar metric and a frozen evaluator can automatically decide keep versus
revert. Create or select one experiment; creating it binds it to this session.

For Standard experiments, keep shared fixtures and evaluation in one small
harness. Put each independently runnable or functionally separable approach in
its own descriptively named source file, declare every relevant file before its
first run, and record each focused variant with `run --agent --title`. If the
objective explicitly calls for iterations on one implementation, keep that file
and verify that each later run has a non-empty diff against the preceding run.

For Autoresearch, use ordinary repository files for the program, candidate, and
frozen evaluator. Run `research preflight`, change only the candidate, and record
one focused hypothesis per `research attempt`. Never edit the evaluator; a
changed evaluator or objective starts a new experiment.

Before writing reports, read `report-instruction`. Mark only decision-changing,
surprising, or new-best evidence as a milestone. Kept Autoresearch attempts are
reported automatically. End Standard experimentation with one concise overall
report attached without a run ID. Preserve all immutable evidence and cite the
run IDs supporting the conclusion. Never open a browser review unless the user
explicitly invokes the review workflow."""


class AgentError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def envelope(operation, data=None, error=None):
    value = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": error is None,
        "operation": operation,
    }
    value["data" if error is None else "error"] = (
        data or {} if error is None else {
            "code": getattr(error, "code", "internal_error"),
            "message": str(error),
        }
    )
    return value


def _validate_agent(agent):
    if agent not in AGENTS:
        raise AgentError("unsupported_agent", f"Unsupported agent: {agent}")


def _binding_row(binding_id=None, *, agent=None, session_id=None):
    conn = db()
    if binding_id:
        row = conn.execute(
            "select * from agent_bindings where binding_id = ?", (binding_id,)
        ).fetchone()
    else:
        row = conn.execute(
            """select * from agent_bindings
               where agent = ? and host_session_id = ?""",
            (agent, session_id),
        ).fetchone()
    conn.close()
    if not row:
        raise AgentError("binding_not_found", "No Autoexp binding exists for this host session.")
    return dict(row)


def _public_binding(row):
    return {
        key: row[key] for key in (
            "binding_id", "agent", "host_session_id", "repo_id",
            "experiment_id", "state", "created_at", "updated_at",
        )
    }


def bind(agent, session_id, repo, experiment=None):
    _validate_agent(agent)
    if not isinstance(session_id, str) or not session_id:
        raise AgentError("invalid_session_id", "Host session ID is required.")
    repository = register_repository(repo)
    selected = None
    if experiment:
        try:
            selected = experiment_entry(experiment)
        except ValueError as exc:
            raise AgentError("experiment_not_found", str(exc)) from exc
        if selected["repo_id"] != repository["repo_id"]:
            raise AgentError(
                "experiment_repository_mismatch",
                "The experiment belongs to a different repository.",
            )
    conn = db()
    existing = conn.execute(
        "select * from agent_bindings where agent = ? and host_session_id = ?",
        (agent, session_id),
    ).fetchone()
    timestamp = now()
    if existing:
        current_experiment = (
            selected["experiment_id"] if selected else existing["experiment_id"]
        )
        if existing["repo_id"] != repository["repo_id"]:
            conn.close()
            raise AgentError(
                "session_repository_mismatch",
                "This host session is already bound to a different repository.",
            )
        conn.execute(
            """update agent_bindings
               set experiment_id = ?, state = 'active', updated_at = ?
               where binding_id = ?""",
            (current_experiment, timestamp, existing["binding_id"]),
        )
        binding_id = existing["binding_id"]
    else:
        binding_id = f"binding_{uuid.uuid4().hex}"
        conn.execute(
            """insert into agent_bindings(
                 binding_id, agent, host_session_id, repo_id, experiment_id,
                 state, created_at, updated_at
               ) values (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (
                binding_id, agent, session_id, repository["repo_id"],
                selected["experiment_id"] if selected else None,
                timestamp, timestamp,
            ),
        )
    conn.commit()
    row = conn.execute(
        "select * from agent_bindings where binding_id = ?", (binding_id,)
    ).fetchone()
    conn.close()
    return {
        "binding": _public_binding(row),
        "repository": repository,
        "experiment": (
            _experiment_summary(experiment_entry(row["experiment_id"]))
            if row["experiment_id"] else None
        ),
    }


def _experiment_summary(entry):
    return {
        key: entry[key] for key in (
            "experiment_id", "repo_id", "title", "objective", "kind",
            "status", "created_at", "updated_at",
        )
    }


def _resolved_experiment(binding, explicit=None):
    conn = db()
    repo = conn.execute(
        "select * from repositories where repo_id = ?", (binding["repo_id"],)
    ).fetchone()
    conn.close()
    if not repo:
        raise AgentError("repository_not_found", "The bound repository no longer exists.")
    wanted = explicit or binding["experiment_id"]
    if wanted:
        try:
            entry = experiment_entry(wanted)
        except ValueError as exc:
            raise AgentError("experiment_not_found", str(exc)) from exc
        if entry["repo_id"] != binding["repo_id"]:
            raise AgentError(
                "experiment_repository_mismatch",
                "The experiment belongs to a different repository.",
            )
        return entry
    items = list_experiments(binding["repo_id"])
    if not items:
        raise AgentError(
            "no_active_experiment",
            "No Autoexp experiment is associated with this repository.",
        )
    return items[0]


def context(agent, session_id, repo, objective=""):
    bound = bind(agent, session_id, repo)
    binding = bound["binding"]
    try:
        selected = _resolved_experiment(binding)
    except AgentError as exc:
        if exc.code != "no_active_experiment":
            raise
        selected = None
    objective = str(objective or "").strip()
    prefix = ["autoexp", "agent", "exec", "--binding-id", binding["binding_id"], "--"]
    return {
        "binding_id": binding["binding_id"],
        "repository": bound["repository"],
        "objective": objective,
        "experiment": _experiment_summary(selected) if selected else None,
        "instruction": WORKFLOW_INSTRUCTION,
        "exec_argv_prefix": prefix,
    }


def _operation(operation_id):
    conn = db()
    row = conn.execute(
        """select o.*, b.agent, b.host_session_id, b.repo_id, b.experiment_id
           from agent_operations o
           join agent_bindings b on b.binding_id = o.binding_id
           where o.operation_id = ?""",
        (operation_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise AgentError("operation_not_found", f"Unknown operation ID: {operation_id}")
    return dict(row)


def _sync_operation(row):
    if row["state"] != "waiting" or not row["review_session_id"]:
        return row
    session = review_session_by_id(row["review_session_id"])
    state = row["state"]
    if not session:
        state = "failed"
    elif session["status"] == "expired":
        state = "expired"
    elif session["status"] == "completed":
        state = "dismissed" if session["decision"] == "dismissed" else "completed"
    if state != row["state"]:
        conn = db()
        conn.execute(
            "update agent_operations set state = ?, updated_at = ? where operation_id = ? and state = 'waiting'",
            (state, now(), row["operation_id"]),
        )
        conn.commit()
        conn.close()
        row = _operation(row["operation_id"])
    return row


def _operation_data(row):
    row = _sync_operation(row)
    session = (
        review_session_by_id(row["review_session_id"])
        if row["review_session_id"] else None
    )
    result = json.loads(row["result"] or "{}")
    return {
        "operation_id": row["operation_id"],
        "binding_id": row["binding_id"],
        "state": row["state"],
        "experiment_id": session["experiment_id"] if session else row["experiment_id"],
        "review_session_id": row["review_session_id"],
        "decision": session["decision"] if session else None,
        "notes": session["notes"] if session else [],
        "expires_at": session["expires_at"] if session else None,
        "delivered": bool(result.get("delivery")),
        "error": row["error"],
    }


def review_start(
    agent, session_id, repo, experiment=None, *, timeout=900,
    host="127.0.0.1", port=8765, open_browser=True,
):
    from urllib.parse import quote
    from .server import ensure_server

    binding = bind(agent, session_id, repo, experiment)["binding"]
    selected = _resolved_experiment(binding, experiment)
    if binding["experiment_id"] != selected["experiment_id"]:
        binding = bind(agent, session_id, repo, selected["experiment_id"])["binding"]
    token, session = create_review_session(selected["experiment_id"], ttl=timeout)
    operation_id = f"agentop_{uuid.uuid4().hex}"
    timestamp = now()
    conn = db()
    conn.execute(
        """insert into agent_operations(
             operation_id, binding_id, kind, state, review_session_id,
             request_id, result, error, created_at, updated_at
           ) values (?, ?, 'review', 'starting', ?, ?, ?, null, ?, ?)""",
        (
            operation_id, binding["binding_id"], session["session_id"],
            f"request_{uuid.uuid4().hex}",
            json.dumps({"review_session_id": session["session_id"]}),
            timestamp, timestamp,
        ),
    )
    conn.commit()
    try:
        base, _ = ensure_server(host, port)
        url = (
            f"{base}/?experiment={quote(session['experiment_id'])}"
            f"&review={quote(token)}"
        )
        if open_browser:
            webbrowser.open(url)
        conn.execute(
            """update agent_operations
               set state = 'waiting', updated_at = ? where operation_id = ?""",
            (now(), operation_id),
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            """update review_sessions set status = 'expired'
               where session_id = ? and status = 'waiting'""",
            (session["session_id"],),
        )
        conn.execute(
            """update agent_operations
               set state = 'failed', error = ?, updated_at = ?
               where operation_id = ?""",
            (str(exc), now(), operation_id),
        )
        conn.commit()
        conn.close()
        raise AgentError("review_start_failed", str(exc)) from exc
    conn.close()
    return {
        **_operation_data(_operation(operation_id)),
        "url": url,
    }


def review_status(operation_id):
    return _operation_data(_operation(operation_id))


def review_wait(operation_id, timeout=900, interval=0.25):
    deadline = time.monotonic() + max(0, timeout)
    while True:
        data = review_status(operation_id)
        if data["state"] != "waiting" or time.monotonic() >= deadline:
            return data
        time.sleep(interval)


def review_cancel(operation_id):
    conn = db()
    conn.execute("begin immediate")
    row = conn.execute(
        """select o.state, o.review_session_id, r.status as review_status,
                  r.expires_at
           from agent_operations o
           left join review_sessions r on r.session_id = o.review_session_id
           where o.operation_id = ?""",
        (operation_id,),
    ).fetchone()
    if not row:
        conn.rollback()
        conn.close()
        raise AgentError("operation_not_found", f"Unknown operation ID: {operation_id}")
    if (
        row["state"] == "waiting"
        and row["review_status"] == "waiting"
        and row["expires_at"] > int(time.time())
    ):
        conn.execute(
            """update review_sessions set status = 'expired'
               where session_id = ? and status = 'waiting'""",
            (row["review_session_id"],),
        )
        conn.execute(
            """update agent_operations set state = 'canceled', updated_at = ?
               where operation_id = ? and state = 'waiting'""",
            (now(), operation_id),
        )
    conn.commit()
    conn.close()
    return review_status(operation_id)


def mark_delivered(operation_id, host_message_id=None):
    conn = db()
    conn.execute("begin immediate")
    row = conn.execute(
        "select result from agent_operations where operation_id = ?", (operation_id,)
    ).fetchone()
    if not row:
        conn.rollback()
        conn.close()
        raise AgentError("operation_not_found", f"Unknown operation ID: {operation_id}")
    result = json.loads(row["result"] or "{}")
    first = "delivery" not in result
    if first:
        result["delivery"] = {
            "claimed_at": now(),
            "delivered_at": now() if host_message_id else None,
            "host_message_id": host_message_id,
        }
    elif host_message_id and not result["delivery"].get("host_message_id"):
        result["delivery"].update({
            "delivered_at": now(),
            "host_message_id": host_message_id,
        })
    if first or host_message_id:
        conn.execute(
            "update agent_operations set result = ?, updated_at = ? where operation_id = ?",
            (json.dumps(result), now(), operation_id),
        )
    conn.commit()
    conn.close()
    return {"operation_id": operation_id, "delivered": first}


def lifecycle(agent, session_id, event, repo):
    if event not in {"start", "resume", "shutdown"}:
        raise AgentError("invalid_lifecycle_event", f"Unsupported lifecycle event: {event}")
    if event in {"start", "resume"}:
        data = bind(agent, session_id, repo)
        conn = db()
        operation = conn.execute(
            """select o.operation_id
               from agent_operations o
               where o.binding_id = ? and o.kind = 'review'
                 and o.state in ('waiting', 'completed', 'dismissed')
                 and json_extract(o.result, '$.delivery') is null
               order by o.created_at desc limit 1""",
            (data["binding"]["binding_id"],),
        ).fetchone()
        conn.close()
        return {
            "event": event,
            **data,
            "review": review_status(operation["operation_id"]) if operation else None,
        }
    binding = _binding_row(agent=agent, session_id=session_id)
    conn = db()
    conn.execute(
        "update agent_bindings set state = 'ended', updated_at = ? where binding_id = ?",
        (now(), binding["binding_id"]),
    )
    conn.commit()
    conn.close()
    return {"event": event, "binding": {**_public_binding(binding), "state": "ended"}}


def format_feedback(data):
    if data["state"] == "dismissed":
        return (
            "[AUTOEXP REVIEW DISMISSED]\n"
            "The user closed the review without submitting a decision. "
            "Do not treat this as approval and do not open another review."
        )
    if data["state"] != "completed":
        return (
            f"[AUTOEXP REVIEW {data['state'].upper()}]\n"
            f"Operation: {data['operation_id']}\n"
            "Do not open another review for this invocation."
        )
    if data["decision"] == "approved" and not data["notes"]:
        return (
            "[AUTOEXP REVIEW COMPLETE]\n"
            "The user approved the reviewed experiment without requesting changes. "
            "Do not open another review."
        )
    notes = "\n".join(
        f"- [{note['scope']}] {note['text']}" for note in data["notes"]
    )
    return (
        "[AUTOEXP REVIEW FEEDBACK]\n"
        f"Experiment: {data['experiment_id']}\n"
        f"Operation: {data['operation_id']}\n\n"
        f"{notes}\n\n"
        "Treat these notes as the user's next instruction in the active Autoexp "
        "experiment.\nDo not open another review unless the user explicitly "
        "invokes the review command again."
    )


def review_for_host(agent, session_id, repo, experiment=None, timeout=900):
    started = review_start(
        agent, session_id, repo, experiment, timeout=timeout, open_browser=True
    )
    result = review_wait(started["operation_id"], timeout)
    mark_delivered(started["operation_id"], "hook-context")
    return format_feedback(result)


def execute(binding_id, argv):
    """Dispatch an Autoexp argv without a shell and return its structured output."""
    if not argv or argv[0] == "agent":
        raise AgentError("invalid_argv", "An Autoexp command is required after --.")
    binding = _binding_row(binding_id)
    if binding["state"] != "active":
        raise AgentError("binding_ended", "The host binding has ended.")
    from .cli import build_parser

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        raise AgentError("invalid_argv", "Invalid Autoexp command arguments.") from exc
    request_id = f"request_{uuid.uuid4().hex}"
    conn = db()
    repository = conn.execute(
        "select path from repositories where repo_id = ?", (binding["repo_id"],)
    ).fetchone()
    conn.close()
    if hasattr(args, "repo") and argv[:2] == ["experiment", "create"]:
        args.repo = repository["path"]
    if hasattr(args, "experiment") and not args.experiment and binding["experiment_id"]:
        args.experiment = binding["experiment_id"]
    args._agent_binding = binding
    args._agent_request_id = request_id
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            result = args.fn(args)
    except SystemExit as exc:
        raise AgentError(
            "command_failed", f"Autoexp command exited with status {exc.code}."
        ) from exc
    text = output.getvalue().strip()
    if argv[:2] == ["experiment", "create"]:
        entry = result
        if not entry and text:
            entry = json.loads(text)
        if entry and entry.get("experiment_id"):
            repo = Path(experiment_entry(entry["experiment_id"])["repo_path"])
            bind(
                binding["agent"], binding["host_session_id"], repo,
                entry["experiment_id"],
            )
            timestamp = now()
            conn = db()
            conn.execute(
                """insert into agent_operations(
                     operation_id, binding_id, kind, state, request_id, result,
                     created_at, updated_at
                   ) values (?, ?, 'experiment', 'completed', ?, ?, ?, ?)""",
                (
                    f"agentop_{uuid.uuid4().hex}", binding_id, request_id,
                    json.dumps({"experiment_id": entry["experiment_id"]}),
                    timestamp, timestamp,
                ),
            )
            conn.commit()
            conn.close()
    try:
        command_output = json.loads(text) if text else result
    except json.JSONDecodeError:
        command_output = text
    return {
        "binding_id": binding_id,
        "request_id": request_id,
        "argv": argv,
        "result": command_output,
    }


def hook_event(agent, event):
    """Handle lifecycle and Codex's native Autoexp prompt hooks."""
    name = event.get("hook_event_name")
    session_id = event.get("session_id")
    repo = event.get("cwd")
    if not session_id or not repo:
        raise AgentError("invalid_hook_event", "Hook event requires session_id and cwd.")
    if name == "SessionStart":
        data = lifecycle(
            agent, session_id,
            "resume" if event.get("source") == "resume" else "start", repo,
        )
        if agent == "codex":
            binding = data["binding"]
            return {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        "[AUTOEXP SESSION v1]\n"
                        f"Agent: codex\nSession: {session_id}\n"
                        f"Binding: {binding['binding_id']}\nRepository: {repo}\n"
                        "Use this binding for $autoexp agent-exec commands."
                    ),
                }
            }
        return {}
    if name == "SessionEnd":
        lifecycle(agent, session_id, "shutdown", repo)
        return {}
    if agent == "codex" and name == "UserPromptSubmit":
        prompt = str(event.get("prompt") or "").strip()
        command, _, argument = prompt.partition(" ")
        if command == "$autoexp":
            data = context("codex", session_id, repo, argument.strip())
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": (
                        "[AUTOEXP PROTOCOL v1]\n"
                        f"Binding: {data['binding_id']}\n"
                        f"Repository: {data['repository']['path']}\n"
                        f"Objective: {data['objective'] or '(not supplied)'}\n"
                        f"Command prefix: {' '.join(data['exec_argv_prefix'])}\n\n"
                        f"{data['instruction']}"
                    ),
                }
            }
        parts = prompt.split()
        if (
            not parts
            or parts[0] != "$autoexp-review"
            or len(parts) > 2
            or (len(parts) == 2 and not re.fullmatch(r"exp_[A-Za-z0-9._-]+", parts[1]))
        ):
            return {}
        experiment = parts[1] if len(parts) == 2 else None
        message = review_for_host("codex", session_id, repo, experiment)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "[AUTOEXP PROTOCOL v1]\n"
                    f"Session: {session_id}\n{message}"
                ),
            }
        }
    return {}
