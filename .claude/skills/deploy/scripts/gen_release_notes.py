#!/usr/bin/env python3
"""Scaffold docs/release_notes/release_notes_v<VERSION>.md.

Usage:
    python gen_release_notes.py <VERSION> [--since <TAG>] [--force]

Lists every commit since the previous version tag (across all merged branches,
not just the current one) in the format past releases use. The prose summary and
the grouped "New Features & Fixes" bullets are left as TODO placeholders for the
agent to fill in — this script only guarantees no commit is missed.
"""
import argparse
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
NOTES_DIR = REPO_ROOT / "docs" / "release_notes"

TEMPLATE = """# Award Tracker v{version}

TODO: one-paragraph summary of what this release introduces or fixes.

---

## \N{ROCKET} New Features & Fixes

TODO: group the commits below into user-facing bullets, e.g.
- **Feature name**: what changed and why it matters.

---

## \N{FILE FOLDER} Commits in this Release

{commits}
"""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def previous_tag() -> str:
    try:
        return git("describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        raise SystemExit("no previous tag found; pass --since <TAG> explicitly")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the new version, without a leading v")
    parser.add_argument("--since", help="base tag (default: most recent tag)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing notes file")
    args = parser.parse_args()

    base = args.since or previous_tag()
    log = git("log", "--no-merges", "--format=* `%h` `%s`", f"{base}..HEAD")
    if not log:
        raise SystemExit(f"no commits between {base} and HEAD — nothing to release")

    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    out = NOTES_DIR / f"release_notes_v{args.version}.md"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists (pass --force to overwrite)")

    out.write_text(TEMPLATE.format(version=args.version, commits=log), encoding="utf-8")
    print(f"{out}  ({len(log.splitlines())} commits since {base})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
