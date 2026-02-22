#!/usr/bin/env bash
set -euo pipefail

REPO_PATH="${1:-.}"
TASK_TEXT="${2:-demo multi-phase task}"

uv run autoeval init --repo "${REPO_PATH}" --provider codex --task "${TASK_TEXT}"
uv run autoeval run --repo "${REPO_PATH}" --task "${TASK_TEXT}"
uv run autoeval status --repo "${REPO_PATH}"
uv run autoeval eval --repo "${REPO_PATH}" --profile default
uv run autoeval mcp add --scope user --name puppeteer --transport stdio --command "echo puppeteer" --tool-namespace puppeteer --repo "${REPO_PATH}"
uv run autoeval mcp connect --repo "${REPO_PATH}" --name puppeteer
uv run autoeval test browser --repo "${REPO_PATH}" --mcp puppeteer --scenario "open home"
uv run autoeval review --repo "${REPO_PATH}" --severity medium
