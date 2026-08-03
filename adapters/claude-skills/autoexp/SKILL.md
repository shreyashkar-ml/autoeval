---
name: autoexp
description: Start or continue a reproducible Autoexp experiment.
argument-hint: "[objective]"
allowed-tools: Bash(autoexp *)
disable-model-invocation: true
---

## Native Autoexp context

!`autoexp agent context --agent claude --session-id "${CLAUDE_SESSION_ID}" --repo "${CLAUDE_PROJECT_DIR}" --format prompt`

## Task

Objective supplied by the user: $ARGUMENTS

Follow the returned Autoexp workflow completely. After creating or selecting an
experiment, bind it to this host session. Keep immutable evidence and report the
run IDs that support the conclusion.
