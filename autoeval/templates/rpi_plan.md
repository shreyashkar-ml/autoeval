<!-- template_id: rpi_plan -->
<!-- template_version: 2.2.0 -->

# Planning Artifact Instruction

Purpose:
- Decompose the current task into phase-level execution strategy.
- Use phases separated by core logic/component boundaries.
- Keep this artifact at phase granularity, not sub-task granularity.

## Request Context
- task: {task}
- constraints: {constraints}
- acceptance_targets: {acceptance_targets}
- provider_capabilities: {provider_capabilities}

## Required Sections
1. Phase breakdown with explicit boundaries (what is in scope/out of scope per phase).
2. Phase objective, dependency assumptions, and expected output per phase.
3. Testing methodology for each phase (unit/integration/e2e/manual checks).
4. Strict constraints for each phase (allowed tools, runtime boundaries, no-go edits, safety constraints).
5. Planned file/script touchpoints for each phase (exact paths, purpose of edits, why phase owns them).
6. Skeletal implementation snippets for non-trivial edits (pseudocode/diff-style outline, not full implementation).
7. Relevant code references or excerpts that justify the planned approach.
8. Phase exit criteria and blocker handling.
9. Risk/rollback notes and handoff instructions for context rollover.

## Execution Contract
- The orchestrator decides completion based on evidence, not agent claims.
- Do not put smallest granular sub-task definitions in this file.
- Granular implementation units and pass criteria belong only in `feature_list.json`.
- Every phase in plan should map to one or more `sub_tasks` in `feature_list.json`.

## Phase Template
### Phase <N> - <name>
- Objective:
- In scope:
- Out of scope:
- Dependencies/assumptions:
- Strict constraints:
- Planned file/script touchpoints:
- Skeletal change snippet(s):
- Relevant code references:
- Validation:
- Exit criteria:
