#!/usr/bin/env bash
set -euo pipefail

source_dir="${AUTOEXP_SOURCE_DIR:-}"
skip_runtime="${AUTOEXP_SKIP_RUNTIME:-0}"
uninstall="${AUTOEXP_UNINSTALL:-0}"
[[ "${1:-}" == "--uninstall" ]] && uninstall=1

command -v install >/dev/null || { echo "autoexp installer requires install" >&2; exit 1; }
if [[ -z "$source_dir" ]]; then
  command -v curl >/dev/null || { echo "autoexp installer requires curl" >&2; exit 1; }
  command -v git >/dev/null || { echo "autoexp installer requires git" >&2; exit 1; }
fi
[[ "$skip_runtime" == 1 ]] || command -v uv >/dev/null || {
  echo "autoexp installer requires uv" >&2
  exit 1
}

codex_home="${CODEX_HOME:-$HOME/.codex}"
claude_home="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
opencode_home="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
pi_home="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
legacy_skills="${AUTOEXP_CODEX_SKILLS_DIR:-$HOME/.agents/skills}"

# Remove pre-0.4 shared-skill installs; native adapters own command discovery now.
rm -rf "$legacy_skills/autoexp" "$legacy_skills/autoexp-review"

if [[ "$uninstall" == 1 ]]; then
  command -v codex >/dev/null && codex plugin remove autoexp@autoexp >/dev/null 2>&1 || true
  command -v codex >/dev/null && codex plugin marketplace remove autoexp >/dev/null 2>&1 || true
  command -v claude >/dev/null && claude plugin uninstall autoexp@autoexp >/dev/null 2>&1 || true
  command -v claude >/dev/null && claude plugin marketplace remove autoexp >/dev/null 2>&1 || true
  command -v pi >/dev/null && PI_CODING_AGENT_DIR="$pi_home" pi remove "$pi_home/autoexp-extension" >/dev/null 2>&1 || true
  rm -rf \
    "$codex_home/autoexp-marketplace" \
    "$claude_home/autoexp-marketplace" \
    "$claude_home/skills/autoexp" \
    "$claude_home/skills/autoexp-review" \
    "$opencode_home/plugins/autoexp" \
    "$opencode_home/plugins/autoexp-native" \
    "$pi_home/autoexp-extension"
  rm -f \
    "$opencode_home/commands/autoexp.md" \
    "$opencode_home/commands/autoexp-review.md" \
    "$opencode_home/plugins/autoexp.ts" \
    "$opencode_home/agents/autoexp.md" \
    "$pi_home/prompts/autoexp.md" \
    "$pi_home/prompts/autoexp-review.md"
  [[ "$skip_runtime" == 1 ]] || uv tool uninstall autoexp >/dev/null 2>&1 || true
  echo "Uninstalled Autoexp-owned runtime and adapter files; unrelated host configuration was left unchanged."
  exit 0
fi

repo="https://github.com/shreyashkar-ml/autoexp"
ref="${AUTOEXP_REF:-main}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ -z "$source_dir" ]]; then
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    ref="${ref,,}"
  else
    ref="$(
      git ls-remote "${repo}.git" "$ref" "refs/heads/$ref" "refs/tags/$ref^{}" "refs/tags/$ref" |
        awk '$2 ~ /\^\{\}$/ { print $1; found=1; exit } !found && !commit { commit=$1 } END { if (!found) print commit }'
    )"
    [[ -n "$ref" ]] || {
      echo "autoexp installer could not resolve AUTOEXP_REF" >&2
      exit 1
    }
  fi
  raw="https://raw.githubusercontent.com/shreyashkar-ml/autoexp/$ref"
  source_dir="$tmp/source"
  files=(
    .agents/plugins/marketplace.json
    .claude-plugin/marketplace.json
    adapters/claude/.claude-plugin/plugin.json
    adapters/claude/hooks/hooks.json
    adapters/claude/skills/autoexp/SKILL.md
    adapters/claude/skills/autoexp-review/SKILL.md
    adapters/codex/.codex-plugin/plugin.json
    adapters/codex/hooks/hooks.json
    adapters/codex/skills/autoexp/SKILL.md
    adapters/codex/skills/autoexp/agents/openai.yaml
    adapters/codex/skills/autoexp-review/SKILL.md
    adapters/codex/skills/autoexp-review/agents/openai.yaml
    adapters/opencode-plugin/package.json
    adapters/opencode-plugin/index.ts
    adapters/opencode-plugin/bridge.ts
    adapters/opencode-plugin/loader.ts
    adapters/opencode-plugin/commands/autoexp.md
    adapters/opencode-plugin/commands/autoexp-review.md
    adapters/pi-extension/package.json
    adapters/pi-extension/index.ts
    adapters/pi-extension/bridge.ts
  )
  for file in "${files[@]}"; do
    mkdir -p "$source_dir/$(dirname "$file")"
    curl -fsSL "$raw/$file" -o "$source_dir/$file"
  done
fi

