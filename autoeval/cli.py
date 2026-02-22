import json
from pathlib import Path
from threading import Event, Thread

import typer

from .config import RepoPaths, ensure_repo_layout, ensure_user_layout, read_json, touch_state
from .connectors import (
    add_profile,
    connect_profile,
    disconnect_profile,
    list_profiles,
    record_slack_notification,
    remove_profile,
    run_browser_scenario,
    set_auth_ref,
    set_profile_enabled,
)
from .evals import run_eval_suite
from .migrations import run_migrations
from .orchestrator import fork_run, intervene, resume_task, run_task, status
from .review import run_review
from .rpi import bootstrap_rpi_with_provider

app = typer.Typer(help="CLI for autonomous execution against a target repository")
mcp_app = typer.Typer(help="MCP lifecycle commands")
test_app = typer.Typer(help="Validation helpers")
CONTEXT_RATIO_DISPLAY = {
    "value": 1.0,
    "note": "representational value until real provider telemetry is integrated",
}

app.add_typer(mcp_app, name="mcp")
app.add_typer(test_app, name="test")


def _paths(repo: Path) -> RepoPaths:
    return RepoPaths.from_repo(repo)


def _emit(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def init(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    provider: str = typer.Option("codex"),
    task: str = typer.Option("Initialize target repository execution context"),
    force: bool = typer.Option(False, "--force", help="Regenerate existing RPI artifacts/prompts"),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)
    touch_state(paths, provider=provider)
    artifact_paths = [
        str(paths.rpi_dir / "research.md"),
        str(paths.rpi_dir / "plan.md"),
        str(paths.rpi_dir / "feature_list.json"),
    ]
    payload: dict[str, object] = {
        "ok": True,
        "provider": provider,
        "rpi": {"created": [], "skipped": []},
    }
    status_messages = {
        "connecting_provider": f"[autoeval] connecting to provider '{provider}'...",
        "provider_connected": f"[autoeval] provider '{provider}' connected.",
        "provider_connection_failed": f"[autoeval] provider '{provider}' connection failed.",
        "provider_bootstrap_requested": "[autoeval] generating research artifacts and executing task...",
        "provider_bootstrap_response": "[autoeval] provider returned bootstrap payload.",
        "writing_rpi_artifacts": "[autoeval] writing artifacts to .autoeval/instructions/ ...",
        "rpi_bootstrap_completed": "[autoeval] bootstrap artifact generation complete.",
        "rpi_bootstrap_skipped": "[autoeval] bootstrap skipped (artifacts already generated).",
        "rpi_bootstrap_failed": "[autoeval] bootstrap failed; no artifacts written.",
    }
    wait_stop = Event()
    wait_thread: Thread | None = None

    def _stop_waiting() -> None:
        nonlocal wait_thread
        wait_stop.set()
        if wait_thread and wait_thread.is_alive():
            wait_thread.join(timeout=0.2)
        wait_thread = None

    def _start_waiting() -> None:
        nonlocal wait_thread
        if wait_thread and wait_thread.is_alive():
            return
        wait_stop.clear()

        def _heartbeat() -> None:
            while not wait_stop.wait(timeout=8):
                typer.echo(
                    "[autoeval] generating research artifacts and executing task... (waiting)",
                    err=True,
                )

        wait_thread = Thread(target=_heartbeat, daemon=True)
        wait_thread.start()

    def _status_callback(message: str) -> None:
        if message == "provider_bootstrap_requested":
            _start_waiting()
        elif message in {
            "provider_bootstrap_response",
            "rpi_bootstrap_failed",
            "rpi_bootstrap_completed",
            "rpi_bootstrap_skipped",
            "provider_connection_failed",
        }:
            _stop_waiting()
        rendered = status_messages.get(message, f"[autoeval] {message}")
        typer.echo(rendered, err=True)

    try:
        bootstrap = bootstrap_rpi_with_provider(
            paths=paths,
            task=task,
            provider_name=provider,
            force=force,
            status_callback=_status_callback,
        )
    finally:
        _stop_waiting()
    payload["bootstrap"] = bootstrap
    if bool(bootstrap.get("ok", False)):
        if bool(bootstrap.get("skipped", False)):
            payload["rpi"] = {"created": [], "skipped": artifact_paths}
        else:
            written = bootstrap.get("artifacts_written", [])
            created = [str(item) for item in written if isinstance(item, str)]
            payload["rpi"] = {"created": created, "skipped": []}
    payload["ok"] = bool(payload["ok"]) and bool(bootstrap.get("ok", False))
    _emit(payload)
    if not bool(bootstrap.get("ok", False)):
        raise typer.Exit(code=1)


@app.command()
def run(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    task: str = typer.Option(...),
    provider: str = typer.Option("codex"),
    run_id: str | None = typer.Option(None),
    context_threshold: float = typer.Option(0.6),
    eval_profile: str = typer.Option("default"),
    require_eval_pass: bool = typer.Option(True, "--require-eval-pass/--no-require-eval-pass"),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)

    try:
        result = run_task(
            paths=paths,
            task=task,
            provider=provider,
            run_id=run_id,
            context_threshold=context_threshold,
            eval_profile=eval_profile,
            require_eval_pass=require_eval_pass,
        )
    except Exception as exc:
        _emit({"ok": False, "provider": provider, "error": str(exc)})
        raise typer.Exit(code=1) from exc
    result["context_ratio"] = CONTEXT_RATIO_DISPLAY
    _emit(result)


@app.command()
def resume(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    task: str = typer.Option("Continue target repository execution"),
    provider: str = typer.Option("codex"),
    run_id: str | None = typer.Option(None),
    context_threshold: float = typer.Option(0.6),
    eval_profile: str = typer.Option("default"),
    require_eval_pass: bool = typer.Option(True, "--require-eval-pass/--no-require-eval-pass"),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)

    try:
        result = resume_task(
            paths=paths,
            task=task,
            provider=provider,
            run_id=run_id,
            context_threshold=context_threshold,
            eval_profile=eval_profile,
            require_eval_pass=require_eval_pass,
        )
    except Exception as exc:
        _emit({"ok": False, "provider": provider, "error": str(exc)})
        raise typer.Exit(code=1) from exc
    result["context_ratio"] = CONTEXT_RATIO_DISPLAY
    _emit(result)


def _status_cmd(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    payload = status(paths, run_id=run_id)
    payload["context_ratio"] = CONTEXT_RATIO_DISPLAY
    _emit(payload)


def _intervene_cmd(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    reason: str = typer.Option(...),
    run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    _emit(intervene(paths, reason=reason, run_id=run_id))


@app.command()
def review(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    severity: str = typer.Option("medium"),
    run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    _emit(run_review(paths, severity=severity, run_id=run_id))


@app.command()
def notify(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    message: str = typer.Option(...),
    channel: str = typer.Option("new-channel"),
    run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id") or "notify_only"
    touch_state(paths, last_run_id=active_run)
    _emit(
        record_slack_notification(
            paths=paths,
            run_id=active_run,
            channel=channel,
            message=message,
            requested_by="user",
        )
    )


@app.command("eval")
def eval_run(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    run_id: str | None = typer.Option(None),
    profile: str = typer.Option("default"),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id")
    if not active_run:
        raise typer.BadParameter("no active run found; provide --run-id explicitly")
    _emit(run_eval_suite(paths=paths, run_id=active_run, profile=profile))


@mcp_app.command("list")
def mcp_list(
    scope: str = typer.Option("effective"),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    _emit({"scope": scope, "profiles": list_profiles(paths, scope=scope)})


@mcp_app.command("add")
def mcp_add(
    scope: str = typer.Option(...),
    name: str = typer.Option(...),
    transport: str = typer.Option("stdio"),
    command: str = typer.Option(""),
    tool_namespace: str = typer.Option(""),
    required_env: str = typer.Option(""),
    timeout_s: int = typer.Option(60),
    enabled: bool = typer.Option(True),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    env_items = [item.strip() for item in required_env.split(",") if item.strip()]
    result = add_profile(
        paths=paths,
        scope=scope,
        name=name,
        transport=transport,
        command=command,
        tool_namespace=tool_namespace,
        required_env=env_items,
        timeout_s=timeout_s,
        enabled=enabled,
    )
    _emit({"scope": scope, "name": name, "profile": result})


@mcp_app.command("remove")
def mcp_remove(
    scope: str = typer.Option(...),
    name: str = typer.Option(...),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    existed = remove_profile(paths=paths, scope=scope, name=name)
    _emit({"scope": scope, "name": name, "removed": existed})


@mcp_app.command("enable")
def mcp_enable(
    scope: str = typer.Option(...),
    name: str = typer.Option(...),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    _emit(set_profile_enabled(paths=paths, scope=scope, name=name, enabled=True))


@mcp_app.command("disable")
def mcp_disable(
    scope: str = typer.Option(...),
    name: str = typer.Option(...),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    _emit(set_profile_enabled(paths=paths, scope=scope, name=name, enabled=False))


@mcp_app.command("connect")
def mcp_connect(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    name: str = typer.Option(...),
) -> None:
    paths = _paths(repo)
    _emit(connect_profile(paths=paths, name=name))


@mcp_app.command("disconnect")
def mcp_disconnect(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    name: str = typer.Option(...),
) -> None:
    paths = _paths(repo)
    _emit(disconnect_profile(paths=paths, name=name))


@mcp_app.command("set-auth")
def mcp_set_auth(
    name: str = typer.Option(...),
    auth_ref: str = typer.Option(...),
    repo: Path = typer.Option(Path("."), exists=True, file_okay=False, dir_okay=True),
) -> None:
    paths = _paths(repo)
    _emit(set_auth_ref(paths=paths, name=name, auth_ref=auth_ref))


@test_app.command("browser")
def test_browser(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    mcp: str = typer.Option(...),
    scenario: str = typer.Option(...),
    run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    state = read_json(paths.state_file, {"last_run_id": None})
    active_run = run_id or state.get("last_run_id") or "browser_only"
    touch_state(paths, last_run_id=active_run)
    _emit(run_browser_scenario(paths=paths, run_id=active_run, profile_name=mcp, scenario=scenario))


@app.command("status")
def status_alias(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    run_id: str | None = typer.Option(None),
) -> None:
    _status_cmd(repo=repo, run_id=run_id)


@app.command("intervene")
def intervene_alias(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    reason: str = typer.Option(...),
    run_id: str | None = typer.Option(None),
) -> None:
    _intervene_cmd(repo=repo, reason=reason, run_id=run_id)


@app.command("fork")
def fork_alias(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    source_run_id: str = typer.Option(...),
    target_run_id: str | None = typer.Option(None),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    _emit(fork_run(paths, source_run_id=source_run_id, target_run_id=target_run_id))


if __name__ == "__main__":
    app()
