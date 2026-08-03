$ErrorActionPreference = "Stop"

$sourceDir = $env:AUTOEXP_SOURCE_DIR
$skipRuntime = $env:AUTOEXP_SKIP_RUNTIME -eq "1"
$uninstall = $env:AUTOEXP_UNINSTALL -eq "1" -or $args -contains "--uninstall"
$userHome = [Environment]::GetFolderPath("UserProfile")

function First-Value($value, $fallback) {
    if ([string]::IsNullOrWhiteSpace($value)) { return $fallback }
    return $value
}

function Has-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Remove-Path($path) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

function Copy-Tree($source, $destination) {
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -Path (Join-Path $source "*") -Destination $destination -Recurse -Force
}

function Run-Quiet($command, $arguments) {
    & $command @arguments *> $null
    return $LASTEXITCODE -eq 0
}

if (-not (Has-Command "git")) {
    throw "autoexp installer requires git"
}
if (-not $skipRuntime -and -not (Has-Command "uv")) {
    throw "autoexp installer requires uv"
}

$codexHome = First-Value $env:CODEX_HOME (Join-Path $userHome ".codex")
$claudeHome = First-Value $env:CLAUDE_CONFIG_DIR (Join-Path $userHome ".claude")
$configHome = First-Value $env:XDG_CONFIG_HOME (Join-Path $userHome ".config")
$opencodeHome = Join-Path $configHome "opencode"
$piHome = First-Value $env:PI_CODING_AGENT_DIR (Join-Path $userHome ".pi\agent")
$codexSkills = First-Value $env:AUTOEXP_CODEX_SKILLS_DIR (Join-Path $userHome ".agents\skills")

Remove-Path (Join-Path $codexSkills "autoexp")

if ($uninstall) {
    if (Has-Command "codex") {
        Run-Quiet "codex" @("plugin", "remove", "autoexp@autoexp") | Out-Null
        Run-Quiet "codex" @("plugin", "marketplace", "remove", "autoexp") | Out-Null
    }
    if (Has-Command "claude") {
        Run-Quiet "claude" @("plugin", "uninstall", "autoexp@autoexp") | Out-Null
        Run-Quiet "claude" @("plugin", "marketplace", "remove", "autoexp") | Out-Null
    }
    if (Has-Command "pi") {
        $oldPiHome = $env:PI_CODING_AGENT_DIR
        $env:PI_CODING_AGENT_DIR = $piHome
        Run-Quiet "pi" @("remove", (Join-Path $piHome "autoexp-extension")) | Out-Null
        $env:PI_CODING_AGENT_DIR = $oldPiHome
    }
    @(
        (Join-Path $codexHome "autoexp-marketplace"),
        (Join-Path $codexSkills "autoexp-review"),
        (Join-Path $claudeHome "autoexp-marketplace"),
        (Join-Path $claudeHome "skills\autoexp"),
        (Join-Path $claudeHome "skills\autoexp-review"),
        (Join-Path $opencodeHome "plugins\autoexp"),
        (Join-Path $opencodeHome "plugins\autoexp-native"),
        (Join-Path $piHome "autoexp-extension")
    ) | ForEach-Object { Remove-Path $_ }
    @(
        (Join-Path $opencodeHome "commands\autoexp.md"),
        (Join-Path $opencodeHome "commands\autoexp-review.md"),
        (Join-Path $opencodeHome "plugins\autoexp.ts"),
        (Join-Path $opencodeHome "agents\autoexp.md"),
        (Join-Path $piHome "prompts\autoexp.md"),
        (Join-Path $piHome "prompts\autoexp-review.md")
    ) | ForEach-Object { Remove-Path $_ }
    if (-not $skipRuntime) {
        Run-Quiet "uv" @("tool", "uninstall", "autoexp") | Out-Null
    }
    Write-Output "Uninstalled Autoexp-owned runtime and adapter files; unrelated host configuration was left unchanged."
    exit 0
}

