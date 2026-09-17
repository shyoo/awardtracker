#!/usr/bin/env python3
"""Plan and cut tag-driven Award Tracker releases without making commits."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cmp_to_key
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Iterable, Optional


REPOSITORY = "shyoo/awardtracker"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")


@dataclass(frozen=True)
class VersionTag:
    name: str
    version: str
    triple: tuple[int, int, int]
    rc: Optional[int]
    commit: str = ""


def parse_tag(name: str, commit: str = "") -> Optional[VersionTag]:
    match = TAG_RE.fullmatch(name.strip())
    if not match:
        return None
    major, minor, patch, rc = match.groups()
    canonical = f"v{major}.{minor}.{patch}" + (f"-rc.{rc}" if rc else "")
    return VersionTag(
        name=canonical,
        version=canonical[1:],
        triple=(int(major), int(minor), int(patch)),
        rc=int(rc) if rc else None,
        commit=commit,
    )


def compare_versions(left: str, right: str) -> int:
    a = parse_tag(f"v{left.removeprefix('v')}")
    b = parse_tag(f"v{right.removeprefix('v')}")
    if not a or not b:
        raise ValueError(f"not a release version: {left if not a else right!r}")
    if a.triple != b.triple:
        return (a.triple > b.triple) - (a.triple < b.triple)
    if a.rc == b.rc:
        return 0
    if a.rc is None:
        return 1
    if b.rc is None:
        return -1
    return (a.rc > b.rc) - (a.rc < b.rc)


def bump_triple(triple: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = triple
    if kind == "major":
        return major + 1, 0, 0
    if kind == "minor":
        return major, minor + 1, 0
    if kind == "patch":
        return major, minor, patch + 1
    raise ValueError(f"unknown bump: {kind}")


def plan_release(
    tags: Iterable[dict[str, str]],
    request: str,
    head: str,
    bump: Optional[str] = None,
) -> dict[str, Optional[str]]:
    if bump and request != "rc":
        raise ValueError("--bump is valid only with an rc request")
    known = [parsed for tag in tags if (parsed := parse_tag(tag["name"], tag.get("commit", "")))]
    known.sort(key=cmp_to_key(lambda a, b: compare_versions(a.version, b.version)))
    finals = [tag for tag in known if tag.rc is None]
    last_final = finals[-1] if finals else None
    base = last_final.triple if last_final else (0, 0, 0)
    open_rcs = [tag for tag in known if tag.rc is not None and tag.triple > base]
    since = last_final.name if last_final else None

    if request == "rc":
        if bump:
            triple = bump_triple(base, bump)
        elif open_rcs:
            triple = open_rcs[-1].triple
        else:
            triple = bump_triple(base, "minor")
        series = [tag for tag in open_rcs if tag.triple == triple]
        rc = max((tag.rc or 0 for tag in series), default=0) + 1
        version = f"{'.'.join(map(str, triple))}-rc.{rc}"
        if known and compare_versions(version, known[-1].version) <= 0:
            raise ValueError(f"v{version} is not above the highest existing tag {known[-1].name}")
        why = f"continues {series[-1].name}" if series else f"starts the {'.'.join(map(str, triple))} series"
        return {"version": version, "commit": head, "since": since, "why": why}

    if request == "promote":
        if not open_rcs:
            previous = last_final.name if last_final else "any final"
            raise ValueError(f"nothing to promote: no RC exists above {previous}")
        rc = open_rcs[-1]
        return {
            "version": ".".join(map(str, rc.triple)),
            "commit": rc.commit,
            "since": since,
            "why": f"promotes {rc.name} on its verified commit",
        }

    literal = parse_tag(f"v{request.removeprefix('v')}")
    if not literal:
        raise ValueError(f"not a version: {request!r}; use rc, promote, or MAJOR.MINOR.PATCH[-rc.N]")
    if known and compare_versions(literal.version, known[-1].version) <= 0:
        raise ValueError(f"{literal.name} is not above the highest existing tag {known[-1].name}")
    return {"version": literal.version, "commit": head, "since": since, "why": "chosen explicitly"}


def git(*args: str, cwd: Optional[Path] = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def read_tags(cwd: Path) -> list[dict[str, str]]:
    output = git(
        "for-each-ref",
        "refs/tags/v*",
        "--format=%(refname:short)|%(*objectname)|%(objectname)",
        cwd=cwd,
    )
    tags = []
    for line in output.splitlines():
        if not line:
            continue
        name, peeled, direct = line.split("|", 2)
        tags.append({"name": name, "commit": peeled or direct})
    return tags


def _counts(cwd: Path, revision_range: str) -> tuple[int, int]:
    left, right = git("rev-list", "--left-right", "--count", revision_range, cwd=cwd).split()
    return int(left), int(right)


def release_base_problems(cwd: Path) -> list[str]:
    """Protect against releasing code origin/main does not contain."""
    common_dir = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd))
    trunk = common_dir.parent
    try:
        trunk_branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=trunk)
    except subprocess.CalledProcessError:
        trunk_branch = "main"

    _, trunk_ahead = _counts(cwd, f"origin/main...{trunk_branch}")
    head_behind, _ = _counts(cwd, "origin/main...HEAD")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=trunk,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()

    problems = []
    if trunk_ahead:
        problems.append(f"the main checkout is {trunk_ahead} commit(s) ahead of origin/main; push it first")
    if head_behind:
        problems.append(f"this checkout is {head_behind} commit(s) behind origin/main; update it first")
    if dirty:
        names = ", ".join(line[3:] for line in dirty[:3])
        problems.append(f"the main checkout has tracked changes ({names}); commit or discard them first")
    return problems


def ci_status(commit: str) -> Optional[dict[str, object]]:
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?head_sha={commit}&per_page=10",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    runs = [run for run in json.loads(result.stdout).get("workflow_runs", []) if run.get("event") == "push"]
    return runs[0] if runs else None


def _print_plan(plan: dict[str, Optional[str]]) -> None:
    version = plan["version"] or ""
    print(f"version {version}")
    print(f"commit {plan['commit']}")
    print(f"since {plan['since'] or '(no final release yet)'}")
    print(f"why {plan['why']}")
    if "-rc." in version:
        print("publishes as a prerelease: invisible to installed apps")
    else:
        print("publishes as latest: installed apps will be offered it")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("request", nargs="?", default="rc")
    plan_parser.add_argument("--bump", choices=["major", "minor", "patch"])

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("tag")

    cut_parser = subparsers.add_parser("cut")
    cut_parser.add_argument("version")
    cut_parser.add_argument("--notes", required=True, type=Path)
    cut_parser.add_argument("--commit")
    cut_parser.add_argument("--wait", action="store_true")
    cut_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd()

    git("fetch", "--quiet", "--tags", "origin", cwd=cwd)
    if args.command == "plan":
        try:
            plan = plan_release(read_tags(cwd), args.request, git("rev-parse", "origin/main", cwd=cwd), args.bump)
        except ValueError as exc:
            parser.error(str(exc))
        _print_plan(plan)
        return 0

    if args.command == "validate":
        tag = parse_tag(args.tag)
        if not tag:
            parser.error("validate requires vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N")
        previous = [known for known in read_tags(cwd) if known["name"] != tag.name]
        try:
            plan_release(previous, tag.version, git("rev-parse", f"{tag.name}^{{commit}}", cwd=cwd))
        except ValueError as exc:
            parser.error(str(exc))
        print(f"{tag.name} moves forward from every existing release tag")
        return 0

    tag = parse_tag(f"v{args.version.removeprefix('v')}")
    if not tag:
        parser.error("cut requires MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rc.N")
    notes = args.notes.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not notes:
        parser.error(f"{args.notes} is empty")
    if re.search(r"^#\s", notes, re.MULTILINE):
        parser.error("release notes must not contain a top-level heading")

    problems = release_base_problems(cwd)
    commit = git("rev-parse", args.commit or "origin/main", cwd=cwd)
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/main"], cwd=cwd
    ).returncode:
        problems.append(f"{commit[:7]} is not on origin/main")
    known = read_tags(cwd)
    if any(item["name"] == tag.name for item in known):
        problems.append(f"{tag.name} already exists locally")
    if git("ls-remote", "--tags", "origin", f"refs/tags/{tag.name}", cwd=cwd):
        problems.append(f"{tag.name} already exists on origin")
    try:
        plan_release(known, tag.version, commit)
    except ValueError as exc:
        problems.append(str(exc))

    run = ci_status(commit)
    if not run:
        problems.append(f"no push-triggered CI run exists for {commit[:7]}")
    elif run.get("status") != "completed" and args.wait:
        subprocess.run(["gh", "run", "watch", str(run["id"]), "--exit-status"], check=False)
        run = ci_status(commit)
    if run and (run.get("status") != "completed" or run.get("conclusion") != "success"):
        problems.append(f"CI run {run.get('id')} is {run.get('status')}/{run.get('conclusion')}")

    if problems:
        for problem in problems:
            print(f"REFUSING: {problem}", file=sys.stderr)
        return 1

    message = f"Award Tracker {tag.name}\n\n{notes}\n"
    print(f"would tag {tag.name} on {commit} and push it, with this message:\n\n{message}")
    if args.dry_run:
        return 0

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(message)
        message_path = Path(handle.name)
    try:
        git("tag", "--annotate", "--cleanup=verbatim", "--file", str(message_path), tag.name, commit, cwd=cwd)
        git("push", "origin", f"refs/tags/{tag.name}", cwd=cwd)
    finally:
        message_path.unlink(missing_ok=True)
    print(f"tagged and pushed {tag.name}; Actions will publish https://github.com/{REPOSITORY}/releases/tag/{tag.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
