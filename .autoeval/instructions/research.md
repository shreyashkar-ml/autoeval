# Repository Baseline Research

## 1. Repository tree/map with one-line descriptions
- `README.md`: user-facing quickstart and capability summary for the harness.
- `pyproject.toml`: package metadata, dependency set (`typer`, `pydantic`), CLI entrypoint (`autoeval`).
- `scripts/smoke.sh`: end-to-end smoke command chain for init/run/status/eval/mcp/browser/review.
- `autoeval/cli.py`: Typer CLI surface for init/run/resume/status/intervene/fork/review/notify/mcp/test/eval.
- `autoeval/orchestrator.py`: multi-session run loop, completion/stuck handling, eval gate integration, metrics emission.
- `autoeval/executor.py`: single-session execution engine (provider call, policy check, action execution, artifact writes).
- `autoeval/rpi.py`: template loading, bootstrap detection, provider bootstrap commit path, RPI artifact normalization.
- `autoeval/agent_contract.py`: `TaskEnvelope`, action/result schemas, default allowed actions and success-criteria derivation.
- `autoeval/providers.py`: provider adapter interface and structured-output schema contracts.
- `autoeval/policy.py`: static/runtime policy gate (allowed actions, no-network token checks, runtime approvals).
- `autoeval/security.py`: shell command allowlist and targeted validators (`rm`, `chmod`, `pkill`, `init.sh`).
- `autoeval/connectors.py`: MCP profile lifecycle, runtime profile resolution, Slack/GitHub/browser artifact writers.
- `autoeval/evals.py`: deterministic eval checks and run report writer.
- `autoeval/tracker.py`: feature list status updates, immutability guardrails, rebaseline flow.
- `autoeval/migrations.py`: schema version normalization across repo/user state artifacts.
- `autoeval/review.py`: structured review report based on incomplete subtasks and run artifact presence.
- `autoeval/prompts/`: orchestrator/initializer/continuation prompt templates and app spec.
- `autoeval/templates/`: template instructions for research/plan/feature_list artifacts.
- `autoeval/schemas/agent_contract.v1.json`: exported contract schema.
- `phase_test/tests/`: regression suite covering CLI, orchestrator, security, connectors, evals, prompts, tracker, migrations.
- `guide_docs/`: product/architecture notes to be updated (currently ignored in `.gitignore` but directly relevant to requested task).

## 2. Project directory and script structures
- `autoeval/`: runtime framework package; all production behavior originates here.
- `autoeval/prompts/*.md|*.txt`: prompt text consumed at session bootstrap (`initializer` vs `continuation`) and copied app spec.
- `autoeval/templates/*.md`: canonical instruction templates used by bootstrap prompt generation.
- `scripts/smoke.sh`: reference operator script for manual validation in a target repo.
- `phase_test/tests/*.py`: expected behavior contract for current implementation (includes explicit checks that `.autoeval/instructions/*` is current path and legacy `.autoeval/rpi` is removed).

## 3. Core functionality and module responsibilities
- CLI command routing is centralized in `autoeval/cli.py`; each command resolves `RepoPaths`, ensures layout, and delegates to module-specific logic.
- Session orchestration in `autoeval/orchestrator.py` repeatedly invokes `execute_session` until all `feature_list.json` subtasks are true or stopping conditions trigger.
- Provider session handling in `autoeval/executor.py` builds task envelope, runs provider, executes approved actions, commits provider-supplied RPI artifacts, and records run telemetry.
- Artifact truth model:
  - Research + plan are markdown.
  - Feature list is JSON with immutable non-status fields (enforced by `tracker.py`).
- Completion policy:
  - Candidate completion requires all subtask statuses true.
  - Eval suite runs and can block final completion when `require_eval_pass` is enabled.

## 4. End-to-end flow traces
- `autoeval init`:
  - `cli.init` -> layout + migrations + state touch -> provider bootstrap via `bootstrap_rpi_with_provider` -> writes `.autoeval/instructions/{research.md,plan.md,feature_list.json}`.
- `autoeval run`:
  - `cli.run` -> `orchestrator.run_task` -> loop `executor.execute_session` -> status updates -> optional `evals.run_eval_suite` -> `metrics.json`.
- `execute_session` inner path:
  - provider connect -> task envelope build (with prompt mode and RPI instructions) -> provider response parse -> optional RPI artifact commit -> per-action policy evaluation -> action execution/denial logging -> completion updates only if no failed/denied actions -> snapshot/checkpoint/progress/meta/usage writes.
- MCP/browser flow:
  - CLI `mcp add/connect/...` -> connectors registry + health updates.
  - `test browser` writes browser evidence artifacts under run directory.

## 5. Integration methodology and external dependencies
- Python runtime dependencies: `typer`, `pydantic`.
- Provider adapters are pluggable through `providers.py` and a shared `ProviderAdapter` contract.
- Optional integrations are artifact-first (Slack/GitHub/MCP) and recorded as JSONL in run directories.
- No dedicated DB/queue/service dependency in current baseline; persistence is file-based JSON/JSONL/MD under `.autoeval/` and `$AUTOEVAL_HOME`.

## 6. Deployment/runtime/testing setup
- Install/runtime:
  - `uv venv`
  - `uv sync --extra dev`
  - `uv run autoeval --help`
- Test command: `uv run pytest phase_test/tests`.
- Entry point: `autoeval = autoeval.cli:app` from `pyproject.toml`.
- Runtime assumptions:
  - target repo path passed via `--repo`.
  - local filesystem writable in normal operation for `.autoeval/*` outputs.
  - provider adapter reachable by configured binary/env.

## 7. Known gaps, risks, and unknowns
- Documentation drift risk is currently high in `guide_docs/`:
  - Existing docs reference legacy paths and artifacts (`.autoeval/rpi`, `implementation.md`) while current implementation uses `.autoeval/instructions/*` and three primary artifacts.
- `guide_docs/` is gitignored; updates may not be tracked unless workflow intentionally stages ignored docs.
- Runtime constraint mismatch risk:
  - Task-level plan should avoid implying unsupported integrations (e.g., Linear) since current tested artifact flow is Slack/GitHub + MCP profiles.
- Evidence needed to fully close unknowns:
  - Cross-check each guide document against current CLI surface and file layout from `cli.py`, `rpi.py`, and tests asserting expected paths.
  - Validate guide command examples against `scripts/smoke.sh` and README command set.
