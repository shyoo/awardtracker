import pytest

from scripts.release_tag import bump_triple, compare_versions, parse_tag, plan_release


HEAD = "a" * 40
SHIPPED = [{"name": "v1.3.10", "commit": "1" * 40}]


def test_parse_and_compare_release_versions():
    assert parse_tag("v1.4.0-rc.2").triple == (1, 4, 0)
    assert parse_tag("v1.4.0-rc.2").rc == 2
    assert parse_tag("1.4.0") is None
    assert compare_versions("1.4.0-rc.1", "1.4.0-rc.2") < 0
    assert compare_versions("1.4.0-rc.2", "1.4.0") < 0
    assert compare_versions("1.4.0", "1.5.0-rc.1") < 0


def test_bump_triple():
    assert bump_triple((1, 3, 10), "patch") == (1, 3, 11)
    assert bump_triple((1, 3, 10), "minor") == (1, 4, 0)
    assert bump_triple((1, 3, 10), "major") == (2, 0, 0)


def test_rc_starts_patch_series_by_default_and_honors_bump():
    assert plan_release(SHIPPED, "rc", HEAD)["version"] == "1.3.11-rc.1"
    assert plan_release(SHIPPED, "rc", HEAD, "minor")["version"] == "1.4.0-rc.1"


def test_rc_continues_open_series():
    tags = SHIPPED + [{"name": "v1.4.0-rc.1", "commit": "2" * 40}]
    plan = plan_release(tags, "rc", HEAD)
    assert plan["version"] == "1.4.0-rc.2"
    assert plan["commit"] == HEAD


def test_promote_uses_latest_rc_commit():
    tags = SHIPPED + [
        {"name": "v1.4.0-rc.1", "commit": "2" * 40},
        {"name": "v1.4.0-rc.2", "commit": "3" * 40},
    ]
    plan = plan_release(tags, "promote", HEAD)
    assert plan["version"] == "1.4.0"
    assert plan["commit"] == "3" * 40


def test_release_plan_refuses_missing_rc_or_backwards_literal():
    with pytest.raises(ValueError, match="nothing to promote"):
        plan_release(SHIPPED, "promote", HEAD)
    with pytest.raises(ValueError, match="not above"):
        plan_release(SHIPPED, "1.3.10", HEAD)
    with pytest.raises(ValueError, match="not a version"):
        plan_release(SHIPPED, "latest", HEAD)


def test_release_plan_refuses_bump_that_would_go_backwards():
    tags = SHIPPED + [{"name": "v1.4.0-rc.1", "commit": "2" * 40}]
    with pytest.raises(ValueError, match="not above"):
        plan_release(tags, "rc", HEAD, "patch")
