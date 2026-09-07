#!/usr/bin/env python3
"""Bump version.txt.

Usage:
    python bump_version.py [major|minor|patch] [--dry-run]

Defaults to a minor bump (1.3.10 -> 1.4.0), which is this project's release
default. Prints the new version to stdout so a caller can capture it.
"""
import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
VERSION_FILE = REPO_ROOT / "version.txt"


def bump(current: str, part: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current.strip())
    if not match:
        raise SystemExit(f"version.txt does not hold a MAJOR.MINOR.PATCH version: {current!r}")
    major, minor, patch = (int(g) for g in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", nargs="?", default="minor", choices=["major", "minor", "patch"])
    parser.add_argument("--dry-run", action="store_true", help="print the new version without writing it")
    args = parser.parse_args()

    if not VERSION_FILE.exists():
        raise SystemExit(f"{VERSION_FILE} not found")

    current = VERSION_FILE.read_text(encoding="utf-8").strip()
    new = bump(current, args.part)

    if not args.dry_run:
        VERSION_FILE.write_text(new + "\n", encoding="utf-8")

    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
