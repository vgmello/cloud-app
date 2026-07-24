import pytest
from conftest import FIXTURES, load_golden

from cloudapp import builds, manifest


@pytest.mark.parametrize(
    ("fixture", "env", "name"),
    [
        ("minimal", "dev", "orders-api"),
        ("full", "prod", "orders-api"),
        ("multi", "dev", "billing"),
        ("partial", "dev", "partial"),
        ("codefn", "dev", "codefn"),
    ],
)
def test_build_plan_matches_golden(fixture, env, name):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{fixture}.yml")
    plan = builds.enumerate_builds(tools[env], name, "acr.example.io", "shaabc")
    assert plan == load_golden(f"builds.{fixture}")
