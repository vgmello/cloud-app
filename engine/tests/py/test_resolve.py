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
