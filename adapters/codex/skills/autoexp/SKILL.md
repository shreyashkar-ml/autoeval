---
name: autoexp
description: Start and run a reproducible Autoexp experiment in the current repository.
---

# Autoexp

Treat explicit invocation arguments as the objective. Read the session ID and
repository from the `[AUTOEXP SESSION v1]` context injected when this Codex
session started. Then run:

```bash
autoexp agent context --agent codex --session-id '<session from context>' --repo '<repository from context>' --objective '<objective>' --json
```

Follow the returned workflow and use its exact `exec_argv_prefix` for every
Autoexp command. Creating an experiment attaches it to the session
automatically. Keep immutable evidence and cite the run IDs supporting the
conclusion.
