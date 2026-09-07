#!/bin/bash
# Point Antigravity at the same skills Claude Code uses.
#
# Antigravity reads workspace skills from <repo>/.agents/skills; Claude Code
# reads them from <repo>/.claude/skills. Both expect the same SKILL.md format,
# so one symlink keeps a single source of truth instead of two copies that
# drift.
#
# A symlink to a gitignored path is not tracked, so re-run this after a fresh
# clone. The Windows equivalent is scripts/link-antigravity-skills.ps1.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO/.claude/skills"
LINK="$REPO/.agents/skills"

if [ ! -d "$SOURCE" ]; then
    echo "Source '$SOURCE' does not exist." >&2
    exit 1
fi

if [ -L "$LINK" ]; then
    echo "Already linked: $LINK -> $(readlink "$LINK")"
    exit 0
fi

if [ -e "$LINK" ]; then
    echo "'$LINK' already exists and is not a symlink. Remove it first." >&2
    exit 1
fi

mkdir -p "$(dirname "$LINK")"
ln -s "$SOURCE" "$LINK"
echo "Linked: $LINK -> $SOURCE"
