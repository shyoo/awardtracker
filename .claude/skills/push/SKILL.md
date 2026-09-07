---
name: push
description: >-
  Use this skill when the user asks to push the current branch to the GitHub
  remote ("push", "push to remote", "push the branch"). It runs the full test
  suite first and refuses to push if anything fails. It deliberately does NOT
  bump the version, write release notes, build binaries, or create a release —
  use the deploy skill for that.
---

# /push — test, then push the branch

Push the current branch to `origin`. Nothing else.

## Non-goals

This skill **must not**:

- modify `version.txt`
- write or update anything under `docs/release_notes/`
- run `release-win.ps1` or `release-macos.sh`
- create a git tag or a GitHub release
- squash, rebase, or otherwise rewrite existing commits

If the user wants a release, stop and point them at `/deploy`.

## Steps

### 1. Check the branch

```bash
git rev-parse --abbrev-ref HEAD
```

If it is `main`, stop. Ask the user to move the work onto a feature branch
first — this project does not push directly to `main`.

### 2. Check the tree is clean

```bash
git status --porcelain
```

If there are uncommitted changes, show them and ask whether to commit them
before pushing. Do not commit silently, and do not push a tree that does not
match what you tested.

### 3. Run the full test suite

Windows:

```bash
venv/Scripts/python.exe -m pytest -q
```

macOS/Linux:

```bash
venv/bin/python -m pytest -q
```

If `venv/` is absent (for example inside a git worktree), fall back to the
interpreter from the main checkout, e.g.
`C:/Dev/awardtracker/venv/Scripts/python.exe -m pytest -q`.

**Every test must pass.** Skipped tests are fine. If anything fails, stop the
skill, report the failures verbatim, and do not push. Fix-then-retry is the
user's call, not an automatic step.

### 4. Push

```bash
git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

Use a plain push. Only use `--force-with-lease` if the user explicitly asks and
the target is not `main`. Never use bare `--force`.

### 5. Report

Report the pushed branch and its compare URL. If there is no open PR, you may
*offer* to run `gh pr create`, but do not create one unless the user says yes.

## What happens next

The push triggers `.github/workflows/ci.yml`, which reruns the suite on both
`windows-latest` and `macos-latest`. That is a backstop, not a substitute for
step 3. If the user wants to watch it: `gh run watch`.
