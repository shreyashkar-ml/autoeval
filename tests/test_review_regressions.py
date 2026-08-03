import hashlib
import threading
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

import autoexp.importer as importer
import autoexp.runner as runner
from autoexp.artifacts import list_artifacts
from autoexp.autoresearch import AutoResearch
from autoexp.cli import relink_cmd
from autoexp.execution import execute
from autoexp.runs import copy_run_source, restore_run_state
from autoexp.reports import list_documents, mark_milestone, read_project_report
from autoexp.review import create_review_session
from autoexp.runtime import list_runs, run_diff, run_report, run_source
import autoexp.server as server_module
from autoexp.server import AutoexpHTTPServer, AutoexpHandler, view
from autoexp.snapshots import (
    _hash_declared_source, capture_workspace, materialize_snapshot,
    snapshot_hashes, snapshot_matches,
)
from autoexp.store import db, private_git_dir
from autoexp.workspace import (
    create_experiment, declare_file, experiment_entry, materialize_workspace,
    register_repository, registry, repo_data_dir, resolve_root, run_dir_for,
    sync_storage,
)


def git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def commit_repo(repo, message):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test",
            "-c", "user.email=test@example.com", "commit", "-qm", message,
        ],
        check=True,
    )


def test_milestone_creates_per_experiment_report_not_overall_report(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('important result')\n")
    entry = create_experiment("test milestone reports", root=repo, entrypoint="main.py", command="python main.py")
    commit_repo(repo, "initial")
    run = execute(entry["experiment_id"])

    milestone = mark_milestone(
        run_id=run["run_id"], title="Decision reached",
        significance="This result changes which variant should be kept.", root=entry["experiment_id"],
    )

    documents = list_documents(entry["experiment_id"], "report")
    assert milestone["report"]["run_id"] == run["run_id"]
    assert documents[0]["run_id"] == run["run_id"]
    assert read_project_report(entry["experiment_id"])["exists"] is False
    assert "Decision reached" in run_report(run["run_id"], entry["experiment_id"])["text"]
    assert list_runs(root=entry["experiment_id"])[0]["report_path"] == documents[0]["path"]


def test_standard_runs_form_diffable_lineage(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('first')\n")
    entry = create_experiment(
        "test ordinary run diffs", root=repo,
        entrypoint="main.py", command="python main.py",
    )
    commit_repo(repo, "initial")
    first = execute(entry["experiment_id"])
    (repo / "main.py").write_text("print('second')\n")
    second = execute(entry["experiment_id"])

    delta = run_diff(second["run_id"], entry["experiment_id"])

    assert second["parent_run_id"] == first["run_id"]
    assert delta["base_run_id"] == first["run_id"]
    assert delta["changed_files"] == ["main.py"]
    assert "-print('first')" in delta["diff"]
    assert "+print('second')" in delta["diff"]


def test_subdirectory_registration_and_review_stay_in_context(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    logs = repo / "tests/logs"
    churn = repo / "tests/churn"
    logs.mkdir(parents=True)
    churn.mkdir(parents=True)
    (logs / "benchmark.py").write_text("print('logs')\n")
    (churn / "candidate.py").write_text("print('churn')\n")

    monkeypatch.chdir(logs)
    log_entry = create_experiment(
        "classify production logs", root=".",
        entrypoint="benchmark.py", command="python benchmark.py",
    )
    monkeypatch.chdir(churn)
    create_experiment(
        "predict churn", root=".",
        entrypoint="candidate.py", command="python candidate.py",
    )
    monkeypatch.chdir(logs)
    token, session = create_review_session()

    assert log_entry["stage"]["name"] == "tests/logs/benchmark.py"
    assert log_entry["stage"]["working_dir"] == "tests/logs"
    assert experiment_entry(resolve_root())["experiment_id"] == log_entry["experiment_id"]
    assert session["experiment_id"] == log_entry["experiment_id"]
    assert len(token) >= 32


def test_missing_entrypoint_does_not_register_orphan(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    with pytest.raises(FileNotFoundError, match="entrypoint does not exist"):
        create_experiment("broken registration", root=repo, entrypoint="missing.py")
    conn = db()
    assert conn.execute("select count(*) from experiments").fetchone()[0] == 0
    conn.close()


def test_registry_hides_repositories_without_experiments(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    registered = register_repository(repo)
    assert registry() == []
    result = sync_storage(prune=True)
    assert result["pruned_repositories"] == [registered["repo_id"]]
    assert not repo_data_dir(registered["repo_id"]).exists()


def test_sync_prunes_experiments_with_deleted_working_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    first_dir = repo / "first"
    second_dir = repo / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "main.py").write_text("print('first')\n")
    (second_dir / "main.py").write_text("print('second')\n")
    first = create_experiment(
        "first experiment", root=repo,
        entrypoint="first/main.py", command="python main.py",
    )
    first_run = execute(first["experiment_id"])
    (first_dir / "main.py").write_text("print('first, revised')\n")
    revised_run = execute(first["experiment_id"])
    mark_milestone(
        run_id=revised_run["run_id"],
        title="Revised result",
        significance="Exercises immutable report cleanup.",
        root=first["experiment_id"],
    )
    second = create_experiment(
        "second experiment", root=repo,
        entrypoint="second/main.py", command="python main.py",
    )
    second_run = execute(second["experiment_id"])
    git_dir = private_git_dir(second["experiment_id"])
    shutil.rmtree(first_dir)

    audit = sync_storage()
    assert Path(first["data_path"]).is_dir()
    result = sync_storage(prune=True)

    assert audit["missing"][0]["experiment_id"] == first["experiment_id"]
    assert result["pruned"][0]["experiment_id"] == first["experiment_id"]
    assert not Path(first["data_path"]).exists()
    assert experiment_entry(second["experiment_id"])["exists"]
    assert subprocess.run(
        ["git", "--git-dir", str(git_dir), "show-ref", "--verify", "--quiet",
         f"refs/autoexp/snapshots/{first_run['source_snapshot_id']}"],
    ).returncode != 0
    assert subprocess.run(
        ["git", "--git-dir", str(git_dir), "show-ref", "--verify", "--quiet",
         f"refs/autoexp/snapshots/{second_run['source_snapshot_id']}"],
    ).returncode == 0

    shutil.rmtree(repo)
    final = sync_storage(prune=True)
    assert final["experiment_count"] == 0
    assert not repo_data_dir(second["repo_id"]).exists()


def test_report_guidance_can_be_overwritten_from_ui_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    entry = create_experiment("test report guidance", root=repo)
    server = AutoexpHTTPServer(("127.0.0.1", 0), AutoexpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/experiments/{entry['experiment_id']}/report-guidance",
            data=json.dumps({"text": "Use short sections.\n"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=30) as response:
            assert json.load(response)["text"] == "Use short sections.\n"
        assert experiment_entry(entry["experiment_id"])["report_guidance"] == "Use short sections.\n"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_snapshot_drops_files_reclassified_as_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    (repo / "credentials.txt").write_text("old-secret\n")
    entry = create_experiment("test snapshots", root=repo, entrypoint="main.py")
    declare_file(entry["experiment_id"], "credentials.txt", "supporting-source")
    first = capture_workspace(entry["experiment_id"])

    declare_file(entry["experiment_id"], "credentials.txt", "secret-source")
    second = capture_workspace(
        entry["experiment_id"], parent_snapshot_id=first["snapshot_id"]
    )
    restored = tmp_path / "restored"
    materialize_snapshot(second["snapshot_id"], restored, entry["experiment_id"])

    assert not (restored / "credentials.txt").exists()
    legacy = snapshot_hashes(restored, include_types=False)
    assert legacy["source_hash"] != second["source_hash"]
    assert snapshot_matches(legacy, restored)


def test_source_hash_distinguishes_empty_missing_and_directory(tmp_path):
    config = {"files": [{"path": "source.txt", "role": "editable-source"}]}
    source = tmp_path / "source.txt"
    source.write_text("")
    empty = _hash_declared_source(tmp_path, config)
    source.unlink()
    missing = _hash_declared_source(tmp_path, config)
    source.mkdir()
    directory = _hash_declared_source(tmp_path, config)

    assert len({empty, missing, directory}) == 3


def test_relinked_repository_keeps_its_original_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    entry = create_experiment("test relink", root=repo, entrypoint="main.py")
    moved = tmp_path / "moved"
    repo.rename(moved)

    relink_cmd(SimpleNamespace(repo_id=entry["repo_id"], path=str(moved)))
    registered = register_repository(moved)

    assert registered["repo_id"] == entry["repo_id"]


def research_experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "research")
    (repo / "program.md").write_text("Improve the score.\n")
    (repo / "candidate.py").write_text("print('candidate')\n")
    (repo / "evaluate.py").write_text("print('evaluate')\n")
    config = {
        "autoresearch": {
            "objective": {
                "metric": "score",
                "direction": "max",
                "baseline": None,
                "budget_sec": 30,
            },
            "files": [
                {"path": "program.md", "role": "human"},
                {"path": "candidate.py", "role": "agent"},
                {"path": "evaluate.py", "role": "frozen"},
            ],
            "metric": {"kind": "json", "path": "metrics.json", "key": "score"},
            "agent": {"cmd": [sys.executable, "-c", "pass"]},
        }
    }
    entry = create_experiment(
        "test recovery",
        root=repo,
        kind="autoresearch",
        entrypoint="candidate.py",
        command="python candidate.py --ctx ${CTX}",
        config=config,
    )
    declare_file(entry["experiment_id"], "program.md", "supporting-source")
    declare_file(entry["experiment_id"], "evaluate.py", "frozen-evaluator")
    return entry


def test_kept_research_attempt_gets_one_report(tmp_path, monkeypatch):
    entry = research_experiment(tmp_path, monkeypatch)
    research = AutoResearch(entry["experiment_id"])
    started = research.begin_attempt("Establish a useful baseline")
    monkeypatch.setattr(research, "_score_run", lambda *_: 0.5)

    attempt = research.finish_attempt(started["attempt"]["key"])
    duplicate = mark_milestone(
        attempt_id=attempt["attempt_id"],
        title="Duplicate agent milestone",
        significance="Should reuse the automatic kept report.",
        root=entry["experiment_id"],
    )

    reports = [
        item for item in list_documents(entry["experiment_id"], "report")
        if item["run_id"] == attempt["run_id"]
    ]
    assert attempt["verdict"] == "kept"
    assert len(reports) == 1
    assert duplicate["report"]["document_id"] == reports[0]["document_id"]
    assert "Establish a useful baseline" in run_report(
        attempt["run_id"], entry["experiment_id"]
    )["text"]


def test_stranded_research_attempt_is_recovered(tmp_path, monkeypatch):
    entry = research_experiment(tmp_path, monkeypatch)
    research = AutoResearch(entry["experiment_id"])
    contract = research.state()["contract"]
    conn = db()
    conn.execute(
        """insert into research_attempts(
             contract_id, attempt_id, sequence, status, hypothesis,
             base_snapshot_id, candidate_snapshot_id, metadata
           ) values (?, 'a01', 1, 'running', 'interrupted', ?, ?, ?)""",
        (
            contract["contract_id"],
            contract["best_snapshot_id"],
            contract["best_snapshot_id"],
            json.dumps({"owner_pid": 0}),
        ),
    )
    conn.commit()
    conn.close()

    AutoResearch(entry["experiment_id"])

    conn = db()
    attempt = conn.execute(
        "select status, failure_message from research_attempts where attempt_id = 'a01'"
    ).fetchone()
    conn.close()
    assert attempt["status"] == "failed"
    assert "no longer running" in attempt["failure_message"]


def test_restore_is_exact_and_refuses_dirty_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('snapshot')\n")
    entry = create_experiment("test restore", root=repo, entrypoint="main.py")
    declare_file(entry["experiment_id"], "optional.txt", "supporting-source")
    commit_repo(repo, "initial")
    run = execute(entry["experiment_id"])

    (repo / "optional.txt").write_text("added later\n")
    commit_repo(repo, "add optional source")
    restore_run_state(run["run_id"], entry["experiment_id"])
    assert not (repo / "optional.txt").exists()

    commit_repo(repo, "restore snapshot")
    (repo / "main.py").write_text("print('dirty')\n")
    with pytest.raises(ValueError, match="uncommitted source changes"):
        restore_run_state(run["run_id"], entry["experiment_id"])


def test_restore_rejects_snapshot_paths_outside_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    entry = create_experiment("test safe restore", root=repo, entrypoint="main.py")
    snapshot = tmp_path / "snapshot"
    (snapshot / ".autoexp").mkdir(parents=True)
    (snapshot / ".autoexp/project.json").write_text(json.dumps({
        "files": [{"path": "../outside.txt", "role": "editable-source"}],
    }))

    with pytest.raises(ValueError, match="snapshot source path"):
        copy_run_source(snapshot, entry["experiment_id"])


def test_terminal_run_rejects_new_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    entry = create_experiment("test immutable evidence", root=repo, entrypoint="main.py")
    run = execute(entry["experiment_id"])
    conn = db()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="evidence is immutable"):
            conn.execute(
                "insert into artifacts values (?, ?, 'output', ?, ?, ?, ?, ?, '{}')",
                ("late", run["run_id"], "output/late.txt", "text/plain", "0" * 64, 0, "now"),
            )
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="evidence is immutable"):
            conn.execute(
                "insert into run_external_inputs values (?, ?, ?, ?, ?, ?, ?, '{}')",
                (run["run_id"], "late", "env", 1, "hash", "1", "pinned"),
            )
    finally:
        conn.close()


def test_failed_import_cleans_up_and_can_retry(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("AUTOEXP_HOME", str(home))
    source = tmp_path / "legacy"
    control = source / ".autoexp"
    control.mkdir(parents=True)
    (control / "project.json").write_text(json.dumps({"title": "legacy", "runner": "local"}))
    sqlite3.connect(control / "state.sqlite").close()
    subprocess.run(["git", "init", "--bare", "-q", str(control / "repository")], check=True)

    original = importer._validate_artifact_hashes

    def fail_validation(*_args):
        raise ValueError("invalid legacy evidence")

    monkeypatch.setattr(importer, "_validate_artifact_hashes", fail_validation)
    with pytest.raises(ValueError, match="invalid legacy evidence"):
        importer.import_legacy_project(source)

    conn = db()
    assert conn.execute("select count(*) from experiments").fetchone()[0] == 0
    conn.close()
    assert not list(home.glob("repos/*/experiments/*"))

    monkeypatch.setattr(importer, "_validate_artifact_hashes", original)
    summary = importer.import_legacy_project(source)
    assert summary["experiment_id"]


def test_view_rejects_non_loopback_bind():
    with pytest.raises(ValueError, match="loopback"):
        view(host="0.0.0.0", open_browser=False)


def test_server_health_identifies_its_autoexp_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    server = AutoexpHTTPServer(("127.0.0.1", 0), AutoexpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(f"{base}/api/health", timeout=3) as response:
            health = json.load(response)
        assert health["data_root"] == str((tmp_path / "home").resolve())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_ensure_server_does_not_reuse_a_server_for_another_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    expected_root = str((tmp_path / "home").resolve())
    health_checks = []
    launches = []

    def healthy(host, port, expected_data_root=None):
        health_checks.append((host, port, expected_data_root))
        return port == 43210 and str(expected_data_root) == expected_root

    monkeypatch.setattr(server_module, "_healthy", healthy)
    monkeypatch.setattr(server_module, "_port_available", lambda *_: False)
    monkeypatch.setattr(server_module, "_free_port", lambda *_: 43210)
    monkeypatch.setattr(
        server_module.subprocess,
        "Popen",
        lambda args, **kwargs: launches.append((args, kwargs)) or SimpleNamespace(poll=lambda: None),
    )

    url, process = server_module.ensure_server(port=8765)

    assert url == "http://127.0.0.1:43210"
    assert process is not None
    assert health_checks[0][:2] == ("127.0.0.1", 8765)
    assert str(health_checks[0][2]) == expected_root
    assert launches[0][0][launches[0][0].index("--port") + 1] == "43210"


def test_view_uses_a_fresh_port_for_another_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    addresses = []

    monkeypatch.setattr(server_module, "_healthy", lambda *_: False)
    monkeypatch.setattr(server_module, "_port_available", lambda *_: False)
    monkeypatch.setattr(server_module, "_free_port", lambda *_: 43211)

    class FakeServer:
        server_port = 43211

        def __init__(self, address, _handler, _allow_origins):
            addresses.append(address)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(server_module, "AutoexpHTTPServer", FakeServer)

    view(port=8765, open_browser=False)

    assert addresses == [("127.0.0.1", 43211)]


def test_research_restore_only_reverts_agent_subject(tmp_path, monkeypatch):
    entry = research_experiment(tmp_path, monkeypatch)
    research = AutoResearch(entry["experiment_id"])
    contract = research.state()["contract"]
    repo = Path(entry["repo_path"])
    (repo / "candidate.py").write_text("print('changed candidate')\n")
    candidate = capture_workspace(
        entry["experiment_id"], parent_snapshot_id=contract["best_snapshot_id"]
    )
    (repo / "program.md").write_text("user changed the program\n")

    research._restore_snapshot(
        contract["best_snapshot_id"], contract["subject_path"], candidate["snapshot_id"]
    )

    assert (repo / "candidate.py").read_text() == "print('candidate')\n"
    assert (repo / "program.md").read_text() == "user changed the program\n"

    (repo / "candidate.py").write_text("print('newer candidate')\n")
    with pytest.raises(ValueError, match="newer candidate changes"):
        research._restore_snapshot(
            contract["best_snapshot_id"], contract["subject_path"], candidate["snapshot_id"]
        )
    assert (repo / "candidate.py").read_text() == "print('newer candidate')\n"


def test_restore_refuses_modified_ignored_source(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "main.py").write_text("print('ok')\n")
    (repo / "ignored.txt").write_text("snapshot value\n")
    entry = create_experiment("test ignored restore", root=repo, entrypoint="main.py")
    declare_file(entry["experiment_id"], "ignored.txt", "supporting-source")
    commit_repo(repo, "initial")
    run = execute(entry["experiment_id"])

    (repo / "ignored.txt").write_text("uncommitted ignored value\n")
    assert subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout == ""
    with pytest.raises(ValueError, match="ignored.txt"):
        restore_run_state(run["run_id"], entry["experiment_id"])


def test_only_secret_environment_values_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / ".env").write_text("DEBUG=1\n")
    (repo / "main.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path(os.environ['AUTOEXP_OUTPUT_DIR'], 'metrics.json').write_text(json.dumps({\n"
        "    'tag': os.environ['AUTOEXP_RESEARCH_TAG'],\n"
        "    'budget': os.environ['AUTOEXP_RESEARCH_BUDGET_SEC'],\n"
        "    'debug': os.environ['DEBUG'],\n"
        "    'token': os.environ['API_TOKEN'],\n"
        "}))\n"
    )
    entry = create_experiment(
        "test selective redaction",
        root=repo,
        entrypoint="main.py",
        config={"external_inputs": [{"name": "API_TOKEN", "kind": "secret"}]},
    )
    run = execute(entry["experiment_id"], environment={
        "AUTOEXP_RESEARCH_TAG": "a01",
        "AUTOEXP_RESEARCH_BUDGET_SEC": "300",
        "API_TOKEN": "abc123",
    })

    metrics = json.loads(
        (run_dir_for(run, entry["experiment_id"]) / "output/metrics.json").read_text()
    )
    assert metrics == {
        "tag": "a01",
        "budget": "300",
        "debug": "1",
        "token": "[redacted]",
    }


def test_timeout_failure_message_redacts_short_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    entry = create_experiment(
        "test timeout redaction",
        root=repo,
        entrypoint="main.py",
        config={"external_inputs": [{"name": "API_TOKEN", "kind": "secret"}]},
    )

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            ["docker", "run", "-e", "API_TOKEN=abc123"], 1
        )

    monkeypatch.setattr("autoexp.execution.run_script_local", timeout)
    run = execute(entry["experiment_id"], environment={"API_TOKEN": "abc123"})

    assert run["status"] == "failed"
    assert run["failure_kind"] == "timeout"
    assert "abc123" not in run["failure_message"]
    assert "[redacted]" in run["failure_message"]


def _old_snapshot_hashes(root, config):
    script = hashlib.sha256()
    for path in sorted((root / "experiment").rglob("*")):
        if path.is_file():
            script.update(path.relative_to(root / "experiment").as_posix().encode())
            script.update(b"\0")
            script.update(path.read_bytes())
            script.update(b"\0")

    def file_hash(path):
        return hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()

    runtime = {
        key: config[key]
        for key in ("runner", "sandbox", "runtime")
        if key in config
    }
    hashes = {
        "script_hash": script.hexdigest(),
        "params_hash": file_hash(root / ".autoexp/params.json"),
        "manifest_hash": file_hash(root / ".autoexp/stage.json"),
        "runtime_config_hash": hashlib.sha256(
            json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    hashes["source_hash"] = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return hashes


def test_imports_and_executes_real_legacy_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    source = git_repo(tmp_path / "legacy")
    control = source / ".autoexp"
    experiment = source / "experiment"
    control.mkdir()
    experiment.mkdir()
    config = {
        "title": "legacy",
        "description": "A real 0.2 layout",
        "runner": "local",
        "sandbox": {
            "image": "python:3.12-slim",
            "network": "none",
            "cpus": "1",
            "memory": "512m",
        },
        "runtime": {},
        "report_instruction_file": ".autoexp/custom-report.md",
        "source": {"root": "experiment", "editable": ["main.py"]},
    }
    stage = {
        "name": "main.py",
        "command": "python main.py --ctx ${CTX}",
        "working_dir": "experiment",
        "interface_version": "1",
    }
    (control / "project.json").write_text(json.dumps(config))
    (control / "stage.json").write_text(json.dumps(stage))
    (control / "params.json").write_text("{}")
    (control / "params.schema.json").write_text(
        json.dumps({"type": "object", "properties": {}})
    )
    (control / "instructions.md").write_text("Legacy agent guidance.\n")
    (control / "custom-report.md").write_text("Keep this custom report guidance.\n")
    (experiment / "main.py").write_text("print('legacy run')\n")
    commit_repo(source, "legacy snapshot")
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(source), str(control / "repository")],
        check=True,
    )

    hashes = _old_snapshot_hashes(source, config)
    old = sqlite3.connect(control / "state.sqlite")
    old.execute(
        """create table source_snapshots(
             snapshot_id text primary key, project_id text not null,
             parent_snapshot_id text, git_commit text not null,
             script_hash text not null, params_hash text not null,
             manifest_hash text not null, runtime_config_hash text not null,
             source_hash text not null, created_at text not null,
             created_by_trigger_id text, label text, legacy_run_id text
           )"""
    )
    old.execute(
        """insert into source_snapshots values(
             'legacy_snapshot', 'legacy_project', null, ?, ?, ?, ?, ?, ?,
             '2025-01-01T00-00-00Z', null, 'Legacy snapshot', null
           )""",
        (
            commit,
            hashes["script_hash"],
            hashes["params_hash"],
            hashes["manifest_hash"],
            hashes["runtime_config_hash"],
            hashes["source_hash"],
        ),
    )
    old.commit()
    old.close()

    summary = importer.import_legacy_project(source)
    experiment_id = summary["experiment_id"]
    assert summary["validated"]["snapshot_hashes"] == {"checked": 1, "ok": True}
    assert experiment_entry(experiment_id)["report_guidance"] == "Keep this custom report guidance.\n"

    restored = tmp_path / "restored-legacy"
    materialize_snapshot("legacy_snapshot", restored, experiment_id)
    assert snapshot_matches(hashes, restored)
    run = execute(experiment_id, snapshot_id="legacy_snapshot")
    assert run["status"] == "success"
    assert [item["path"] for item in run_source(run["run_id"], experiment_id)["files"]] == [
        "experiment/main.py"
    ]


def test_downloads_stream_complete_artifact_and_log(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    output_size = 16 * 1024 * 1024 + 257
    (repo / "main.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"Path(os.environ['AUTOEXP_OUTPUT_DIR'], 'large.bin').write_bytes(b'x' * {output_size})\n"
        "print('L' * 70000)\n"
    )
    entry = create_experiment("test complete downloads", root=repo, entrypoint="main.py")
    run = execute(entry["experiment_id"])
    artifact = next(
        item for item in list_artifacts(run["run_id"], entry["experiment_id"], "output")
        if item["path"] == "output/large.bin"
    )

    server = AutoexpHTTPServer(("127.0.0.1", 0), AutoexpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/runs/{run['run_id']}"
    try:
        with urlopen(
            f"{base}/artifacts/{artifact['artifact_id']}/content?download=1",
            timeout=30,
        ) as response:
            assert response.read() == b"x" * output_size
        with urlopen(f"{base}/logs/stdout?download=1", timeout=30) as response:
            assert response.read() == b"L" * 70000 + os.linesep.encode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_runner_receives_only_declared_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DECLARED_SETTING", "ambient-value")
    monkeypatch.setenv("UNDECLARED_API_TOKEN", "ambient-secret")
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path(os.environ['AUTOEXP_OUTPUT_DIR'], 'env.json').write_text(json.dumps({\n"
        "    'declared': os.environ.get('DECLARED_SETTING'),\n"
        "    'undeclared': os.environ.get('UNDECLARED_API_TOKEN'),\n"
        "}))\n"
    )
    entry = create_experiment(
        "test explicit environment",
        root=repo,
        entrypoint="main.py",
        config={"external_inputs": [{"name": "DECLARED_SETTING", "kind": "env"}]},
    )

    run = execute(entry["experiment_id"])

    result = json.loads(
        (run_dir_for(run, entry["experiment_id"]) / "output/env.json").read_text()
    )
    assert result == {"declared": "ambient-value", "undeclared": None}


def test_redaction_crosses_streaming_chunk_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    secret = "boundary-secret-value"
    (repo / "main.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "prefix = 'x' * (1024 * 1024 - 5)\n"
        "value = prefix + os.environ['API_TOKEN']\n"
        "print(value)\n"
        "Path(os.environ['AUTOEXP_OUTPUT_DIR'], 'value.txt').write_text(value)\n"
    )
    entry = create_experiment(
        "test streaming redaction",
        root=repo,
        entrypoint="main.py",
        config={"external_inputs": [{"name": "API_TOKEN", "kind": "secret"}]},
    )

    run = execute(entry["experiment_id"], environment={"API_TOKEN": secret})
    run_dir = run_dir_for(run, entry["experiment_id"])

    for path in (run_dir / "logs/script.stdout.log", run_dir / "output/value.txt"):
        text = path.read_text()
        assert secret not in text
        assert "[redacted]" in text


def test_global_storage_is_private_by_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("AUTOEXP_HOME", str(home))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")

    create_experiment("test private storage", root=repo, entrypoint="main.py")

    assert (home / "state.sqlite").is_file()
    if os.name != "nt":
        assert home.stat().st_mode & 0o777 == 0o700
        assert (home / "state.sqlite").stat().st_mode & 0o777 == 0o600


def test_docker_runner_hardens_container_without_secret_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    repo = git_repo(tmp_path / "repo")
    (repo / "main.py").write_text("print('ok')\n")
    entry = create_experiment(
        "test hardened Docker command",
        root=repo,
        entrypoint="main.py",
        runner="docker",
    )
    source = tmp_path / "source"
    materialize_workspace(entry["experiment_id"], source)
    run_dir = tmp_path / "run"
    for name in ("output", "logs", "report"):
        (run_dir / name).mkdir(parents=True)
    captured = {}

    def fake_run(command, *_args, **_kwargs):
        captured["command"] = command
        env_path = Path(command[command.index("--env-file") + 1])
        captured["environment"] = env_path.read_text()
        return 0

    monkeypatch.setattr(runner, "_run_process", fake_run)
    runner.run_script(
        run_dir,
        root=entry["experiment_id"],
        source_root=source,
        extra_env={"API_TOKEN": "not-in-process-arguments"},
    )

    command = captured["command"]
    assert {"--cap-drop", "--read-only", "--pids-limit", "--security-opt"} <= set(command)
    assert f"{run_dir.resolve()}:/workspace/run:ro" in command
    assert "not-in-process-arguments" not in "\0".join(command)
    assert captured["environment"] == "API_TOKEN=not-in-process-arguments\n"


def test_http_server_rejects_non_loopback_host_header():
    server = AutoexpHTTPServer(("127.0.0.1", 0), AutoexpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("GET", "/api/health", headers={"Host": "attacker.example"})
        response = connection.getresponse()
        assert response.status == 421
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_legacy_import_rejects_symlinked_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEXP_HOME", str(tmp_path / "home"))
    source = tmp_path / "legacy"
    control = source / ".autoexp"
    experiment = source / "experiment"
    control.mkdir(parents=True)
    experiment.mkdir()
    (control / "project.json").write_text(json.dumps({"title": "legacy", "runner": "local"}))
    sqlite3.connect(control / "state.sqlite").close()
    subprocess.run(["git", "init", "--bare", "-q", str(control / "repository")], check=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be imported\n")
    (experiment / "linked.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        importer.import_legacy_project(source)
