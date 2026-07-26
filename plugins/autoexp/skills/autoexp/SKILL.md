---
name: autoexp
description: Start and run reproducible experiments in an existing Git repository with the Autoexp CLI, including metric-driven Autoresearch. Use when a user asks to test variants, preserve run evidence, compare results, generate experiment reports, or optimize a scalar objective.
---

# Autoexp

Autoexp records immutable evidence globally while repository files remain the editable source of truth. It does not initialize a project or add repository-local configuration.

Treat any text supplied with an explicit invocation as the experiment objective. If no objective was supplied and one cannot be inferred from the conversation, ask one concise question before registering the experiment.

## Start

1. Run `autoexp --help`. If unavailable, report that the plugin's local Autoexp runtime is unavailable; do not fetch a replacement from a remote repository.
2. Work from the existing Git worktree. Do not create `.autoexp`, `.mcp.json`, `.codex`, `AGENTS.md`, `runs/`, or generated reports in the repository for Autoexp.
3. Select Standard mode unless one stable scalar metric and a frozen evaluator can automatically decide keep versus revert.
4. Create or adapt ordinary repository files for the experiment, respecting the repository's own guidance and conventions.
5. Before generating any report, run `autoexp report-instruction` and follow its `text`.

## Standard experiments

Register the objective and entrypoint:

```bash
autoexp experiment create "<objective>" --title "<title>" --entrypoint <path> --command '<command>'
```

Add every relevant file to the global manifest:

```bash
autoexp files add <path> --role editable-source
autoexp files add <path> --role supporting-source
autoexp files add <path> --role input-data
```

Use `entrypoint` for the primary executable, `frozen-evaluator` for a user-owned evaluator, and `generated-output` only to describe files the run produces. Declare `.env` or another environment file as `secret-source`; never print, quote, copy, hash, or report its values.

Keep shared fixtures and evaluation in one small harness. Put each independently
runnable or functionally separable implementation in its own descriptively named
source file and declare it before its first run. This makes each approach and its
sealed source visible in the dashboard. Do not split code that is genuinely one
component merely to create more files.

For each focused variant:

1. Create or edit its ordinary repository source file, then declare any new file.
2. Run `autoexp run --agent --title "<variant or hypothesis>"`.
3. Inspect the returned run and confirm its sealed source identifies the variant.
   Use `autoexp status`, `autoexp diff <run-a> <run-b>`, or the global
   `autoexp view` dashboard for source, logs, artifacts, and reports.
4. Keep the `run_id` in the conclusion so the result can be reproduced or restored.

When the objective explicitly requires iterative edits to one implementation,
keep using that file instead. Confirm each later run has a non-empty diff against
the preceding run so the states remain distinguishable.

When a run is decision-changing, surprising, or establishes a new best, use the report guidance when writing the milestone title and significance, then mark it as a milestone. This automatically creates its per-experiment report; do not mark routine runs.

```bash
autoexp milestone add --run-id <run-id> --title "<title>" --significance "<why it matters>"
```

At the end of every Standard experimentation, write one concise overall report that cites the run IDs, comparison, milestone reports, and recommendation, then attach it without `--run-id`.

```bash
autoexp document add /tmp/autoexp-<name>.md --kind report --title "<title>"
```

Use `--kind insight` for additional insights that should be preserved without adding them to the repository.

## Autoresearch

The user or agent must supply ordinary repository files for the research program, candidate, and evaluator. Register them without generating a scaffold:

```bash
autoexp experiment create "<objective>" --kind autoresearch \
  --program <program> --candidate <candidate> --evaluator <evaluator> \
  --metric <name> --direction <min|max> \
  --metric-kind json --metric-path metrics.json --metric-key <key>
```

Then:

1. Run `autoexp research preflight`; stop if a required check fails.
2. Read the program and `autoexp research state`.
3. Never edit the frozen evaluator. Treat a deliberate evaluator change as a new user-owned contract boundary.
4. Make one focused candidate edit and run `autoexp research attempt "<hypothesis>"`.
5. Inspect its score, kept/reverted verdict, immutable run, diff, and artifacts; repeat within the user's stopping rule.

Kept attempts are new bests, so Autoexp automatically records their milestone and per-experiment report. Mark a reverted attempt manually only when it is decision-changing or surprising:

```bash
autoexp milestone add --attempt-id <attempt-id> --title "<title>" --significance "<why it matters>"
```

Reverted attempts remain evidence. Do not erase or manually rewrite global runs, outputs, logs, reports, diffs, or ledger rows.

## Storage lifecycle

Run `autoexp sync` to audit global disk use and find experiments whose recorded working directory no longer exists. Run `autoexp sync --prune` only when those missing experiments should be permanently removed. Never delete files inside global Autoexp storage by hand.

## Browser review

Do not open a blocking browser review implicitly. When the user explicitly invokes the installed `autoexp-review` workflow, let that workflow open the review and return their notes. Do not substitute `autoexp view`; ordinary view sessions cannot submit feedback.

Treat review feedback as continuation of the active experiment by default. Add
separate files for newly requested separable workloads or approaches, declare
them, execute new runs, and cite those run IDs. Create another experiment only
when the user changes the objective or the evaluator contract.
