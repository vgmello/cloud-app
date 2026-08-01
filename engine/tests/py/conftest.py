import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[2]
sys.path.insert(0, str(REPO))

FIXTURES = REPO / "tests" / "fixtures" / "manifests"
GOLDEN = REPO / "tests" / "golden"
ENVDIR = REPO / "tests" / "fixtures" / "environments"


@pytest.fixture
def repo():
    return REPO


@pytest.fixture(autouse=True)
def pin_ci_provider(monkeypatch):
    """The suite asserts GitHub-shaped output (``::error::``, GITHUB_OUTPUT).
    Before the ci package existed, gha.py made that shape unconditional, so
    tests never had to think about which provider was active. Pin the
    provider here so results stay deterministic regardless of whether the
    run happens to be inside a CI container — a suite that passes on a
    GitHub runner and fails on a laptop is worse than either outcome alone.

    Also scrub the real I/O targets these providers write to. Without this,
    running the suite on an actual GitHub (or GitLab) runner would pin the
    github provider and then have it append fixture data straight into the
    runner's real GITHUB_OUTPUT/GITHUB_STEP_SUMMARY (or CLOUDAPP_DOTENV),
    polluting the job's real outputs and summary. Tests that need one of
    these set it via their own ``monkeypatch`` afterward, so this scrub
    never shadows a deliberate test setting.

    Also pin via the ``CLOUDAPP_CI`` env var, not only ``ci.use()``: cli.main()
    resolves and re-pins the provider itself (from the real environment) on
    every invocation, so a CLI-path test would otherwise see its provider
    silently reset out from under the ``ci.use(github)`` pin the moment it
    called ``cli.main()``.
    """
    from cloudapp import ci
    from cloudapp.ci import github

    for var in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "CLOUDAPP_DOTENV"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLOUDAPP_CI", "github")
    ci.use(github)
    yield
    ci.use(None)


def load_manifest(name):
    return yaml.safe_load((FIXTURES / f"{name}.yml").read_text())


def load_golden(name):
    return json.loads((GOLDEN / f"{name}.json").read_text())


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Records commands; per-command results configured by prefix match."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or []

    def __call__(self, cmd, check=True, capture=False, cwd=None):
        self.calls.append(list(cmd))
        for prefix, result in self.results:
            if cmd[: len(prefix)] == list(prefix):
                if callable(result):
                    result = result(cmd)
                if check and result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, cmd, output=result.stdout, stderr=result.stderr
                    )
                return result
        return FakeResult()

    def commands(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]
