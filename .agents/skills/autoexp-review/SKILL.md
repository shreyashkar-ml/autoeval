---
name: autoexp-review
description: Open the native Autoexp browser review for the active experiment.
---

# Autoexp review

This skill is user-triggered only.

If the current prompt includes `[AUTOEXP PROTOCOL v1]` context for this Codex
session, use that result and do not launch another review.

If the sentinel is absent, the native hook is disabled or unavailable. Run
`autoexp review` once, wait for it to return, and treat submitted notes as the
user's next instruction. Never launch a second review for this invocation.