if [[ "$skip_runtime" != 1 ]]; then
  if [[ "$source_dir" == "$tmp/source" ]]; then
    uv tool install --force "git+${repo}.git@${ref}"
  else
    uv tool install --force --no-cache "$source_dir"
  fi
fi

statuses=()

if command -v codex >/dev/null; then
  marketplace_root="$codex_home/autoexp-marketplace"
  mkdir -p "$marketplace_root/.agents/plugins" "$marketplace_root/adapters/codex"
  install -m 0644 "$source_dir/.agents/plugins/marketplace.json" \
    "$marketplace_root/.agents/plugins/marketplace.json"
  cp -R "$source_dir/adapters/codex/." "$marketplace_root/adapters/codex/"
  installed_marketplace="$(
    codex plugin marketplace list 2>/dev/null |
      sed -n 's/^autoexp[[:space:]]*//p' |
      head -n 1
  )"
  if [[ -n "$installed_marketplace" && "$installed_marketplace" != "$marketplace_root" ]]; then
    codex plugin remove autoexp@autoexp >/dev/null 2>&1 || true
    codex plugin marketplace remove autoexp >/dev/null
    installed_marketplace=""
  fi
  if [[ -z "$installed_marketplace" ]]; then
    codex plugin marketplace add "$marketplace_root" >/dev/null
  fi
  codex plugin remove autoexp@autoexp >/dev/null 2>&1 || true
  if codex plugin add autoexp@autoexp --json >/dev/null 2>&1; then
    statuses+=("Codex: Integrated (\$autoexp, \$autoexp-review)")
  else
    statuses+=("Codex: Compatible; run: codex plugin add autoexp@autoexp")
  fi
else
  statuses+=("Codex: skipped (not installed)")
fi

if command -v claude >/dev/null; then
  claude_marketplace="$claude_home/autoexp-marketplace"
  mkdir -p "$claude_marketplace/.claude-plugin" "$claude_marketplace/adapters/claude"
  install -m 0644 "$source_dir/.claude-plugin/marketplace.json" \
    "$claude_marketplace/.claude-plugin/marketplace.json"
  cp -R "$source_dir/adapters/claude/." "$claude_marketplace/adapters/claude/"
  mkdir -p "$claude_home/skills/autoexp" "$claude_home/skills/autoexp-review"
  install -m 0644 "$source_dir/adapters/claude/skills/autoexp/SKILL.md" \
    "$claude_home/skills/autoexp/SKILL.md"
  install -m 0644 "$source_dir/adapters/claude/skills/autoexp-review/SKILL.md" \
    "$claude_home/skills/autoexp-review/SKILL.md"
  claude plugin marketplace add "$claude_marketplace" >/dev/null 2>&1 || true
  claude plugin install autoexp@autoexp >/dev/null 2>&1 || true
  statuses+=("Claude Code: Experimental native adapter (/autoexp, /autoexp-review); reload required")
else
  statuses+=("Claude Code: skipped (not installed)")
fi

if command -v opencode >/dev/null; then
  mkdir -p "$opencode_home/plugins/autoexp-native" "$opencode_home/commands"
  install -m 0644 "$source_dir/adapters/opencode-plugin/loader.ts" \
    "$opencode_home/plugins/autoexp.ts"
  install -m 0644 "$source_dir/adapters/opencode-plugin/index.ts" \
    "$opencode_home/plugins/autoexp-native/plugin.ts"
  install -m 0644 "$source_dir/adapters/opencode-plugin/bridge.ts" \
    "$opencode_home/plugins/autoexp-native/bridge.ts"
  install -m 0644 "$source_dir/adapters/opencode-plugin/commands/"*.md \
    "$opencode_home/commands/"
  rm -rf "$opencode_home/plugins/autoexp"
  rm -f "$opencode_home/agents/autoexp.md"
  statuses+=("OpenCode: Integrated (/autoexp, /autoexp-review)")
else
  statuses+=("OpenCode: skipped (not installed)")
fi

if command -v pi >/dev/null; then
  pi_extension="$pi_home/autoexp-extension"
  mkdir -p "$pi_extension"
  cp -R "$source_dir/adapters/pi-extension/." "$pi_extension/"
  if PI_CODING_AGENT_DIR="$pi_home" pi install "$pi_extension" >/dev/null &&
     PI_CODING_AGENT_DIR="$pi_home" pi list 2>/dev/null | grep -Fq autoexp; then
    PI_CODING_AGENT_DIR="$pi_home" \
      pi remove "$source_dir/adapters/pi-extension" >/dev/null 2>&1 || true
    rm -f "$pi_home/prompts/autoexp.md" "$pi_home/prompts/autoexp-review.md"
    statuses+=("Pi: Integrated (/autoexp, /autoexp-review)")
  else
    statuses+=("Pi: Compatible; native extension install failed, existing prompts were preserved")
  fi
else
  statuses+=("Pi: skipped (not installed)")
fi

printf '%s\n' "Installed Autoexp runtime and detected host adapters." "${statuses[@]}"