$repo = "https://github.com/shreyashkar-ml/autoexp"
$ref = First-Value $env:AUTOEXP_REF "main"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("autoexp-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    if ([string]::IsNullOrWhiteSpace($sourceDir)) {
        if ($ref -notmatch "^[0-9a-fA-F]{40}$") {
            $refs = & git ls-remote "$repo.git" $ref "refs/heads/$ref" "refs/tags/$ref^{}" "refs/tags/$ref"
            if ($LASTEXITCODE -ne 0) { throw "autoexp installer could not resolve AUTOEXP_REF" }
            $peeled = $refs | Where-Object { $_ -match "\^\{\}$" } | Select-Object -First 1
            $selected = if ($peeled) { $peeled } else { $refs | Select-Object -First 1 }
            if (-not $selected) { throw "autoexp installer could not resolve AUTOEXP_REF" }
            $ref = ($selected -split "\s+")[0]
        } else {
            $ref = $ref.ToLowerInvariant()
        }

        $sourceDir = Join-Path $tempRoot "source"
        $files = @(
            ".agents/plugins/marketplace.json",
            "adapters/codex-skills/autoexp-review/SKILL.md",
            ".claude-plugin/marketplace.json",
            "adapters/claude/.claude-plugin/plugin.json",
            "adapters/claude/hooks/hooks.json",
            "adapters/claude-skills/autoexp/SKILL.md",
            "adapters/claude-skills/autoexp-review/SKILL.md",
            "adapters/codex/.codex-plugin/plugin.json",
            "adapters/codex/hooks/hooks.json",
            "adapters/opencode-plugin/package.json",
            "adapters/opencode-plugin/index.ts",
            "adapters/opencode-plugin/bridge.ts",
            "adapters/opencode-plugin/loader.ts",
            "adapters/opencode-plugin/commands/autoexp.md",
            "adapters/opencode-plugin/commands/autoexp-review.md",
            "adapters/pi-extension/package.json",
            "adapters/pi-extension/index.ts",
            "adapters/pi-extension/bridge.ts"
        )
        foreach ($file in $files) {
            $target = Join-Path $sourceDir $file
            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
            Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/shreyashkar-ml/autoexp/$ref/$file" -OutFile $target
        }
    }

    $reviewSkill = Join-Path $codexSkills "autoexp-review"
    New-Item -ItemType Directory -Force -Path $reviewSkill | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\codex-skills\autoexp-review\SKILL.md") -Destination (Join-Path $reviewSkill "SKILL.md") -Force

    if (-not $skipRuntime) {
        if ($sourceDir -eq (Join-Path $tempRoot "source")) {
            & uv tool install --force "git+$repo.git@$ref"
        } else {
            & uv tool install --force --no-cache $sourceDir
        }
        if ($LASTEXITCODE -ne 0) { throw "Autoexp runtime installation failed" }
    }

    $statuses = [System.Collections.Generic.List[string]]::new()

    if (Has-Command "codex") {
        $marketplaceRoot = Join-Path $codexHome "autoexp-marketplace"
        Remove-Path $marketplaceRoot
        New-Item -ItemType Directory -Force -Path (Join-Path $marketplaceRoot ".agents\plugins") | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceDir ".agents\plugins\marketplace.json") -Destination (Join-Path $marketplaceRoot ".agents\plugins\marketplace.json") -Force
        Copy-Tree (Join-Path $sourceDir "adapters\codex") (Join-Path $marketplaceRoot "adapters\codex")
        Run-Quiet "codex" @("plugin", "remove", "autoexp@autoexp") | Out-Null
        Run-Quiet "codex" @("plugin", "marketplace", "remove", "autoexp") | Out-Null
        Run-Quiet "codex" @("plugin", "marketplace", "add", $marketplaceRoot) | Out-Null
        if (Run-Quiet "codex" @("plugin", "add", "autoexp@autoexp", "--json")) {
            $statuses.Add('Codex: Integrated ($autoexp, $autoexp-review)')
        } else {
            $statuses.Add("Codex: Compatible; run: codex plugin add autoexp@autoexp")
        }
    } else {
        $statuses.Add("Codex: skipped (not installed)")
    }

    if (Has-Command "claude") {
        $claudeMarketplace = Join-Path $claudeHome "autoexp-marketplace"
        Remove-Path $claudeMarketplace
        New-Item -ItemType Directory -Force -Path (Join-Path $claudeMarketplace ".claude-plugin") | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceDir ".claude-plugin\marketplace.json") -Destination (Join-Path $claudeMarketplace ".claude-plugin\marketplace.json") -Force
        $claudeAdapter = Join-Path $claudeMarketplace "adapters\claude"
        New-Item -ItemType Directory -Force -Path (Join-Path $claudeAdapter ".claude-plugin"), (Join-Path $claudeAdapter "hooks") | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\claude\.claude-plugin\plugin.json") -Destination (Join-Path $claudeAdapter ".claude-plugin\plugin.json") -Force
        Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\claude\hooks\hooks.json") -Destination (Join-Path $claudeAdapter "hooks\hooks.json") -Force
        Copy-Tree (Join-Path $sourceDir "adapters\claude-skills\autoexp") (Join-Path $claudeHome "skills\autoexp")
        Copy-Tree (Join-Path $sourceDir "adapters\claude-skills\autoexp-review") (Join-Path $claudeHome "skills\autoexp-review")
        Run-Quiet "claude" @("plugin", "uninstall", "autoexp@autoexp") | Out-Null
        Run-Quiet "claude" @("plugin", "marketplace", "remove", "autoexp") | Out-Null
        Run-Quiet "claude" @("plugin", "marketplace", "add", $claudeMarketplace) | Out-Null
        Run-Quiet "claude" @("plugin", "install", "autoexp@autoexp") | Out-Null
        $statuses.Add("Claude Code: Experimental native adapter (/autoexp, /autoexp-review); reload required")
    } else {
        $statuses.Add("Claude Code: skipped (not installed)")
    }

    if (Has-Command "opencode") {
        $nativeRoot = Join-Path $opencodeHome "plugins\autoexp-native"
        New-Item -ItemType Directory -Force -Path $nativeRoot, (Join-Path $opencodeHome "commands") | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\opencode-plugin\loader.ts") -Destination (Join-Path $opencodeHome "plugins\autoexp.ts") -Force
        Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\opencode-plugin\index.ts") -Destination (Join-Path $nativeRoot "plugin.ts") -Force
        Copy-Item -LiteralPath (Join-Path $sourceDir "adapters\opencode-plugin\bridge.ts") -Destination (Join-Path $nativeRoot "bridge.ts") -Force
        Copy-Item -Path (Join-Path $sourceDir "adapters\opencode-plugin\commands\*.md") -Destination (Join-Path $opencodeHome "commands") -Force
        Remove-Path (Join-Path $opencodeHome "plugins\autoexp")
        Remove-Path (Join-Path $opencodeHome "agents\autoexp.md")
        $statuses.Add("OpenCode: Integrated (/autoexp, /autoexp-review)")
    } else {
        $statuses.Add("OpenCode: skipped (not installed)")
    }

    if (Has-Command "pi") {
        $piExtension = Join-Path $piHome "autoexp-extension"
        Remove-Path $piExtension
        Copy-Tree (Join-Path $sourceDir "adapters\pi-extension") $piExtension
        $oldPiHome = $env:PI_CODING_AGENT_DIR
        $env:PI_CODING_AGENT_DIR = $piHome
        if (Run-Quiet "pi" @("install", $piExtension)) {
            Remove-Path (Join-Path $piHome "prompts\autoexp.md")
            Remove-Path (Join-Path $piHome "prompts\autoexp-review.md")
            $statuses.Add("Pi: Integrated (/autoexp, /autoexp-review)")
        } else {
            $statuses.Add("Pi: Compatible; native extension install failed, existing prompts were preserved")
        }
        $env:PI_CODING_AGENT_DIR = $oldPiHome
    } else {
        $statuses.Add("Pi: skipped (not installed)")
    }

    Write-Output "Installed Autoexp runtime and detected host adapters."
    $statuses | ForEach-Object { Write-Output $_ }
} finally {
    Remove-Path $tempRoot
}
