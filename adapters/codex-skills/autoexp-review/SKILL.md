---
name: autoexp-review
description: Open the native Autoexp browser review for the active experiment.
---

# Autoexp review

This skill is user-triggered only.

The native Codex `UserPromptSubmit` hook handles this command before the model
runs. Use the injected `[AUTOEXP PROTOCOL v1]` result and never launch another
review.

If that protocol result is absent, report that the native Autoexp hook is
unavailable. Do not run a shell fallback.
