# Point Antigravity at the same skills Claude Code uses.
#
# Antigravity reads workspace skills from <repo>/.agents/skills; Claude Code
# reads them from <repo>/.claude/skills. Both expect the same SKILL.md format,
# so one directory junction keeps a single source of truth instead of two copies
# that drift.
#
# A junction is not tracked by git, so re-run this after a fresh clone.
# Usage: pwsh -File scripts/link-antigravity-skills.ps1

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo '.claude\skills'
$link = Join-Path $repo '.agents\skills'

if (-not (Test-Path $source)) {
    throw "Source '$source' does not exist. Run this from a checkout that has the skills."
}

$existing = Get-Item $link -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.LinkType -eq 'Junction' -and $existing.Target -eq $source) {
        Write-Host "Already linked: $link -> $source"
        exit 0
    }
    throw "'$link' already exists and is not a junction to '$source'. Remove it first."
}

New-Item -ItemType Directory -Force (Split-Path -Parent $link) | Out-Null
cmd /c mklink /J "$link" "$source"
Write-Host "Linked: $link -> $source"
