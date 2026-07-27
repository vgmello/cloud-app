import pytest
from conftest import ENVDIR, FIXTURES, load_golden

from cloudapp import manifest, resolve


def test_minimal_dev_tfvars_matches_golden():
    _, _, tools, _ = manifest.parse(FIXTURES / "minimal.yml")
    tfvars = resolve.resolve(tools["dev"], ENVDIR / "dev.yml", "dev")
    assert tfvars == load_golden("tfvars.minimal.dev")


def test_missing_platform_file_fails_with_clear_message():
    with pytest.raises(resolve.ResolveError, match="platform config not found"):
        resolve.resolve({}, ENVDIR / "nonexistent.yml", "nonexistent")


def test_deploy_policy_is_kept_out_of_tfvars(tmp_path):
    """`deploy:` governs how the action ships the stack, not what Terraform
    builds. Leaking it into tfvars would churn the generated test fixtures and
    hand the module a key it has no use for."""
    platform = tmp_path / "dev.yml"
    platform.write_text("subscription_id: sub\n")
    tool = {"name": "orders-api", "deploy": {"verify": False}, "apps": {}}

    tfvars = resolve.resolve(tool, str(platform), "dev")

    assert "deploy" not in tfvars["config"]
    assert tfvars["config"]["name"] == "orders-api"
