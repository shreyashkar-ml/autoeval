#!/usr/bin/env bash
set -euo pipefail

source_dir="${AUTOEXP_SOURCE_DIR:-}"
skip_runtime="${AUTOEXP_SKIP_RUNTIME:-0}"
commands=(awk install)
[[ -z "$source_dir" ]] && commands+=(curl git)
[[ "$skip_runtime" != 1 ]] && commands+=(uv)
for command in "${commands[@]}"; do
  command -v "$command" >/dev/null || {
    echo "autoexp installer requires $command" >&2
    exit 1
  }
done

repo="https://github.com/shreyashkar-ml/autoexp"
ref="${AUTOEXP_REF:-main}"
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
fi
raw="https://raw.githubusercontent.com/shreyashkar-ml/autoexp/${ref}"
tmp="$(mktemp -d)"
trap "rm -rf \"$tmp\"" EXIT

for skill in autoexp autoexp-review; do
  mkdir -p "$tmp/$skill/agents"
  if [[ -n "$source_dir" ]]; then
    install -m 0644 "$source_dir/plugins/autoexp/skills/$skill/SKILL.md" "$tmp/$skill/SKILL.md"
    install -m 0644 "$source_dir/plugins/autoexp/skills/$skill/agents/openai.yaml" "$tmp/$skill/agents/openai.yaml"
  else
    curl -fsSL "$raw/plugins/autoexp/skills/$skill/SKILL.md" -o "$tmp/$skill/SKILL.md"
    curl -fsSL "$raw/plugins/autoexp/skills/$skill/agents/openai.yaml" -o "$tmp/$skill/agents/openai.yaml"
  fi
done

mkdir -p "$tmp/opencode/commands" "$tmp/opencode/agents" "$tmp/pi"
for command in autoexp autoexp-review; do
  if [[ -n "$source_dir" ]]; then
    install -m 0644 "$source_dir/adapters/opencode/commands/$command.md" "$tmp/opencode/commands/$command.md"
    install -m 0644 "$source_dir/adapters/pi/prompts/$command.md" "$tmp/pi/$command.md"
  else
    curl -fsSL "$raw/adapters/opencode/commands/$command.md" -o "$tmp/opencode/commands/$command.md"
    curl -fsSL "$raw/adapters/pi/prompts/$command.md" -o "$tmp/pi/$command.md"
  fi
done
if [[ -n "$source_dir" ]]; then
  install -m 0644 "$source_dir/adapters/opencode/agents/autoexp.md" "$tmp/opencode/agents/autoexp.md"
else
  curl -fsSL "$raw/adapters/opencode/agents/autoexp.md" -o "$tmp/opencode/agents/autoexp.md"
fi

if [[ "$skip_runtime" != 1 ]]; then
  if [[ -n "$source_dir" ]]; then
    uv tool install --force "$source_dir"
  else
    uv tool install --force "git+${repo}.git@${ref}"
  fi
fi

codex_skills="${AUTOEXP_CODEX_SKILLS_DIR:-$HOME/.agents/skills}"
claude_skills="${AUTOEXP_CLAUDE_SKILLS_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills}"
for root in "$codex_skills" "$claude_skills"; do
  for skill in autoexp autoexp-review; do
    mkdir -p "$root/$skill/agents"
    install -m 0644 "$tmp/$skill/SKILL.md" "$root/$skill/SKILL.md"
    install -m 0644 "$tmp/$skill/agents/openai.yaml" "$root/$skill/agents/openai.yaml"
  done
done

# Claude should never open the blocking review unless the user invokes it.
awk "1; /^description:/ { print \"disable-model-invocation: true\" }" \
  "$tmp/autoexp-review/SKILL.md" > "$claude_skills/autoexp-review/SKILL.md"
chmod 0644 "$claude_skills/autoexp-review/SKILL.md"

opencode_commands="${AUTOEXP_OPENCODE_COMMANDS_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/commands}"
opencode_agents="${AUTOEXP_OPENCODE_AGENTS_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/agents}"
pi_prompts="${AUTOEXP_PI_PROMPTS_DIR:-${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/prompts}"
mkdir -p "$opencode_commands" "$opencode_agents" "$pi_prompts"
for command in autoexp autoexp-review; do
  install -m 0644 "$tmp/opencode/commands/$command.md" "$opencode_commands/$command.md"
  install -m 0644 "$tmp/pi/$command.md" "$pi_prompts/$command.md"
done
install -m 0644 "$tmp/opencode/agents/autoexp.md" "$opencode_agents/autoexp.md"

printf "%s\n" \
  "Installed Autoexp and its agent commands." \
  "Codex: \$autoexp, \$autoexp-review" \
  "Claude Code: /autoexp, /autoexp-review" \
  "OpenCode: /autoexp, /autoexp-review" \
  "Pi: /autoexp, /autoexp-review" \
  "Restart your agent to load the skills."
