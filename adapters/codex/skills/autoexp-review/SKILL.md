---
name: autoexp-review
description: Open the native Autoexp browser review for the active experiment.
---

# Autoexp review

This skill is user-triggered only.

If the current prompt includes `[AUTOEXP PROTOCOL v1]` context for this Codex
session, use that result and do not launch another review.

If the sentinel is absent, the native hook is disabled or unavailable. Use the
compatible fallback once:

```bash
autoexp agent review start --agent codex --session-id '<current Codex session ID>' --repo "$PWD" --json
autoexp agent review wait '<operation-id>' --timeout 900 --json
```

Treat submitted notes as the user's next instruction. Approval and dismissal are
terminal for this invocation. Never launch a second review.
