<!-- template_id: rpi_plan -->
<!-- template_version: 2.2.0 -->

# Planning Artifact Instruction

Purpose:
- Break down the task described in user query into phase-level execution strategy.
- Use phases separated by core logic/component boundaries.
- Divide the plan into sections with each section defined as a separate phase for task execution.
- Break down into phases based on relatively independent functionality changes requested for each major logic/module.

## Section/Phase template
- phase_id: {phase_number or unique identifier for phase}
- planned changes: {plan_description}
- Suggested changes: {skeletal structure for the edits suggested}
- Validation criteria: {instructions to validate the functionality changes suggested}
- status: [] pending/completed

## Guidelines for planning
1. Phase breakdown with explicit boundaries (what is in scope/out of scope per phase).
2. Phase objective, dependency assumptions, and expected output per phase.
3. Testing methodology for each phase (unit/integration/e2e/manual checks).
4. Strict constraints for each phase (allowed tools, runtime boundaries, no-go edits, safety constraints).
5. Skeletal implementation snippets for non-trivial edits (pseudocode/diff-style outline, not full implementation).
6. Relevant code references or excerpts that justify the planned approach.