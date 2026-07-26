"""Unit tests for fetch_bootstrap_cache.py. Like dispatch_and_wait.py, the
script ships with the composite action, so it is loaded by path. Every test
monkeypatches urllib.request.urlopen so no real HTTP happens."""

import base64
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "fetch_bootstrap_cache.py"


@pytest.fixture(scope="module")
def fbc():
    spec = importlib.util.spec_from_file_location("fetch_bootstrap_cache", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OWNER", "acme")
    monkeypatch.setenv("CONTROL_REPO", "cloud-app")
    monkeypatch.setenv("CACHE_PATH", "registries/dev/orders.bootstrap.yml")
    monkeypatch.setenv("GH_TOKEN", "secret")


class _Resp:
    """Fake urlopen response / context manager wrapping a JSON payload."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _content_payload(text):
    return {"content": base64.b64encode(text.encode()).decode()}


def _http_error(code):
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", None, io.BytesIO(b""))


def test_200_response_writes_decoded_content(fbc, tmp_path, monkeypatch):
    dest = tmp_path / "cache.yml"
    monkeypatch.setattr(fbc.urllib.request, "urlopen", lambda req, timeout=15: _Resp(_content_payload("stack_name: orders\n")))
    monkeypatch.setattr("sys.argv", ["fetch_bootstrap_cache.py", str(dest)])

    fbc.main()

    assert dest.read_text() == "stack_name: orders\n"


def test_404_writes_nothing_and_exits_cleanly(fbc, tmp_path, monkeypatch):
    dest = tmp_path / "cache.yml"

    def raise_404(req, timeout=15):
        raise _http_error(404)

    monkeypatch.setattr(fbc.urllib.request, "urlopen", raise_404)
    monkeypatch.setattr("sys.argv", ["fetch_bootstrap_cache.py", str(dest)])

    fbc.main()  # must not raise

    assert not dest.exists()


def test_non_404_http_error_warns_and_writes_nothing(fbc, tmp_path, monkeypatch, capsys):
    dest = tmp_path / "cache.yml"

    def raise_500(req, timeout=15):
        raise _http_error(500)

    monkeypatch.setattr(fbc.urllib.request, "urlopen", raise_500)
    monkeypatch.setattr("sys.argv", ["fetch_bootstrap_cache.py", str(dest)])

    fbc.main()

    assert not dest.exists()
    assert "::warning::" in capsys.readouterr().out


def test_response_missing_content_writes_empty_file(fbc, tmp_path, monkeypatch):
    # base64.b64decode("") -> b"" -> the code writes an empty file rather than
    # skipping the write; asserting the actual behaviour, not a preference.
    dest = tmp_path / "cache.yml"
    monkeypatch.setattr(fbc.urllib.request, "urlopen", lambda req, timeout=15: _Resp({}))
    monkeypatch.setattr("sys.argv", ["fetch_bootstrap_cache.py", str(dest)])

    fbc.main()

    assert dest.exists()
    assert dest.read_text() == ""


def test_stale_destination_is_removed_even_when_fetch_404s(fbc, tmp_path, monkeypatch):
    # Fix 3: a fixed temp path shared across stacks/environments in one job must
    # never leak a previous stack's cache when this fetch misses.
    dest = tmp_path / "cache.yml"
    dest.write_text("stack_name: stale-stack\n")

    def raise_404(req, timeout=15):
        raise _http_error(404)

    monkeypatch.setattr(fbc.urllib.request, "urlopen", raise_404)
    monkeypatch.setattr("sys.argv", ["fetch_bootstrap_cache.py", str(dest)])

    fbc.main()

    assert not dest.exists()
