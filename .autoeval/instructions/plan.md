# Plan: Update `guide_docs/` to Match Current Repository State

## Phase Breakdown
- Phase 1 focuses on factual baseline extraction from source-of-truth modules and tests.
- Phase 2 updates documentation content in `guide_docs/` with scoped, surgical edits.
- Phase 3 performs validation and handoff evidence capture.

### Phase 1 - Baseline Diff and Scope Lock
- Objective: Build a precise diff between current implementation and existing guide docs.
- In scope: Inspect `autoeval/*.py`, `README.md`, `scripts/smoke.sh`, `phase_test/tests/*`, and `guide_docs/*.md`.
- Out of scope: Any runtime behavior/code changes outside docs.
- Dependencies/assumptions: Repository reflects current implementation; tests encode expected behavior.
- Strict constraints:
  - Read-only inspection first.
  - No edits outside `guide_docs/`.
  - Follow `.gitignore` awareness; include ignored paths only when directly relevant.
- Planned file/script touchpoints:
  - `guide_docs/technical_overview.md`: align architecture/state paths/flows.
  - `guide_docs/roadmap.md`: align status snapshot and file layout claims.
  - `guide_docs/idea.md`: align capability language with implemented provider/tool model.
  - Source references for truth: `autoeval/cli.py`, `autoeval/rpi.py`, `autoeval/executor.py`, `autoeval/orchestrator.py`, `phase_test/tests/test_prompts_and_integrations.py`.
- Skeletal change snippet(s):
  - Replace legacy path mentions:
    - `.autoeval/rpi/*` -> `.autoeval/instructions/*`
    - remove `implementation.md` references where not implemented in current template set.
- Relevant code references:
  - `autoeval/config.py` (`RepoPaths.rpi_dir` -> `.autoeval/instructions`).
  - `autoeval/rpi.py` (`ARTIFACT_FILENAMES` only research/plan/feature_list).
  - `phase_test/tests/test_prompts_and_integrations.py` asserts no `.autoeval/rpi` and yes `.autoeval/instructions/research.md`.
- Validation:
  - Manual content diff against source modules.
- Exit criteria:
  - Concrete mismatch list prepared per guide document.

### Phase 2 - Documentation Rewrite (Surgical)
- Objective: Update `guide_docs/` docs so architecture, commands, and artifact layout match current code.
- In scope: Content edits in selected guide markdown files and command/example corrections.
- Out of scope: Template schema changes, CLI code changes, test changes.
- Dependencies/assumptions: Phase 1 mismatch inventory complete.
- Strict constraints:
  - Preserve intent/history where still valid.
  - Do not invent unsupported behavior.
  - Keep terminology consistent: framework repo vs target repo artifacts.
- Planned file/script touchpoints:
  - `guide_docs/technical_overview.md`: correct state tree, command flows, and policy/security descriptions.
  - `guide_docs/roadmap.md`: update implemented-status section and structure examples.
  - `guide_docs/idea.md`: tighten feature statements to currently supported providers/integrations.
- Skeletal change snippet(s):
  - Example structural correction:
    - `rpi/research.md` -> `instructions/research.md`
    - `rpi/plan.md` -> `instructions/plan.md`
    - `rpi/feature_list.json` -> `instructions/feature_list.json`
  - Example command correction:
    - ensure examples match `autoeval` commands exposed in `cli.py` (`init`, `run`, `resume`, `status`, `intervene`, `fork`, `review`, `notify`, `eval`, `mcp *`, `test browser`).
- Relevant code references:
  - `autoeval/cli.py`, `autoeval/orchestrator.py`, `autoeval/evals.py`, `autoeval/connectors.py`.
- Validation:
  - `rg` checks to ensure removed legacy path strings and unsupported claims are not present.
- Exit criteria:
  - Updated guide docs contain only currently supported architecture/flows.

### Phase 3 - Verification and Handoff
- Objective: Prove docs now reflect implementation and provide handoff notes.
- In scope: Consistency checks, command/reference verification, summary of remaining unknowns.
- Out of scope: Additional feature implementation.
- Dependencies/assumptions: Phase 2 edits complete.
- Strict constraints:
  - Validation must be observable via commands or explicit file content checks.
- Planned file/script touchpoints:
  - `guide_docs/*.md` (final verification).
  - Optional reference commands against `README.md` and `scripts/smoke.sh` for command parity.
- Skeletal change snippet(s):
  - Verification command set:
    - `rg -n "\.autoeval/rpi|implementation\.md" guide_docs`
    - `rg -n "autoeval (init|run|resume|status|eval|review|notify|intervene|fork|mcp|test browser)" guide_docs`
- Relevant code references:
  - `scripts/smoke.sh` command chain.
  - `README.md` quickstart command list.
- Validation:
  - Manual pass plus grep-based checks.
- Exit criteria:
  - No stale path/model claims remain in `guide_docs/` for inspected areas.

## Risk, rollback, and handoff
- Risks:
  - Over-correction that removes useful roadmap context.
  - Missing low-visibility behavior details not covered in overview docs.
- Rollback:
  - Revert only modified `guide_docs/*` files if a correction introduces inaccuracies.
- Handoff instructions:
  - Attach mismatch list, edited files list, and grep validation outputs.
  - Note any intentionally deferred documentation sections.
