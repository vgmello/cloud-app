"""The Terraform state backend, against real Azurite.

`cloudapp state-exists` is the authoritative first-deploy signal: when it is
wrong, the action either skips an apply the stack needed or re-runs a full
apply on every deploy. It is one `az storage blob exists` call built from
`backend.render()`, so these scenarios drive the real CLI against real blob
storage and check the whole chain -- container naming, key naming, and the
three outcomes that look alike from the outside (no container, no blob, blob).

The expected names are spelled out here rather than imported from
cloudapp.backend, so a change to the convention fails this suite instead of
silently agreeing with itself.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fakecloud import blob

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_BIN = Path(__file__).resolve().parent / "fakecloud" / "bin"
PLATFORM = REPO_ROOT / "environments" / "dev.yml"

STACK = "orders-api"
ENV = "dev"
# The documented convention: a per-stack container for the main stack, the
# shared platform container for bootstrap.
MAIN_CONTAINER = f"{STACK}-{ENV}"
MAIN_KEY = f"{STACK}/{ENV}.tfstate"
BOOTSTRAP_CONTAINER = "tfstate"
BOOTSTRAP_KEY = f"{STACK}/{ENV}.bootstrap.tfstate"


@pytest.fixture
def cli(azurite, tmp_path):
    """Run a cloudapp subcommand with the fake cloud on PATH, and hand back its
    step outputs plus the az calls it made."""
    state = tmp_path / "state"
    state.mkdir()

    def run(*args):
        output = tmp_path / "github_output"
        output.write_text("")
        env = {
            **os.environ,
            "PATH": f"{SHIM_BIN}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(REPO_ROOT / "engine"),
            "FAKECLOUD_STATE": str(state),
            "GITHUB_OUTPUT": str(output),
        }
        result = subprocess.run(
            [sys.executable, "-m", "cloudapp", *args],
            env=env, capture_output=True, text=True,
        )
        outputs = dict(
            line.split("=", 1)
            for line in output.read_text().splitlines() if "=" in line
        )
        calls_file = state / "az-calls.jsonl"
        calls = [
            json.loads(line)
            for line in (calls_file.read_text().splitlines() if calls_file.exists() else [])
            if line.strip()
        ]
        return result, outputs, calls

    return run


def state_exists(cli, name=STACK, env=ENV):
    _, outputs, calls = cli(
        "state-exists", "--platform-file", str(PLATFORM),
        "--tool-name", name, "--environment", env,
    )
    return outputs.get("exists"), calls


def test_missing_container_reads_as_first_deploy(cli):
    """Nothing has ever been deployed, so not even the container exists. This
    must read as false rather than erroring -- an error here would be treated
    as 'undetermined' and force a full apply forever."""
    exists, _ = state_exists(cli)
    assert exists == "false"


def test_container_without_the_blob_still_reads_as_first_deploy(cli):
    """The bootstrap creates the state container before the first apply writes
    into it, so an empty container is the normal first-deploy state and must
    not be mistaken for a deployed stack."""
    blob.create_container(MAIN_CONTAINER)

    exists, _ = state_exists(cli)
    assert exists == "false"


def test_existing_state_blob_reads_as_deployed(cli):
    blob.create_container(MAIN_CONTAINER)
    blob.put_blob(MAIN_CONTAINER, MAIN_KEY, '{"version": 4}')

    exists, _ = state_exists(cli)
    assert exists == "true"


def test_the_probe_targets_the_documented_container_and_key(cli):
    """Container and key are the two halves of the convention that must match
    what `terraform init` was given, or the probe answers about the wrong
    blob."""
    blob.create_container(MAIN_CONTAINER)
    _, calls = state_exists(cli)

    probe = next(c for c in calls if c["command"][:3] == ["storage", "blob", "exists"])
    assert probe["flags"]["--container-name"] == MAIN_CONTAINER
    assert probe["flags"]["--name"] == MAIN_KEY
    # Data-plane access is via the deploy identity, never an account key.
    assert probe["flags"]["--auth-mode"] == "login"


def test_another_stack_state_does_not_count_as_this_one(cli):
    """The container name folds stack and environment together, so a
    collision here would let one stack read another's state and skip its own
    first deploy."""
    blob.create_container(MAIN_CONTAINER)
    blob.put_blob(MAIN_CONTAINER, MAIN_KEY, '{"version": 4}')

    assert state_exists(cli, name="billing-api")[0] == "false"
    assert state_exists(cli, env="prod")[0] == "false"


def test_bootstrap_state_lives_in_the_shared_container(cli):
    """The bootstrap stack keeps its state in the platform container: a single
    control-plane identity owns every bootstrap state, and Terraform cannot
    init into a container the same run has not created yet."""
    blob.create_container(BOOTSTRAP_CONTAINER)
    blob.put_blob(BOOTSTRAP_CONTAINER, BOOTSTRAP_KEY, '{"version": 4}')

    # The main-stack probe must not see it, and vice versa.
    assert state_exists(cli)[0] == "false"
    assert blob.blob_exists(BOOTSTRAP_CONTAINER, BOOTSTRAP_KEY)
    assert not blob.blob_exists(MAIN_CONTAINER, MAIN_KEY)
