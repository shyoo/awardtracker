"""Resolve the application version from a release tag or the local checkout."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import Mapping, Optional


PLACEHOLDER_VERSION = "0.0.0"
SEMVER_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)


def is_semver(value: str) -> bool:
    return bool(SEMVER_RE.fullmatch(value))


def version_from_describe(description: str) -> Optional[str]:
    """Convert ``git describe --long --dirty`` output to a SemVer value."""
    value = description.strip()
    dirty = value.endswith("-dirty")
    if dirty:
        value = value[: -len("-dirty")]
    match = re.fullmatch(r"v?(.+)-(\d+)-g([0-9a-f]+)", value)
    if not match:
        return None

    tag, count, sha = match.groups()
    if not is_semver(tag) or "+" in tag:
        return None

    metadata = []
    if int(count):
        metadata.extend((count, f"g{sha}"))
    if dirty:
        metadata.append("dirty")
    return tag if not metadata else f"{tag}+{'.'.join(metadata)}"


def resolve_version(
    *,
    repo_dir: Optional[Path] = None,
    bundle_dir: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Return the build version, preferring an explicit release-tag version."""
    environment = os.environ if env is None else env
    supplied = environment.get("AT_RELEASE_VERSION", "").strip().removeprefix("v")
    if supplied:
        if not is_semver(supplied):
            raise ValueError(f"AT_RELEASE_VERSION is not SemVer: {supplied!r}")
        return supplied

    checkout = Path(repo_dir or Path(__file__).resolve().parent)
    try:
        output = subprocess.run(
            ["git", "describe", "--tags", "--match", "v*", "--long", "--dirty"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        described = version_from_describe(output)
        if described:
            return described
    except (OSError, subprocess.CalledProcessError):
        pass

    version_file = Path(bundle_dir or checkout) / "version.txt"
    try:
        fallback = version_file.read_text(encoding="utf-8").strip()
        if is_semver(fallback):
            return fallback
    except OSError:
        pass
    return PLACEHOLDER_VERSION
