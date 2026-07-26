---
name: autoexp-review
description: Open Autoexp review for the active experiment and continue from submitted feedback.
allowed-tools: Bash(autoexp agent review *)
disable-model-invocation: true
---

## Autoexp review result

!`autoexp agent review claude --session-id "${CLAUDE_SESSION_ID}" --repo "${CLAUDE_PROJECT_DIR}"`

## Continue

If the result contains submitted notes, treat them as the user's next instruction
in this conversation and active experiment. If it says the review was dismissed,
acknowledge it once. Never launch a second review for this invocation.
