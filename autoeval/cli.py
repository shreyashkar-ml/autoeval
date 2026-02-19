import json
from pathlib import Path

import typer

from .config import RepoPaths, ensure_repo_layout, ensure_user_layout, read_json, touch_state
from .connectors import (
    add_profile,
    connect_profile,
    disconnect_profile,
    list_profiles,
    remove_profile,
    run_browser_scenario,
    set_auth_ref,
    set_profile_enabled,
)
from .migrations import run_migrations
from .orchestrator import intervene, resume_task, run_task, status
from .review import run_review
from .rpi import init_rpi_artifacts

app = typer.Typer(help="autoeval harness CLI")
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
    task: str = typer.Option("Initialize autoeval"),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)
    touch_state(paths, provider=provider)

    result = init_rpi_artifacts(paths, task=task)
    _emit({"ok": True, "provider": provider, "rpi": result})


@app.command()
def run(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    task: str = typer.Option(...),
    provider: str = typer.Option("codex"),
    run_id: str | None = typer.Option(None),
    context_threshold: float = typer.Option(0.6),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)

    result = run_task(
        paths=paths,
        task=task,
        provider=provider,
        run_id=run_id,
        context_threshold=context_threshold,
    )
    result["context_ratio"] = CONTEXT_RATIO_DISPLAY
    _emit(result)


@app.command()
def resume(
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True),
    task: str = typer.Option("resume"),
    provider: str = typer.Option("codex"),
    run_id: str | None = typer.Option(None),
    context_threshold: float = typer.Option(0.6),
) -> None:
    paths = _paths(repo)
    ensure_repo_layout(paths)
    ensure_user_layout(paths)
    run_migrations(paths)

    result = resume_task(
        paths=paths,
        task=task,
        provider=provider,
        run_id=run_id,
        context_threshold=context_threshold,
    )
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


if __name__ == "__main__":
    app()
