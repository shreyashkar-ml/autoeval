import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_user_home() -> Path:
    env = os.getenv("AUTOEVAL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".config" / "autoeval").resolve()


@dataclass(frozen=True)
class RepoPaths:
    repo: Path
    user_home: Path

    @classmethod
    def from_repo(cls, repo: Path, user_home: Path | None = None) -> "RepoPaths":
        return cls(repo=repo.expanduser().resolve(), user_home=(user_home or default_user_home()))

    @property
    def autoeval_dir(self) -> Path:
        return self.repo / ".autoeval"

    @property
    def state_file(self) -> Path:
        return self.autoeval_dir / "state.json"

    @property
    def rpi_dir(self) -> Path:
        return self.autoeval_dir / "instructions"

    @property
    def runs_dir(self) -> Path:
        return self.autoeval_dir / "runs"

    @property
    def memory_dir(self) -> Path:
        return self.autoeval_dir / "memory"

    @property
    def mcp_project_dir(self) -> Path:
        return self.autoeval_dir / "mcp"

    @property
    def project_overrides_file(self) -> Path:
        return self.mcp_project_dir / "overrides.json"

    @property
    def user_mcp_dir(self) -> Path:
        return self.user_home / "mcp"

    @property
    def user_registry_file(self) -> Path:
        return self.user_mcp_dir / "registry.json"

    @property
    def user_auth_refs_file(self) -> Path:
        return self.user_mcp_dir / "auth_refs.json"

    @property
    def user_health_file(self) -> Path:
        return self.user_mcp_dir / "health.json"

    @property
    def user_state_dir(self) -> Path:
        return self.user_home / "state"

    @property
    def user_preferences_file(self) -> Path:
        return self.user_state_dir / "preferences.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def ensure_repo_layout(paths: RepoPaths) -> None:
    paths.autoeval_dir.mkdir(parents=True, exist_ok=True)
    paths.rpi_dir.mkdir(parents=True, exist_ok=True)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.memory_dir.mkdir(parents=True, exist_ok=True)
    paths.mcp_project_dir.mkdir(parents=True, exist_ok=True)

    if not paths.state_file.exists():
        write_json(
            paths.state_file,
            {
                "schema_version": SCHEMA_VERSION,
                "contract_version": "1.0",
                "provider": "codex",
                "last_run_id": None,
                "created_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
            },
        )

    if not paths.project_overrides_file.exists():
        write_json(paths.project_overrides_file, {"schema_version": SCHEMA_VERSION, "profiles": {}})


def ensure_user_layout(paths: RepoPaths) -> None:
    paths.user_home.mkdir(parents=True, exist_ok=True)
    paths.user_mcp_dir.mkdir(parents=True, exist_ok=True)
    paths.user_state_dir.mkdir(parents=True, exist_ok=True)

    if not paths.user_registry_file.exists():
        write_json(paths.user_registry_file, {"schema_version": SCHEMA_VERSION, "profiles": {}})

    if not paths.user_auth_refs_file.exists():
        write_json(paths.user_auth_refs_file, {"schema_version": SCHEMA_VERSION, "refs": {}})

    if not paths.user_health_file.exists():
        write_json(paths.user_health_file, {"schema_version": SCHEMA_VERSION, "profiles": {}})

    if not paths.user_preferences_file.exists():
        write_json(paths.user_preferences_file, {"schema_version": SCHEMA_VERSION, "preferences": {}})


def touch_state(paths: RepoPaths, **updates: Any) -> None:
    state = read_json(paths.state_file, {"schema_version": SCHEMA_VERSION})
    state.update(updates)
    state["schema_version"] = SCHEMA_VERSION
    state["contract_version"] = "1.0"
    state["updated_at"] = utc_now_iso()
    write_json(paths.state_file, state)
