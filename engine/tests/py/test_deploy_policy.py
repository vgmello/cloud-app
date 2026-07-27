"""Deploy policy resolution: manifest `deploy:` with an action-input override.

The precedence matters more than it looks. A composite action's inputs always
carry their declared default, so "the caller did not pass this" and "the caller
passed the default" are the same string. That is why the inputs default to
empty and only a non-empty value counts as an override -- get it wrong and a
manifest could never win.
"""

import pytest
from conftest import FIXTURES

from cloudapp.manifest import DEPLOY_DEFAULTS, ManifestError, deploy_policy, parse


def test_no_manifest_block_and_no_overrides_uses_the_defaults():
    assert deploy_policy({}) == DEPLOY_DEFAULTS


def test_defaults_match_the_actions_previous_input_defaults():
    """A manifest with no deploy: block must behave exactly as before this
    existed, or moving the knobs silently changes every caller's deploy."""
    assert DEPLOY_DEFAULTS == {
        "always_run_terraform": False,
        "verify": True,
        "verify_timeout": 300,
    }


def test_manifest_block_wins_over_the_defaults():
    tool = {"deploy": {"always_run_terraform": True, "verify_timeout": 600}}
    assert deploy_policy(tool) == {
        "always_run_terraform": True,
        "verify": True,          # untouched keys keep their default
        "verify_timeout": 600,
    }


def test_explicit_override_wins_over_the_manifest():
    tool = {"deploy": {"verify": True, "verify_timeout": 600}}
    policy = deploy_policy(tool, {"verify": "false", "verify_timeout": "30"})
    assert policy["verify"] is False
    assert policy["verify_timeout"] == 30


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_override_is_not_an_override(blank):
    """The whole backwards-compatibility story rests on this: an input left at
    its empty default must fall through to the manifest."""
    tool = {"deploy": {"verify": False}}
    assert deploy_policy(tool, {"verify": blank})["verify"] is False


def test_overrides_still_apply_without_a_manifest_block():
    policy = deploy_policy({}, {"always_run_terraform": "true"})
    assert policy["always_run_terraform"] is True


@pytest.mark.parametrize("value", [True, False])
def test_manifest_booleans_are_taken_as_booleans(value):
    assert deploy_policy({"deploy": {"verify": value}})["verify"] is value


@pytest.mark.parametrize("value", ["TRUE", "False", " true "])
def test_override_booleans_are_parsed_case_and_space_insensitively(value):
    expected = value.strip().lower() == "true"
    assert deploy_policy({}, {"verify": value})["verify"] is expected


def test_a_non_boolean_is_rejected_rather_than_coerced():
    """Silently treating 'yes' as false would turn verification off without
    saying so -- exactly the failure the verify step exists to prevent."""
    with pytest.raises(ManifestError, match="must be true or false"):
        deploy_policy({}, {"verify": "yes"})


def test_a_non_numeric_timeout_is_rejected():
    with pytest.raises(ManifestError, match="whole number of seconds"):
        deploy_policy({}, {"verify_timeout": "5m"})


@pytest.mark.parametrize("value", [0, -1, 3601])
def test_out_of_range_timeouts_are_rejected(value):
    with pytest.raises(ManifestError, match="between 1 and 3600"):
        deploy_policy({}, {"verify_timeout": value})


def test_a_string_timeout_from_the_action_becomes_an_int():
    assert deploy_policy({}, {"verify_timeout": "45"})["verify_timeout"] == 45


def test_policy_differs_per_environment():
    """The point of moving these into the manifest: dev and prod can disagree.
    As action inputs they were fixed for every environment a workflow deployed."""
    _, _, tools, _ = parse(FIXTURES / "deploy-policy.yml")

    dev = deploy_policy(tools["dev"])
    prod = deploy_policy(tools["prod"])

    assert dev["verify"] is False
    assert prod["verify"] is True          # inherited from the base block
    assert dev["verify_timeout"] == 120    # inherited from the base block
    assert prod["verify_timeout"] == 600
    assert dev["always_run_terraform"] is False
    assert prod["always_run_terraform"] is True
