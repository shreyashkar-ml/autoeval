<p align="center">
  <img src="assets/dark.svg" alt="Autoexp" width="480">
</p>

# autoexp

Track your autonomous research and experimentation, send follow-up feedbacks, and analyze reports and insights with **`autoexp`** — a local, browser-based experimentation surface for AI coding agents: Claude Code, Codex, OpenCode, Pi.

AI agents are already good at proposing code. The harder problem is the harness around those proposals: source boundaries, reproducible execution, external inputs, evaluators, artifacts, lineage, rollback, and human review. Autoexp supplies that infrastructure while your repository remains the editable source of truth.

Explore the workflow and installation options at [autoexp.dev](https://autoexp.dev).

<table>
  <tr>
    <td width="36%">
      <h3>Standard Experiments</h3>
      <p>Compare variants, inspect immutable evidence, and turn results into a clear recommendation.</p>
    </td>
    <td width="64%">
      <img src="assets/readme-standard.webp?v=20260727" alt="Autoexp dashboard showing experiment variants, immutable run evidence, milestones, and the project report">
    </td>
  </tr>
  <tr>
    <td width="36%">
      <h3>Autoresearch</h3>
      <p>Optimize a measurable objective with a frozen evaluator and a keep-or-revert loop.</p>
    </td>
    <td width="64%">
      <img src="assets/readme-autoresearch.webp?v=20260727" alt="Autoexp Autoresearch dashboard showing the scored loop, final state, and attempt ledger">
    </td>
  </tr>
</table>

## Install and connect your agent

Run:

```bash
curl -fsSL https://autoexp.dev/install.sh | bash
```

Restart your coding agent, open a repository, and start with an objective.

## Use Autoexp from your agent

Autoexp exposes two agent workflows:

| Workflow | Codex | Claude Code | OpenCode | Pi |
| --- | --- | --- | --- | --- |
| Start or continue experiments | `$autoexp <objective>` | `/autoexp <objective>` | `/autoexp <objective>` | `/autoexp <objective>` |
| Open browser feedback review | `$autoexp-review` | `/autoexp-review` | `/autoexp-review` | `/autoexp-review` |

### Start experimenting in your repository

```text
/autoexp Compare the cache strategies in this repository. Reuse the existing
replay benchmark, preserve every run, and recommend a winner from the evidence.
```

**Autoexp** understands the objective, works with the code, data, and evaluators
already in your repository, and preserves every result.

```text
You define the objective and success criteria
          ↓
Your agent proposes a focused repository change
          ↓
Autoexp pins execution and seals the resulting evidence
          ↓
A metric or human review decides what happens next
```

### Review results with the agent

Invoke the review workflow when you want to inspect results or steer the next step:

```text
/autoexp-review
```

The review command opens a local browser session immediately. You can inspect
source, rendered artifacts, CSV tables, images, logs, reports, and diffs.
Add notes and submit one feedback batch. Your agent receives it and continues
the experiment.

<p align="center">
  <img src="assets/readme-review.webp?v=20260727" alt="Autoexp review showing experiment evidence, the waiting agent state, and the feedback composer" width="100%">
</p>

### Dashboard view

Use `autoexp view` to browse and download experiments, runs, artifacts, reports,
metrics, and diffs in one place.

### Execution trust boundary

The local runner executes trusted experiment code as your operating-system user; it is not a sandbox. Use the Docker runner for generated or untrusted programs. Docker runs drop capabilities, prevent privilege escalation, use read-only source/run mounts, and expose only output/report directories as writable, but they may still have network access if enabled and are not a hardened multi-tenant sandbox.

Runs receive only declared, file-backed, or explicitly supplied environment values. Autoexp redacts known raw secret values from recorded evidence, but cannot recognize encoded, hashed, split, or transformed secrets. Use short-lived, least-privilege credentials and review evidence before publishing it.

## Direct CLI reference

Use these commands for history, automation, and direct control:

| Task | Command |
| --- | --- |
| Show registered experiments | `autoexp experiment list` |
| Inspect recent runs | `autoexp status` |
| Open the global dashboard | `autoexp view` |
| Compare two immutable runs | `autoexp diff <run-a> <run-b>` |
| Restore declared source from a run | `autoexp restore <run-id>` |
| Check the selected experiment and runtime | `autoexp doctor` |
| Open a blocking agent review | `autoexp review` |

## Local data and secrets

Autoexp stores experiment history and restorable snapshots locally. Repository
files stay in their original locations. Declared secret-source files are
excluded from snapshots and browser reads. Review screens display recorded
outputs, so keep sensitive values outside experiment outputs.

Default data directory:

- Linux: `$XDG_DATA_HOME/autoexp` or `~/.local/share/autoexp`
- macOS: `~/Library/Application Support/autoexp`
- Windows: `%LOCALAPPDATA%/autoexp`

Set `AUTOEXP_HOME` to override it. Use `autoexp relink <repo-id> <new-path>` if a worktree moves.
