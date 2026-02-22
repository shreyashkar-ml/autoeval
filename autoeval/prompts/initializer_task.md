Initialize the target repository execution context in `{project_dir}` for task: `{task}`.

Delegation order:
1. `coding`: run verification gate and baseline checks.
2. `github`: record initial setup commit/operation metadata.
3. `slack`: send initialization notification.
