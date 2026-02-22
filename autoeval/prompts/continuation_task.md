Continue execution in the target project directory (`{project_dir}`) for task: `{task}`.

Delegation order:
1. `coding`: verification gate, then scoped implementation.
2. `github`: record commit/PR metadata for completed sub-task.
3. `slack`: send completion status update.

If verification fails, fix regressions before new work.
