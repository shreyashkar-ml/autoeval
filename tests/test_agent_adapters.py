import json
import os
from pathlib import Path
import subprocess

import pytest

from autoexp.agent import context, execute, hook_event


ROOT = Path(__file__).parents[1]


def git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.mark.parametrize("agent", ["codex", "claude", "opencode", "pi"])
def test_native_adapter_contract(agent):
    if agent == "codex":
        marketplace = json.loads(
            (ROOT / ".agents/plugins/marketplace.json").read_text()
        )
        assert marketplace["plugins"][0]["source"]["path"] == "./adapters/codex"
        root = ROOT / "adapters/codex"
        manifest = json.loads((root / ".codex-plugin/plugin.json").read_text())
        assert manifest["name"] == "autoexp"
        assert "skills" not in manifest
        assert not (root / "skills").exists()
        json.loads((root / "hooks/hooks.json").read_text())
        assert (ROOT / "adapters/codex-skills/autoexp-review/SKILL.md").is_file()
        return

    if agent == "claude":
        root = ROOT / "adapters/claude"
        assert json.loads((root / ".claude-plugin/plugin.json").read_text())["name"] == "autoexp"
        json.loads((root / "hooks/hooks.json").read_text())
        assert not (root / "skills").exists()
        assert (ROOT / "adapters/claude-skills/autoexp/SKILL.md").is_file()
        assert (ROOT / "adapters/claude-skills/autoexp-review/SKILL.md").is_file()
        return

    host = "opencode-plugin" if agent == "opencode" else "pi-extension"
    root = ROOT / "adapters" / host
    package = json.loads((root / "package.json").read_text())
    entrypoint = package.get("main") or package["pi"]["extensions"][0]
    assert (root / entrypoint).is_file()
    assert (root / "bridge.ts").is_file()
    assert (root / "index.test.ts").is_file()


def test_review_commands_use_host_native_launch_paths():
    codex = (ROOT / "adapters/codex-skills/autoexp-review/SKILL.md").read_text()
    claude = (ROOT / "adapters/claude-skills/autoexp-review/SKILL.md").read_text()
    opencode = (ROOT / "adapters/opencode-plugin/index.ts").read_text()
    pi = (ROOT / "adapters/pi-extension/index.ts").read_text()

    assert "Do not run a shell fallback" in codex
    assert "!`autoexp agent review claude" in claude
    assert '"command.execute.before"' in opencode
    assert '"autoexp-review"' in opencode
    assert 'pi.registerCommand("autoexp-review"' in pi


def test_cli_reports_release_version():
    result = subprocess.run(
        [os.sys.executable, "-m", "autoexp", "--version"],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "autoexp 0.4.1"


def test_shared_context_keeps_experiment_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")

    value = context("codex", "session-1", repo, "compare parsers")

    assert value["objective"] == "compare parsers"
    assert value["exec_argv_prefix"][:3] == ["autoexp", "agent", "exec"]
    instruction = " ".join(value["instruction"].split())
    for rule in (
        "functionally separable approach",
        "non-empty diff",
        "frozen evaluator",
        "report-instruction",
        "overall report",
        "Never open a browser review",
    ):
        assert rule in instruction


def test_native_context_executes_and_binds_an_experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    protocol = context("codex", "session-1", repo, "smoke test")

    created = execute(protocol["binding_id"], [
        "experiment", "create", "smoke test",
        "--entrypoint", "main.py", "--command", "python main.py",
    ])
    run = execute(protocol["binding_id"], ["run", "--agent", "--title", "baseline"])

    assert created["result"]["experiment_id"].startswith("exp_")
    assert run["result"]["status"] == "success"
    assert run["result"]["run_id"].startswith("202")


def test_codex_hook_injects_review_feedback(monkeypatch):
    monkeypatch.setattr(
        "autoexp.agent.review_for_host",
        lambda *_args, **_kwargs: "[AUTOEXP REVIEW COMPLETE]\napproved",
    )
    result = hook_event("codex", {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": "/repo",
        "prompt": "$autoexp-review",
    })

    context_text = result["hookSpecificOutput"]["additionalContext"]
    assert "[AUTOEXP PROTOCOL v1]" in context_text
    assert "[AUTOEXP REVIEW COMPLETE]" in context_text
    assert hook_event("codex", {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": "/repo",
        "prompt": "please review this",
    }) == {}


def test_codex_hook_injects_experiment_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")

    result = hook_event("codex", {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": str(repo),
        "prompt": "$autoexp compare parsers",
    })

    context_text = result["hookSpecificOutput"]["additionalContext"]
    assert "Objective: compare parsers" in context_text
    assert "autoexp agent exec --binding-id" in context_text


@pytest.mark.skipif(os.name == "nt", reason="install.sh requires a POSIX shell")
def test_source_installer_exposes_only_review_as_a_shared_codex_skill(
    tmp_path,
):
    home = tmp_path / "home"
    legacy = home / ".agents/skills"
    for skill in ("autoexp", "autoexp-review"):
        (legacy / skill).mkdir(parents=True)
        (legacy / skill / "SKILL.md").write_text("legacy\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_log = tmp_path / "uv.log"
    (bin_dir / "uv").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$UV_LOG\"\n"
    )
    (bin_dir / "uv").chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "UV_LOG": str(uv_log),
        "AUTOEXP_SOURCE_DIR": str(ROOT),
    }

    subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True)

    assert uv_log.read_text().strip() == (
        f"tool install --force --no-cache {ROOT}"
    )
    assert not (legacy / "autoexp").exists()
    assert not (legacy / "autoexp-review").exists()
    assert (home / ".codex/skills/autoexp-review/SKILL.md").read_text() == (
        ROOT / "adapters/codex-skills/autoexp-review/SKILL.md"
    ).read_text()


@pytest.mark.skipif(os.name == "nt", reason="install.sh requires a POSIX shell")
def test_source_installer_keeps_claude_skills_out_of_plugin_namespace(tmp_path):
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "AUTOEXP_SKIP_RUNTIME": "1",
        "AUTOEXP_SOURCE_DIR": str(ROOT),
    }

    subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True)

    plugin = home / ".claude/autoexp-marketplace/adapters/claude"
    assert (plugin / ".claude-plugin/plugin.json").is_file()
    assert (plugin / "hooks/hooks.json").is_file()
    assert not (plugin / "skills").exists()
    assert (home / ".claude/skills/autoexp/SKILL.md").is_file()
    assert (home / ".claude/skills/autoexp-review/SKILL.md").is_file()


@pytest.mark.skipif(os.name == "nt", reason="install.sh requires a POSIX shell")
def test_remote_installer_fetches_one_resolved_commit(tmp_path):
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commit = "a" * 40
    curl_log = tmp_path / "curl.log"
    (bin_dir / "git").write_text(
        f"#!/bin/sh\nprintf '%s\\trefs/heads/main\\n' '{commit}'\n"
    )
    (bin_dir / "curl").write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CURL_LOG']).open('a').write(sys.argv[-3] + '\\n')\n"
        "target = Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "target.write_text('{}\\n' if target.suffix == '.json' else '')\n"
    )
    for path in bin_dir.iterdir():
        path.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "CURL_LOG": str(curl_log),
        "AUTOEXP_SKIP_RUNTIME": "1",
    }

    subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True)

    urls = curl_log.read_text().splitlines()
    assert urls
    assert all(f"/{commit}/" in url for url in urls)
