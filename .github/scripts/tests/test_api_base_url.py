"""The two network scripts resolve their API base from GITHUB_API_URL.

GitHub Actions sets that variable on every runner, so the default path is
unchanged in CI; the e2e suite relies on the override to point the scripts at a
local server instead of api.github.com.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1]
NAMES = ["dispatch_and_wait", "fetch_bootstrap_cache"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", NAMES)
def test_defaults_to_public_api(name, monkeypatch):
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    assert load(name).API == "https://api.github.com"


@pytest.mark.parametrize("name", NAMES)
def test_reads_github_api_url(name, monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:8123")
    assert load(name).API == "http://127.0.0.1:8123"


@pytest.mark.parametrize("name", NAMES)
def test_strips_trailing_slash(name, monkeypatch):
    """URLs are built as f"{API}/repos/...", so a trailing slash would produce a
    double slash and a 404 on some servers."""
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:8123/")
    assert load(name).API == "http://127.0.0.1:8123"
