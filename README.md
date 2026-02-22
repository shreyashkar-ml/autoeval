# autoeval

`autoeval` is a terminal-first harness for long-running autonomous coding workflows with resumable sessions, policy-gated actions, and structured RPI artifacts.

## What Is Implemented

1. **RPI artifacts** with template-driven generation:
   - `.autoeval/instructions/research.md`
   - `.autoeval/instructions/plan.md`
   - `.autoeval/instructions/feature_list.json`
2. **Execution loop** with run/session artifacts:
   - `events.jsonl`, `progress.md`, `session_meta.json`, `usage.json`, `metrics.json`
   - snapshots + checkpoints for handoff/fork workflows
3. **Reference-style multi-agent parity (without Linear)**:
   - orchestrator + coding + github + slack role model
   - delegation trace recorded in events
   - Slack/GitHub operation artifacts written per run
4. **Security guardrails for shell actions**:
   - command allowlist + sensitive command validators in `autoeval/security.py`
   - policy gate in `autoeval/policy.py` before execution
5. **MCP lifecycle management**:
   - `mcp list/add/remove/enable/disable/connect/disconnect/set-auth`
   - runtime profile resolution with preflight checks
6. **Evaluation harness and completion gate**:
   - `autoeval/evals.py` runs deterministic eval checks against run artifacts
   - task completion is gated by eval pass unless bypassed

## Install

```bash
uv venv
uv sync --extra dev
uv run autoeval --help
```

## Quickstart (Step-by-Step)

```bash
# 1) Initialize harness files in target repo
uv run autoeval init \
  --repo . \
  --provider codex \
  --task "Implement feature set"

# 2) Run autonomous loop
uv run autoeval run \
  --repo . \
  --provider codex \
  --task "Implement feature set"

# 2.1) Optional: bypass eval gating for experimental runs
uv run autoeval run \
  --repo . \
  --provider codex \
  --task "Implement feature set" \
  --no-require-eval-pass

# 3) Check current run status
uv run autoeval status --repo .

# 4) Resume previous run if needed
uv run autoeval resume \
  --repo . \
  --provider codex \
  --task "Continue implementation"

# 5) Request intervention when blocked
uv run autoeval intervene \
  --repo . \
  --reason "Need product clarification"

# 6) Emit structured review
uv run autoeval review --repo . --severity medium

# 7) Re-run eval suite explicitly
uv run autoeval eval --repo . --profile default
```

## Slack/GitHub Artifact Flow

During execution, orchestrated actions generate:
- `.autoeval/runs/<run_id>/communications/slack_messages.jsonl`
- `.autoeval/runs/<run_id>/vcs/github_operations.jsonl`

Manual Slack notification is also available:

```bash
uv run autoeval notify \
  --repo . \
  --channel new-channel \
  --message "Session progress update"
```

## MCP + Browser Validation Example

```bash
uv run autoeval mcp add \
  --scope user \
  --name puppeteer \
  --transport stdio \
  --command "echo puppeteer" \
  --tool-namespace puppeteer \
  --repo .

uv run autoeval mcp connect --repo . --name puppeteer

uv run autoeval test browser \
  --repo . \
  --mcp puppeteer \
  --scenario "open homepage and verify key UI"
```

## Security Model

`run` actions are enforced by:
1. static + runtime policy checks (`autoeval/policy.py`)
2. command allowlist and targeted validators (`autoeval/security.py`)
3. repository path boundary checks (`autoeval/executor.py`)

Sensitive commands such as dangerous `rm`, unrestricted `chmod`, and unsafe `pkill` patterns are blocked.

## Testing

```bash
uv run pytest phase_test/tests
```

Current baseline: `32 passed`.

## License

Apache License 2.0. See `LICENSE`.
