from pathlib import Path

import pytest
from conftest import FIXTURES, load_golden, load_manifest

from cloudapp import manifest

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
        ("databases", "dev", "databases.dev"),
        ("databases", "prod", "databases.prod"),
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


def test_database_and_databases_via_overlay_raises():
    with pytest.raises(manifest.ManifestError, match="mixes singular database with databases"):
        manifest.parse(FIXTURES / "invalid-db-overlay-mix.yml")


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


def test_legacy_database_folds_into_databases_main():
    _, _, tools, _ = manifest.parse(FIXTURES / "full.yml")
    cfg = tools["dev"]
    assert "database" not in cfg
    assert list(cfg["databases"]) == ["main"]
    assert cfg["databases"]["main"]["dbs"] == ["main"]
    assert cfg["database_legacy"] is True


def test_databases_entry_defaults_dbs_to_main():
    _, _, tools, _ = manifest.parse(FIXTURES / "databases.yml")
    assert tools["dev"]["databases"]["reporting"]["dbs"] == ["main"]
    assert "database_legacy" not in tools["dev"]


def test_databases_merges_entry_defaults():
    _, _, tools, _ = manifest.parse(FIXTURES / "databases.yml")
    primary = tools["dev"]["databases"]["primary"]
    assert primary["type"] == "postgres"
    assert primary["storage_gb"] == 32
    assert primary["public_access"] is False


def test_unknown_db_server_ref_raises():
    with pytest.raises(manifest.ManifestError, match="ghost/main"):
        manifest.parse(FIXTURES / "invalid-db-ref-server.yml")


def test_unknown_db_name_ref_raises():
    with pytest.raises(manifest.ManifestError, match="primary/ghost"):
        manifest.parse(FIXTURES / "invalid-db-ref-name.yml")


def _validate(m):
    return manifest.validate(m)


def test_runtime_package_function_is_valid():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "python:3.11", "package": "./scripts"}},
    }
    assert _validate(m) == []


def test_runtime_docker_builder_is_valid():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build"}}},
    }
    assert _validate(m) == []


def test_package_requires_runtime():
    m = {"name": "orders", "functions": {"worker": {"package": "./scripts"}}}
    assert _validate(m) != []


def test_runtime_needs_exactly_one_artifact():
    m = {"name": "orders", "functions": {"worker": {"runtime": "python:3.11"}}}
    assert _validate(m) != []


def test_runtime_rejects_two_artifacts():
    m = {
        "name": "orders",
        "functions": {"worker": {"runtime": "python:3.11", "package": "./s", "image": "x:1"}},
    }
    assert _validate(m) != []


def test_bad_runtime_value_rejected():
    m = {"name": "orders", "functions": {"worker": {"runtime": "ruby:3", "package": "./s"}}}
    assert _validate(m) != []


def test_container_function_no_runtime_still_valid():
    m = {"name": "orders", "functions": {"worker": {"image": "myacr.io/x:1"}}}
    assert _validate(m) == []


def test_function_mode():
    assert manifest.function_mode({"runtime": "python:3.11", "package": "./s"}) == "code"
    assert manifest.function_mode({"image": "x:1"}) == "container"
    assert manifest.function_mode({"docker": {"file": "./Dockerfile"}}) == "container"


def test_docker_gate_ignores_code_functions():
    # A code function whose builder is a Dockerfile must NOT flip the ACR docker gate.
    tool = {"functions": {"w": {"runtime": "dotnet-isolated:8.0", "docker": {"file": "./Dockerfile.build"}}}}
    assert manifest._uses_docker_build(tool) is False


def test_docker_gate_still_true_for_container_function():
    tool = {"functions": {"w": {"docker": {"file": "./Dockerfile"}}}}
    assert manifest._uses_docker_build(tool) is True


def test_terraform_shorthand_string_is_valid():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "./terraform"}
    assert manifest.validate(m) == []


def test_terraform_object_with_providers_is_valid():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}],
        },
    }
    assert manifest.validate(m) == []


def test_terraform_object_requires_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": {"providers": []}}
    assert manifest.validate(m) != []


def test_terraform_rejects_non_allowlisted_provider():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "terraform": {
            "dir": "./terraform",
            "providers": [{"name": "aws", "source": "hashicorp/aws", "version": "~> 5"}],
        },
    }
    assert manifest.validate(m) != []


def test_terraform_rejects_parent_escape_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "../evil"}
    assert manifest.validate(m) != []


def test_terraform_rejects_absolute_dir():
    m = {"name": "orders", "app": {"port": 8080}, "terraform": "/etc"}
    assert manifest.validate(m) != []


def test_terraform_allowed_in_environment_overlay():
    m = {
        "name": "orders",
        "app": {"port": 8080},
        "environments": {"prod": {"terraform": "./terraform-prod"}},
    }
    assert manifest.validate(m) == []


def test_normalize_terraform_shorthand_folds_to_object():
    cfg = manifest.normalize({"name": "orders", "terraform": "./terraform"})
    assert cfg["terraform"] == {"dir": "./terraform", "providers": []}


def test_normalize_terraform_object_defaults_providers():
    cfg = manifest.normalize({"name": "orders", "terraform": {"dir": "./tf"}})
    assert cfg["terraform"] == {"dir": "./tf", "providers": []}


def test_normalize_terraform_object_keeps_providers():
    providers = [{"name": "random", "source": "hashicorp/random", "version": "~> 3"}]
    cfg = manifest.normalize({"name": "orders", "terraform": {"dir": "./tf", "providers": providers}})
    assert cfg["terraform"] == {"dir": "./tf", "providers": providers}


def test_normalize_without_terraform_leaves_key_absent():
    cfg = manifest.normalize({"name": "orders"})
    assert "terraform" not in cfg


def test_the_schema_ships_inside_the_package():
    """The engine must not reach outside its own directory to validate a manifest."""
    package_root = Path(manifest.__file__).parent
    assert manifest.SCHEMA_PATH.is_file()
    assert manifest.SCHEMA_PATH.is_relative_to(package_root)


def test_package_data_covers_every_non_python_file_the_engine_reads():
    """Schema and defaults must be declared as package data, or an installed
    engine validates nothing and resolves no defaults."""
    pyproject = (Path(manifest.__file__).parents[1] / "pyproject.toml").read_text()
    assert 'cloudapp = ["defaults/*.yml", "schema/*.json"]' in pyproject
