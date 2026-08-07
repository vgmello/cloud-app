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


def test_component_images_go_under_the_stack_prefix():
    """The apply identity's ACR push grant is an ABAC prefix condition on
    '<stack>/', so the component may only add a segment beneath it."""
    _, _, tools, _ = manifest.parse(FIXTURES / "sharedapi.yml")
    plan = builds.enumerate_builds(tools["dev"], "shop", "acr.example.io", "shaabc")
    assert plan["tags"] == {"main/main": "acr.example.io/shop/api/main-main:shaabc"}


def test_components_of_one_stack_do_not_share_an_image_repository():
    _, _, root, _ = manifest.parse(FIXTURES / "minimal.yml")
    _, _, component, _ = manifest.parse(FIXTURES / "sharedapi.yml")
    a = builds.enumerate_builds(root["dev"], "shop", "acr.example.io", "sha")["tags"]["main/main"]
    b = builds.enumerate_builds(component["dev"], "shop", "acr.example.io", "sha")["tags"]["main/main"]
    assert a != b
    assert a.startswith("acr.example.io/shop/") and b.startswith("acr.example.io/shop/")
