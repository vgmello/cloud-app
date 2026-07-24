import pytest

from cloudapp import manifest
from conftest import FIXTURES, load_golden, load_manifest

VALID = ["minimal", "full", "multi", "partial", "databases"]
INVALID = [
    "invalid-missing-name",
    "invalid-legacy-type",
    "invalid-unknown-key",
    "invalid-empty-environments",
    "invalid-no-compute",
    "invalid-mixed-container",
    "invalid-db-type",
    "invalid-app-and-apps",
    "invalid-image-and-docker",
    "invalid-function-image-docker",
    "invalid-env-number",
    "invalid-database-and-databases",
]


@pytest.mark.parametrize("name", VALID)
def test_valid_manifests_pass_schema(name):
    assert manifest.validate(load_manifest(name)) == []


@pytest.mark.parametrize("name", INVALID)
def test_invalid_manifests_fail_schema(name):
    assert manifest.validate(load_manifest(name)) != []


@pytest.mark.parametrize(
    ("name", "env", "golden"),
    [
        ("minimal", "dev", "minimal.dev"),
        ("full", "dev", "full.dev"),
        ("full", "prod", "full.prod"),
        ("multi", "dev", "multi.dev"),
        ("partial", "dev", "partial.dev"),
        ("partial", "prod", "partial.prod"),
    ],
)
def test_normalized_tool_matches_golden(name, env, golden):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{name}.yml")
    assert tools[env] == load_golden(golden)


def test_environments_default_to_dev():
    _, environments, tools, _ = manifest.parse(FIXTURES / "minimal.yml")
    assert environments == ["dev"]
    assert set(tools) == {"dev"}


def test_environments_follow_manifest_key_order():
    _, environments, _, _ = manifest.parse(FIXTURES / "full.yml")
    assert environments == ["dev", "prod"]


def test_app_shorthand_folds_into_apps_main():
    _, _, tools, _ = manifest.parse(FIXTURES / "minimal.yml")
    assert list(tools["dev"]["apps"]) == ["main"]


def test_overlay_app_mixed_with_base_apps_fails():
    with pytest.raises(manifest.ManifestError, match="mixes singular app"):
        manifest.parse(FIXTURES / "invalid-overlay-app-mix.yml")


def test_invalid_manifest_raises_with_schema_errors():
    with pytest.raises(manifest.ManifestError, match="validation failed"):
        manifest.parse(FIXTURES / "invalid-legacy-type.yml")


def test_docker_false_without_any_docker_source():
    _, _, _, docker = manifest.parse(FIXTURES / "minimal.yml")
    assert docker is False


def test_docker_true_when_entry_has_docker_section():
    _, _, _, docker = manifest.parse(FIXTURES / "full.yml")
    assert docker is True


def test_docker_true_when_a_container_has_docker_section():
    _, _, _, docker = manifest.parse(FIXTURES / "multi.yml")
    assert docker is True


def test_docker_true_when_dockerfile_exists_in_app_root(tmp_path):
    (tmp_path / "Dockerfile").touch()
    _, _, _, docker = manifest.parse(FIXTURES / "minimal.yml", app_root=tmp_path)
    assert docker is True


def test_deep_merge_maps_merge_arrays_replace():
    base = {"a": {"x": 1, "y": 2}, "list": [1, 2], "keep": "k"}
    override = {"a": {"y": 3}, "list": [9]}
    assert manifest.deep_merge(base, override) == {
        "a": {"x": 1, "y": 3},
        "list": [9],
        "keep": "k",
    }


def test_partial_ingress_object_fills_defaults_and_port():
    _, _, tools, _ = manifest.parse(FIXTURES / "partial.yml")
    assert tools["dev"]["apps"]["main"]["ingress"] == {
        "external": False,
        "target_port": 5000,
        "transport": "http2",
        "allow_insecure": False,
    }
