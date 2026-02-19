# autoeval

`autoeval` is a terminal-first harness for autonomous coding workflows.

## Methodology

### Context Artifacts

1. **Research** documentation:
- Build a repository baseline and operating context before execution. 
- This is pure codebase context and understanding reference with no informations about any planning or execution task. 
- Initialized only at the beginning, it's only updated after completion of each phase to accurately reflect current status of the codebase.

2. **Planning** documentation:
- Convert the user request into phases and testable sub-tasks.
- The query is broken down into phases and smaller sub-tasks with accurate description of expectations and planning for each.
- The planning documentation includes information about scripts to change upon, skeletal structure (or pseudocode) for required changes.

3. **`feature_list`**
- Large (200+ in case of complex queries) suite of test-cases/feature_list for worker agent to pass against to mark each sub-task as complete.
- Immutable list of sub-task description and pass criterions (to avoid worker agent bypassing the failing test cases).
- Worker agent updates "status" from `false` to `true` once all defined test cases pass.

### Execution:
- Execute phase-by-phase with resumable sessions.
- Update sub-task status only when checks pass.
- Trigger intervention when execution is blocked.
- Generate a structured review at the end.

This gives predictable, auditable autonomous runs instead of one-shot opaque agent behavior.

## Capabilities

- Codex-first provider execution (`init`, `run`, `resume`, `status`)
- Human-in-the-loop controls (`intervene`)
- Structured review output (`review`)
- MCP lifecycle management (`mcp list/add/remove/enable/disable/connect/disconnect/set-auth`)
- Browser validation through MCP (`test browser`)

### Pending — Support for `claude-code`, `opencode`, `cursor-cli`, etc.

## Prerequisites

1. Python 3.10+
2. `uv`
3. Codex provider credentials configured in your environment

## Install

```bash
uv venv
uv sync --extra dev
uv run autoeval --help
```

## Auth Setup (Codex + MCP)

```bash
# Codex/provider auth (set according to your runtime requirements)
export OPENAI_API_KEY="your_api_key_here"

# Optional: override default user scope location
export AUTOEVAL_HOME="$HOME/.config/autoeval"
```

If an MCP profile requires auth, bind an auth reference:

```bash
uv run autoeval mcp set-auth \
  --name puppeteer \
  --auth-ref "vault://team/prod/puppeteer-token" \
  --repo .
```

## Example End-to-End Execution (Codex)

Run this from the repository you want `autoeval` to operate on:

```bash
# 1) Initialize harness state for the repo
uv run autoeval init \
  --repo . \
  --provider codex \
  --task "Implement API pagination and tests"

# 2) Execute autonomous run
uv run autoeval run \
  --repo . \
  --provider codex \
  --task "Implement API pagination and tests"

# 3) Check status
uv run autoeval status --repo .

# 4) Resume if interrupted
uv run autoeval resume \
  --repo . \
  --provider codex \
  --task "Continue API pagination implementation"

# 5) Request intervention when blocked
uv run autoeval intervene \
  --repo . \
  --reason "Need product decision for pagination token semantics"

# 6) Emit review report
uv run autoeval review --repo . --severity medium
```

## MCP + Browser Validation Example

```bash
# 1) Add MCP profile
uv run autoeval mcp add \
  --scope user \
  --name puppeteer \
  --transport stdio \
  --command "echo puppeteer" \
  --tool-namespace puppeteer \
  --repo .

# 2) Enable/verify profile
uv run autoeval mcp enable --scope user --name puppeteer --repo .
uv run autoeval mcp list --scope effective --repo .

# 3) Connect profile (preflight)
uv run autoeval mcp connect --repo . --name puppeteer

# 4) Run browser scenario
uv run autoeval test browser \
  --repo . \
  --mcp puppeteer \
  --scenario "open homepage and verify header"

# 5) Optional cleanup
uv run autoeval mcp disconnect --repo . --name puppeteer
```

## License

Apache License 2.0. See `LICENSE`.
