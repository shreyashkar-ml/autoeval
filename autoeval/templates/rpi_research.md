<!-- template_id: rpi_research -->
<!-- template_version: 2.2.0 -->

# Research Artifact Instruction

Purpose:
- Build repository familiarity context for a target repository when `autoeval` is initialized there for the first time.
- This artifact is repository-level and not task-specific.
- It should remain reusable across future tasks in the same target repository.

## Scope Rules
1. Cover the whole repository architecture and behavior baseline, not just a single request.
2. Keep this artifact factual and descriptive; do not include phase execution status.
3. After implementation runs, update this file surgically so it reflects current functionality.
4. Preserve historical context; do not rewrite the entire document each run unless structure is obsolete.
5. Build structure sections from direct repository inspection by the worker agent; do not rely on pre-generated tree snapshots.
6. While preparing structure highlights, follow the repository `.gitignore` rules; include ignored paths only when they are directly relevant to the request.

## Required Sections
1. Repository tree/map with one-line descriptions for important nodes and modules.
2. Project directory and script structures with a one-line purpose/functionality note for each highlighted entry.
3. Core functionality and module responsibilities.
4. End-to-end flow traces for key user/system paths.
5. Integration methodology and external dependencies (APIs, services, data stores, queues).
6. Deployment/runtime/testing setup (entry points, commands, tooling assumptions).
7. Known gaps, risks, and unknowns with evidence needed to resolve them.

## Update Rules
- Keep links/file references actionable and current.
- If behavior changes, update only affected sections with concrete diffs in understanding.
- Do not add per-phase checklists or granular sub-task completion states here.
