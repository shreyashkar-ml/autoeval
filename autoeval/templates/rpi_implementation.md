# Workflow Orchestration

### 1. Plan Mode Default
- Always refer to `.autoeval/instructions/research.md` to understand the primary context and purpose behind repository and major components.
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions) as defined in phases of `.autoeval/instructions/plan.md`
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps as defined in `.autoeval/instructions/feature_list.json` as well when required
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent strategy
- Use subagents liberally to keep main context window clean
- Offload task-specific research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `.autoeval/instructions/review.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Review lessons from `.autoeval/instructions/review.md` "Lessons" section at the start of each session

### 4. Verification Before Done
- Never mark a task/sub-task complete without proving it works and passing all success criteria for task as defined in `.autoeval/instructions/feature_list.json`
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI test without being told how

### Task Management
1. **Research First**: If an overall research about repository is not present in `.autoeval/instructions/research.md`, create the research as per the instructions defined.
2. **Plan First**: Write plan to `.autoeval/instructions/plan.md` with clear phases defined for the task and checkable items for each.
3. **Track Progress**: Mark items complete as you go, keep updating status for phases and sub-tasks in `.autoeval/instructions/plan.md` and `.autoeval/instructions/feature_list.json` respectively.
4. **Explain changes**: High-level summary at each step
5. **Capture Lessons**: Update `.autoeval/instructions/review.md` "Lessons" section with the patterns learnt
6. **Document Results**: Add review section to `.autoeval/instructions/review.md` in the "Review" section
