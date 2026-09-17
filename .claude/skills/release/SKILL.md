---
name: release
description: >-
  Cut an Award Tracker release in one turn. /release rc tags the next release
  candidate on origin/main and Actions publishes it as a prerelease; /release
  promote tags the verified RC commit with the final version so it becomes
  /releases/latest. The tag is the version and its message is the release notes.
---

# /release — tag an RC or promote it

Run this skill only when a person explicitly asks to release. It never builds
or uploads files locally: the tag starts `.github/workflows/release.yml`, which
tests, builds, signs, notarizes, and publishes every artifact.

The version is a Git tag, not a release commit. Release notes are the annotated
tag message. Do not edit `version.txt`, create a release-notes commit, or upload
assets by hand.

## 1. Plan

`rc` is the default and starts the next minor series. It continues an open RC
series automatically. Use `patch` or `major` only when requested.

```bash
python scripts/release_tag.py plan rc
python scripts/release_tag.py plan rc --bump patch
python scripts/release_tag.py plan promote
python scripts/release_tag.py plan 1.5.0-rc.1
```

The plan prints the version, commit, previous final tag, and whether GitHub will
publish a prerelease or latest release.

- An RC tags the current `origin/main` tip.
- Promotion tags the highest open RC's own commit. This is deliberate: the
  source a person verified is the source that becomes latest, even if `main`
  has moved since the RC.

Stop on any refusal rather than choosing a different version or commit.

## 2. Write the notes

For an RC, review every non-merge commit since the `since` tag printed by the
plan:

```bash
git log --no-merges --format='%h %s' <since>..<commit>
```

For promotion, start with the newest RC's tag body and fold in anything added
by later RCs:

```bash
git tag -l --format='%(contents:body)' v<rc-version>
```

Write user-facing Markdown to `.build-cache/notes-v<version>.md`. Use sections
such as `## What's new`, `## Upgrade notes`, and `## Known problems` when they
are useful. Do not add a top-level `#` heading; GitHub supplies the release
title. Show these notes to the user before cutting the tag.

## 3. Cut

Dry-run first. For promotion, pass the exact commit printed by `plan promote`.

```bash
python scripts/release_tag.py cut <version> --notes .build-cache/notes-v<version>.md --dry-run
python scripts/release_tag.py cut <version> --notes .build-cache/notes-v<version>.md

# Promotion only:
python scripts/release_tag.py cut <version> --commit <rc-commit> --notes .build-cache/notes-v<version>.md --dry-run
python scripts/release_tag.py cut <version> --commit <rc-commit> --notes .build-cache/notes-v<version>.md
```

The command refuses unless:

- the main checkout has no tracked changes or commits missing from
  `origin/main`, and this checkout is not behind it;
- the chosen commit is on `origin/main`;
- the tag is new locally and remotely;
- the version moves forward; and
- the latest push-triggered CI run for the commit succeeded.

It creates one annotated tag and pushes only that tag. It never commits.

## 4. Report

```bash
gh run list --workflow release.yml --limit 1
```

Report the version, tagged commit, whether it is a **prerelease** or **latest**,
and `https://github.com/shyoo/awardtracker/releases/tag/v<version>`.

For an RC, install and verify the appropriate Windows, Intel macOS, or Apple
Silicon macOS asset, then run `/release promote`. For a final release, existing
installations will see it on their next update check because GitHub's
`/releases/latest` endpoint excludes RC prereleases.
