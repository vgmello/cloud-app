"""Smoke tests over the repository's real workflows.

Not deploy scenarios -- these catch the class of breakage that only shows up
once GitHub parses a workflow: an unresolvable action pin, a malformed
expression, a job that references a step id that no longer exists. `act
--dryrun` walks every job and step without executing them, so it is cheap
enough to run on every change and catches those before a push does.

Executing the workflows for real is deliberately opt-in (E2E_RUN_WORKFLOWS=1):
the ci job downloads actionlint over the network and terraform pulls providers,
which makes it slow and dependent on things outside this repo.
"""

import os
import subprocess
from pathlib import Path

import pytest
from conftest import ACT_IMAGE, CONTAINER_ARCH

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Each workflow paired with an event that actually triggers it.
WORKFLOWS = [
    ("ci.yml", "push"),
    ("site.yml", "push"),
    ("release.yml", "workflow_dispatch"),
    ("bootstrap.yml", "workflow_dispatch"),
]


def act(*args, timeout=600):
    return subprocess.run(
        ["gh", "act", *args,
         "-C", str(REPO_ROOT),
         "--container-architecture", CONTAINER_ARCH,
         "-P", f"ubuntu-latest={ACT_IMAGE}",
         "--pull=false"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
    )


@pytest.mark.parametrize("workflow,event", WORKFLOWS)
def test_workflow_resolves_every_job_and_step(workflow, event, docker_available):
    path = WORKFLOW_DIR / workflow
    assert path.exists(), f"{workflow} is gone; update WORKFLOWS in this file"

    result = act(event, "-n", "-W", str(path))

    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "Job succeeded" in result.stdout


def test_every_workflow_is_covered_by_a_smoke_test():
    """A new workflow should not be able to arrive untested."""
    on_disk = {p.name for p in WORKFLOW_DIR.glob("*.yml")}
    covered = {name for name, _ in WORKFLOWS}
    # e2e.yml runs this suite; smoke-testing it from inside itself would be
    # circular, so it is the one exemption.
    assert on_disk - covered - {"e2e.yml"} == set()


@pytest.mark.skipif(
    os.environ.get("E2E_RUN_WORKFLOWS") != "1",
    reason="set E2E_RUN_WORKFLOWS=1 to actually execute ci.yml (needs network)",
)
def test_ci_test_job_passes_under_act(docker_available):
    """The full lint + unit-test job, executed rather than walked."""
    result = act("push", "-W", str(WORKFLOW_DIR / "ci.yml"), "-j", "test", timeout=1800)
    assert result.returncode == 0, result.stdout[-6000:]
