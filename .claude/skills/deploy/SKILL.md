---
name: deploy
description: >-
  Use this skill when the user asks to cut a release, deploy, or ship a new
  version ("deploy", "release", "cut v1.4", "bump and release"). It pulls main,
  bumps version.txt (minor by default, major or patch on request), writes release
  notes covering every commit since the last version, tags, and hands off to
  GitHub Actions, which tests on Windows and macOS, builds signed binaries, and
  publishes a PRERELEASE for a human to promote.
---

# /deploy — cut a release

The local half of this skill is deliberately thin: it bumps the version, writes
notes, and pushes a tag. The tag is what triggers
[release.yml](../../../.github/workflows/release.yml), which does all the
testing, building, signing and publishing.

**You never publish the final release.** CI creates a *prerelease*. A human
verifies it and promotes it to latest. `updater.py` queries
`/releases/latest`, which GitHub excludes prereleases from, so users are not
offered the build until that promotion happens.

## Step 1 — Get onto a clean, current `main`

```bash
git checkout main
git pull --ff-only origin main
git status --porcelain
```

Abort and report if the tree is dirty, if the pull is not a fast-forward, or if
`main` has diverged. Do not merge or rebase to force it through.

## Step 2 — Bump the version

Default is a **minor** bump. Use `major` or `patch` only if the user asked for
one in this session.

```bash
python .claude/skills/deploy/scripts/bump_version.py            # 1.3.10 -> 1.4.0
python .claude/skills/deploy/scripts/bump_version.py major      # 1.3.10 -> 2.0.0
python .claude/skills/deploy/scripts/bump_version.py patch      # 1.3.10 -> 1.3.11
```

The script prints the new version; capture it as `<VERSION>`.

## Step 3 — Write the release notes

```bash
python .claude/skills/deploy/scripts/gen_release_notes.py <VERSION>
```

This creates `docs/release_notes/release_notes_v<VERSION>.md` containing every
non-merge commit since the previous tag — the release covers all work since the
last version, across all merged branches, not just one branch.

**Now do the part the script cannot**: replace the two `TODO` placeholders with
a real summary paragraph and grouped user-facing bullets. Read the commits and
any referenced issue numbers. Match the voice of the previous release
(`gh release view v1.3.10`). Leave the commit list intact.

These notes are tracked in git — CI reads this exact file to build the GitHub
release body, so it must be committed with the tag.

## Step 4 — Commit and tag

```bash
git add version.txt docs/release_notes/release_notes_v<VERSION>.md
git commit -m "chore(release): v<VERSION>"
git push origin main
git tag v<VERSION>
git push origin v<VERSION>
```

Push the branch before the tag, so the tagged commit already exists on the
remote.

## Step 5 — Watch CI and hand off

The tag push starts the release workflow:

1. **test** — full suite on `windows-latest` and `macos-latest`. Everything else
   is gated on this; a failure means no release is created.
2. **build-windows** — `release-win.ps1` produces the portable ZIP and the Inno
   Setup installer (unsigned, as today).
3. **build-macos** — a `macos-13` (Intel) + `macos-14` (Apple Silicon) matrix.
   Each leg codesigns with the Developer ID cert and notarizes via `notarytool`,
   producing arch-tagged DMG and ZIP assets.
4. **release** — creates `v<VERSION>` as a **prerelease** with the notes file as
   the body and all six assets attached.

Watch it and report the outcome:

```bash
gh run watch
gh run view --log-failed   # if it fails
```

Then give the user the prerelease URL and tell them explicitly that it is a
prerelease: they should download and verify a build, then uncheck "This is a
pre-release" on the GitHub release page to make it the latest and offer it to
existing users via the in-app updater.

## If CI fails

Do not build or upload anything locally to work around it. Report the failing
job and its log. If the tag needs to be redone after a fix, delete it on both
sides (`git tag -d v<VERSION>` and `git push origin :refs/tags/v<VERSION>`) and
re-run this skill from step 4 — the version bump and notes commit can stay.

## Prerequisites

The macOS jobs need repository secrets configured. See
[docs/release-pipeline.md](../../../docs/release-pipeline.md) for the list. If
they are missing, the mac legs fail at the signing step.
