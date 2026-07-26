"""Fixtures for the workflow e2e suite.

Each scenario gets a scratch workspace that looks like a real caller repo with
the platform installed into it: the platform tree (engine, actions, terraform,
environments) plus the caller fixture's manifest and Dockerfile at the root.
act runs a harness workflow there with `--bind`, so the container sees the
workspace at the same absolute path as the host and everything the run writes
is readable here afterwards.

Azurite and the fake GitHub API run as containers on a shared docker network,
recreated per scenario so no state leaks between them. That serialises the
suite -- the container names are fixed because the harness workflows reference
them by hostname -- so do not run these tests with -n/xdist.
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parents[1]
WORK_DIR = E2E_DIR / ".work"

NETWORK = "cloudapp-e2e"
AZURITE = "cloudapp-e2e-azurite"
FAKEGH = "cloudapp-e2e-fakegh"
AZURITE_IMAGE = "mcr.microsoft.com/azure-storage/azurite:latest"
FAKEGH_IMAGE = "python:3.12-alpine"
ACT_IMAGE = "catthehacker/ubuntu:act-latest"

AZURITE_HOST_PORT = 10000
FAKEGH_HOST_PORT = 18080

ACT_TIMEOUT = 900

# Remote actions the composite actions call, mapped to the stub that replaces
# them. Keyed by owner/repo; the pinned ref is read out of the action files so a
# dependabot bump does not silently unhook a stub.
STUBS = {
    "actions/checkout": "checkout",
    "actions/create-github-app-token": "create-github-app-token",
    "azure/login": "azure-login",
    "actions/upload-artifact": "upload-artifact",
}

# Copied into every scratch workspace. Everything the composite actions reach
# for via `${{ github.action_path }}/../../..`.
PLATFORM_PATHS = [
    ".github", "engine", "environments", "terraform", "registries",
    "bootstrap.fingerprint", ".actrc",
]

RSYNC_EXCLUDES = [
    ".git", ".terraform", ".terraform.lock.hcl", "node_modules",
    "__pycache__", ".pytest_cache", ".ruff_cache", "htmlcov", ".coverage",
]

USES_RE = re.compile(r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)")


def _run(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)


def _docker(*args, check=True):
    result = _run(["docker", *args])
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed:\n{result.stderr}")
    return result


def _image_present(image):
    return _docker("image", "inspect", image, check=False).returncode == 0


# --- session setup ---

@pytest.fixture(scope="session", autouse=True)
def docker_available():
    if _run(["docker", "version"]).returncode != 0:
        pytest.skip("docker is not available; the e2e suite needs it")


@pytest.fixture(scope="session", autouse=True)
def images(docker_available):
    """Pull once per session. .actrc sets --pull=false so act never re-pulls."""
    for image in (AZURITE_IMAGE, FAKEGH_IMAGE, ACT_IMAGE):
        if not _image_present(image):
            result = _docker("pull", image, check=False)
            if result.returncode != 0:
                pytest.skip(f"could not pull {image}: {result.stderr.strip()[:200]}")


@pytest.fixture(scope="session", autouse=True)
def network(docker_available):
    _docker("network", "create", NETWORK, check=False)
    yield NETWORK


@pytest.fixture(scope="session")
def action_pins():
    """owner/repo -> pinned ref, read from the composite actions themselves."""
    pins = {}
    for action in (REPO_ROOT / ".github" / "actions").glob("*/action.yml"):
        for repo, ref in USES_RE.findall(action.read_text()):
            if repo in STUBS:
                pins.setdefault(repo, set()).add(ref)
    missing = set(STUBS) - set(pins)
    if missing:
        # Not a failure: an action may legitimately stop using one of these.
        print(f"e2e: no pinned ref found for {sorted(missing)}; stub not wired")
    return pins


# --- workspace construction ---

def _copy_platform(dest):
    dest.mkdir(parents=True, exist_ok=True)
    excludes = []
    for pattern in RSYNC_EXCLUDES:
        excludes += ["--exclude", pattern]
    for path in PLATFORM_PATHS:
        source = REPO_ROOT / path
        if not source.exists():
            continue
        if source.is_dir():
            _run(["rsync", "-a", *excludes, f"{source}/", str(dest / path) + "/"], check=True)
        else:
            shutil.copy2(source, dest / path)
    # The fake cloud itself, minus its own scratch state.
    _run([
        "rsync", "-a", *excludes, "--exclude", ".work", "--exclude", "state",
        f"{E2E_DIR}/", str(dest / "tests" / "e2e") + "/",
    ], check=True)
    # Harness workflows become real workflows inside the scratch workspace so
    # `uses: ./.github/actions/...` resolves the way it does in a caller repo.
    for workflow in (E2E_DIR / "workflows").glob("*.yml"):
        shutil.copy2(workflow, dest / ".github" / "workflows" / f"e2e-{workflow.name}")


def _git(ws, *args):
    result = _run(["git", "-C", str(ws), *args])
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {ws}:\n{result.stderr}")
    return result


def _init_git(ws, remote_url, commits):
    _git(ws, "init", "-q", "-b", "main")
    _git(ws, "config", "user.name", "e2e")
    _git(ws, "config", "user.email", "e2e@example.invalid")
    _git(ws, "config", "commit.gpgsign", "false")
    _git(ws, "remote", "add", "origin", remote_url)
    for index, manifest in enumerate(commits):
        if manifest is not None:
            shutil.copy2(E2E_DIR / "fixtures" / "caller" / manifest, ws / "cloud-app.yml")
        _git(ws, "add", "-A")
        if index == 0:
            _git(ws, "commit", "-q", "-m", f"e2e: initial ({manifest})")
        else:
            _git(ws, "commit", "-q", "--allow-empty", "-m", f"e2e: commit {index} ({manifest})")


class Workspace:
    """A scratch caller repo plus helpers to drive act against it and read back
    what the run did."""

    def __init__(self, path, pins):
        self.path = path
        self.pins = pins
        self.state = path / "tests" / "e2e" / "state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.last = None

    # -- seeding --

    def scenario(self, **knobs):
        """Arm the fake cloud: failed revisions, transient authz, secret-set
        failures. See tests/e2e/fakecloud/bin for the knobs each shim reads."""
        (self.state / "scenario.json").write_text(json.dumps(knobs, indent=2))

    def fakegh(self, **config):
        (self.state / "fakegh.json").write_text(json.dumps(config, indent=2))

    def checkout_map(self, mapping):
        (self.state / "checkout-map.json").write_text(json.dumps(mapping, indent=2))

    def seed_graph(self, graph):
        (self.state / "graph.json").write_text(json.dumps(graph, indent=2))

    def seed_state_blob(self, container, key, body='{"version": 4}'):
        """Make a stack look already-deployed, which is what flips the action
        off the first-deploy path."""
        from fakecloud import blob
        blob.create_container(container)
        blob.put_blob(container, key, body)

    # -- driving --

    def env_flags(self):
        """The environment the run needs, passed as `act --env`.

        It has to be --env, not workflow/job/step `env:`. act injects its own
        GITHUB_* values after workflow- and job-level env, so a GITHUB_API_URL
        set there loses; --env wins and, unlike step-level env, reaches the
        steps inside a composite action.
        """
        env = {
            # Redirects .github/scripts away from api.github.com. Both scripts
            # read GITHUB_API_URL, which GitHub sets on every real runner.
            "GITHUB_API_URL": f"http://{FAKEGH}:8080",
            "AZURITE_BLOB_URL": f"http://{AZURITE}:10000",
            "FAKECLOUD_STATE": str(self.path / "tests" / "e2e" / "state"),
            # The act runner image ships a Debian-managed Python, so PEP 668
            # rejects the action's `pip install`. GitHub's hosted runners do
            # not, so this papers over an image difference, not a product bug.
            "PIP_BREAK_SYSTEM_PACKAGES": "1",
        }
        flags = []
        for key, value in env.items():
            flags += ["--env", f"{key}={value}"]
        return flags

    def act(self, workflow, inputs=None, repository="orders-app", owner="vgmello",
            event_name="workflow_dispatch", expect_success=None):
        event = {
            "inputs": inputs or {},
            "ref": "refs/heads/main",
            "repository": {
                "name": repository,
                "full_name": f"{owner}/{repository}",
                "owner": {"login": owner},
                "default_branch": "main",
            },
        }
        (self.path / "event.json").write_text(json.dumps(event, indent=2))

        local_repos = []
        for repo, refs in self.pins.items():
            stub = self.path / "tests" / "e2e" / "stubs" / STUBS[repo]
            for ref in refs:
                local_repos += ["--local-repository", f"{repo}@{ref}={stub}"]

        cmd = [
            "gh", "act", event_name,
            "-C", str(self.path),
            "-W", str(self.path / ".github" / "workflows" / f"e2e-{workflow}"),
            "--eventpath", str(self.path / "event.json"),
            "--network", NETWORK,
            *self.env_flags(),
            *local_repos,
        ]
        self.last = _run(cmd, cwd=str(self.path), timeout=ACT_TIMEOUT)
        (self.state / "act.log").write_text(
            f"$ {' '.join(cmd)}\n\n--- stdout ---\n{self.last.stdout}\n--- stderr ---\n{self.last.stderr}"
        )
        if expect_success is True:
            assert self.last.returncode == 0, self.tail()
        elif expect_success is False:
            assert self.last.returncode != 0, self.tail()
        return self.last

    def tail(self, lines=60):
        if self.last is None:
            return "(act has not run)"
        combined = (self.last.stdout or "") + "\n" + (self.last.stderr or "")
        return "\n".join(combined.splitlines()[-lines:])

    @property
    def log(self):
        if self.last is None:
            return ""
        return (self.last.stdout or "") + "\n" + (self.last.stderr or "")

    # -- reading back --

    def _json(self, name, default=None):
        path = self.state / name
        if not path.exists():
            return default
        return json.loads(path.read_text())

    def _jsonl(self, name):
        path = self.state / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def graph(self):
        return self._json("graph.json", {})

    def outputs(self):
        return self._json("action-outputs.json", {})

    def az_calls(self):
        return self._jsonl("az-calls.jsonl")

    def terraform_calls(self):
        return self._jsonl("terraform-calls.jsonl")

    def docker_calls(self):
        return self._jsonl("docker-calls.jsonl")

    def dispatches(self):
        return self._jsonl("dispatches.jsonl")

    def azure_logins(self):
        return self._jsonl("azure-logins.jsonl")

    def app_token_requests(self):
        return self._jsonl("app-token-requests.jsonl")

    def artifact(self, name, filename):
        path = self.state / "artifacts" / name / filename
        return json.loads(path.read_text()) if path.exists() else None

    def az_commands(self):
        return [" ".join(call["command"]) for call in self.az_calls()]

    def terraform_commands(self):
        return [
            f"{call['command'][0] if call['command'] else ''}@{Path(call['chdir']).name}"
            for call in self.terraform_calls()
        ]


# --- services ---

def _start_azurite():
    _docker("rm", "-f", AZURITE, check=False)
    _docker(
        "run", "-d", "--name", AZURITE, "--network", NETWORK,
        "-p", f"{AZURITE_HOST_PORT}:10000", AZURITE_IMAGE,
        "azurite-blob", "--blobHost", "0.0.0.0", "--skipApiVersionCheck",
    )
    # Any HTTP response means it is listening; an unauthenticated list is a 403.
    def responding():
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{AZURITE_HOST_PORT}/devstoreaccount1?comp=list", timeout=2
            )
        except urllib.error.HTTPError:
            return True
        return True

    _wait_for(responding, "azurite")


def _start_fakegh(ws):
    _docker("rm", "-f", FAKEGH, check=False)
    _docker(
        "run", "-d", "--name", FAKEGH, "--network", NETWORK,
        "-p", f"{FAKEGH_HOST_PORT}:8080",
        "-e", "FAKEGH_STATE=/state",
        "-v", f"{ws.path / 'tests' / 'e2e' / 'fakegh'}:/app:ro",
        "-v", f"{ws.state}:/state",
        FAKEGH_IMAGE, "python3", "/app/server.py",
    )
    _wait_for(
        lambda: "listening" in _docker("logs", FAKEGH, check=False).stdout
        + _docker("logs", FAKEGH, check=False).stderr,
        "fakegh",
    )


def _wait_for(predicate, what, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:  # noqa: BLE001 - any failure is just "not ready yet"
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{what} did not become ready within {timeout}s")


# --- the per-scenario fixture ---

@pytest.fixture
def workspace(request, action_pins, network, images):
    """Build a scratch workspace and bring the fake cloud up around it.

    Parametrise with `@pytest.mark.workspace(commits=[...], remote=...)`.
    `commits` is a list of caller manifest fixture names, one per git commit;
    None repeats the previous manifest (an empty commit), which is what the
    manifest-unchanged scenarios need.
    """
    marker = request.node.get_closest_marker("workspace")
    options = dict(marker.kwargs) if marker else {}
    commits = options.get("commits", ["cloud-app.yml"])
    owner = options.get("owner", "vgmello")
    repository = options.get("repository", "orders-app")

    name = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)
    path = WORK_DIR / name
    if path.exists():
        shutil.rmtree(path)

    _copy_platform(path)
    for item in (E2E_DIR / "fixtures" / "caller").iterdir():
        if item.name.startswith("cloud-app.") or item.name == "README.md":
            continue
        target = path / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    _init_git(path, f"https://github.com/{owner}/{repository}.git", commits)

    ws = Workspace(path, action_pins)
    # Default wiring; scenarios override before calling .act().
    ws.checkout_map({
        "central-workspace": str(path),
        "caller-workspace": str(E2E_DIR / "fixtures" / "caller"),
    })
    ws.fakegh()
    ws.scenario()

    os.environ.setdefault("AZURITE_BLOB_URL", f"http://127.0.0.1:{AZURITE_HOST_PORT}")
    _start_azurite()
    _start_fakegh(ws)
    try:
        yield ws
    finally:
        _docker("rm", "-f", FAKEGH, check=False)
        _docker("rm", "-f", AZURITE, check=False)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "workspace(commits=..., owner=..., repository=...): scratch workspace options"
    )
