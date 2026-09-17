from pathlib import Path
import subprocess

import pytest

from versioning import resolve_version, version_from_describe


def test_version_from_describe_handles_final_rc_and_dirty_builds():
    assert version_from_describe("v1.3.10-0-gabc1234") == "1.3.10"
    assert version_from_describe("v1.4.0-rc.1-0-gabc1234") == "1.4.0-rc.1"
    assert version_from_describe("v1.3.10-7-gabc1234-dirty") == "1.3.10+7.gabc1234.dirty"
    assert version_from_describe("not-a-tag") is None


def test_explicit_release_version_wins(tmp_path: Path):
    assert resolve_version(repo_dir=tmp_path, env={"AT_RELEASE_VERSION": "v1.4.0-rc.2"}) == "1.4.0-rc.2"


def test_invalid_explicit_release_version_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="not SemVer"):
        resolve_version(repo_dir=tmp_path, env={"AT_RELEASE_VERSION": "latest"})


def test_version_file_is_offline_fallback(tmp_path: Path, monkeypatch):
    (tmp_path / "version.txt").write_text("1.3.10\n", encoding="utf-8")

    def fail_git(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr("versioning.subprocess.run", fail_git)
    assert resolve_version(repo_dir=tmp_path, bundle_dir=tmp_path, env={}) == "1.3.10"
