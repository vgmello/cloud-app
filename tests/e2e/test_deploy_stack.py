"""End-to-end scenarios for .github/actions/deploy-stack (the control side).

The authorization gate is the security boundary of this system: it decides
which caller repository is allowed to deploy a given stack name. These
scenarios run it for real, against a real git remote, so a lock that fails to
persist is a failure rather than a swallowed warning.
"""

import pytest
import yaml

STACK = "orders-api"
ENV = "dev"
OWNER = "vgmello"
CALLER = "orders-app"
CENTRAL = "central-workspace"
LOCK_PATH = f"registries/{ENV}/{STACK}.yml"
CACHE_PATH = f"registries/{ENV}/{STACK}.bootstrap.yml"

# Every deploy-stack scenario runs in the control repo, not a caller repo.
pytestmark = pytest.mark.workspace(repository="cloud-app")


def seed_lock(workspace, allowed_repos):
    """Pre-register the stack in the central repo the run will check out."""
    path = workspace.path / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "stack_name": STACK,
        "environment": ENV,
        "allowed_repos": allowed_repos,
        "registered_at": "2026-07-01 00:00:00Z",
    }, default_flow_style=False))


def test_first_caller_claims_the_stack_and_the_lock_is_pushed(workspace):
    """Trust on first use: an unregistered stack name is claimed by the first
    caller, and the claim has to reach the remote or the run must fail --
    persist_lock is deliberately fail-closed."""
    workspace.act("bootstrap.yml", expect_success=True)

    lock = yaml.safe_load((workspace.path / CENTRAL / LOCK_PATH).read_text())
    assert lock["stack_name"] == STACK
    assert lock["environment"] == ENV
    assert lock["allowed_repos"] == [f"{OWNER}/{CALLER}"]

    # Pushed, not just written: read it back off the bare remote.
    pushed = workspace.remote_file(CENTRAL, LOCK_PATH)
    assert pushed is not None, "the lock was never pushed to origin"
    assert yaml.safe_load(pushed)["allowed_repos"] == [f"{OWNER}/{CALLER}"]


def test_registered_owner_is_authorized(workspace):
    seed_lock(workspace, [f"{OWNER}/{CALLER}"])

    workspace.act("bootstrap.yml", expect_success=True)

    assert f"Repository '{OWNER}/{CALLER}' authorized" in workspace.log


def test_a_different_repo_cannot_deploy_a_claimed_stack(workspace):
    """The gate itself. A repo that does not own the stack must be refused
    before anything is created."""
    seed_lock(workspace, [f"{OWNER}/someone-else"])

    workspace.act("bootstrap.yml", expect_success=False)

    assert "SECURITY VIOLATION" in workspace.log
    assert f"'{OWNER}/{CALLER}' is NOT authorized" in workspace.log
    # Refused before the bootstrap identity ever logged in and before
    # anything was planned. (`terraform output` still runs afterwards: the
    # outputs step is `if: always()` so the caller always gets a status.)
    assert workspace.azure_logins() == []
    assert not _planned_or_applied(workspace)


def test_manifest_name_mismatch_fails_closed(workspace):
    """The dispatched stack name and the manifest's own name must agree;
    otherwise a caller could deploy under a name it does not own."""
    workspace.act("bootstrap.yml", {"stack_name": "not-orders-api"}, expect_success=False)

    assert "MISMATCH DETECTED" in workspace.log
    assert not _planned_or_applied(workspace)


def test_bootstrap_creates_the_rg_and_both_identities(workspace):
    workspace.act("bootstrap.yml", expect_success=True)

    graph = workspace.graph()
    assert f"rg-{STACK}-{ENV}" in graph["resource_groups"]
    roles = {entry["role"] for entry in graph["identities"].values()}
    assert roles == {"plan", "apply"}


def test_bootstrap_publishes_outputs_for_the_caller(workspace):
    """The caller learns the RG and both client ids only through this
    artifact, so it must carry all three even though the caller never sees the
    Terraform state."""
    workspace.act("bootstrap.yml", expect_success=True)

    results = workspace.artifact("deployment-results.json")
    assert results is not None, "no deployment-outputs artifact was uploaded"
    assert results["stack_name"] == STACK
    assert results["environment"] == ENV
    assert results["resource_group"] == f"rg-{STACK}-{ENV}"
    assert results["plan_client_id"]
    assert results["apply_client_id"]
    assert results["plan_client_id"] != results["apply_client_id"]
    assert results["status"] == "success"


def test_bootstrap_caches_its_result_for_the_next_deploy(workspace):
    """The cache the caller-side action reads. Its fingerprint has to be the
    committed one, or every later deploy re-bootstraps."""
    workspace.act("bootstrap.yml", expect_success=True)

    cached = workspace.remote_file(CENTRAL, CACHE_PATH)
    assert cached is not None, "the bootstrap cache was never pushed"
    entry = yaml.safe_load(cached)
    assert entry["stack_name"] == STACK
    assert entry["environment"] == ENV
    assert entry["resource_group"] == f"rg-{STACK}-{ENV}"
    assert entry["fingerprint"] == (workspace.path / "bootstrap.fingerprint").read_text().strip()


def test_plan_only_bootstrap_creates_nothing(workspace):
    workspace.act("bootstrap.yml", {"plan_only": "true"}, expect_success=True)

    assert workspace.graph().get("resource_groups", {}) == {}
    assert "apply" not in _terraform_actions(workspace)


def _terraform_actions(workspace):
    return [call["command"][0] for call in workspace.terraform_calls() if call["command"]]


def _planned_or_applied(workspace):
    """Whether the run got as far as changing anything. `terraform output` does
    not count -- the outputs step runs unconditionally so a refused caller
    still gets a status back."""
    return bool({"plan", "apply"} & set(_terraform_actions(workspace)))
