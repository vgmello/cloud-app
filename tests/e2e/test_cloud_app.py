"""End-to-end scenarios for .github/actions/cloud-app.

These run the composite action as a real workflow under act. The assertions are
about the seam the unit tests cannot reach: which steps ran, in what order,
under which identity, and what the cloud looks like afterwards.
"""

import pytest

STACK = "orders-api"
ENV = "dev"
RESOURCE_GROUP = f"rg-{STACK}-{ENV}"
CONTAINER_APP = f"ca-{STACK}-{ENV}"
KEYVAULT = f"kv-{STACK}-{ENV}"
STATE_CONTAINER = f"{STACK}-{ENV}"
STATE_KEY = f"{STACK}/{ENV}.tfstate"

# What the fake GitHub API hands back as the bootstrap result.
PLAN_ID = "00000000-0000-0000-0000-0000000000p1"
APPLY_ID = "00000000-0000-0000-0000-0000000000a1"


def bootstrap_cache(fingerprint):
    return (
        f"stack_name: {STACK}\n"
        f"environment: {ENV}\n"
        f"resource_group: {RESOURCE_GROUP}\n"
        f"plan_client_id: {PLAN_ID}\n"
        f"apply_client_id: {APPLY_ID}\n"
        f"fingerprint: {fingerprint}\n"
        "updated_at: 2026-07-26T00:00:00Z\n"
    )


def test_first_deploy_creates_the_stack_and_its_state(workspace):
    """No state blob means first deploy: the action must bootstrap, apply the
    key vault before syncing secrets, run the full apply, and leave Terraform
    state behind."""
    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    outputs = workspace.outputs()
    assert outputs["name"] == STACK
    assert outputs["applied"] == "true"
    assert outputs["resource_group"] == RESOURCE_GROUP
    assert outputs["summary"] == f"applied {ENV}"

    graph = workspace.graph()
    assert RESOURCE_GROUP in graph["resource_groups"]
    assert CONTAINER_APP in graph["containerapps"]

    # The key vault is applied on its own first, so the secret sync has
    # somewhere to write. Both syncs must have happened, in that order.
    terraform = workspace.terraform_commands()
    assert terraform.count("apply@azure") == 2, terraform

    secrets = graph["keyvaults"][KEYVAULT]["secrets"]
    assert secrets["stripe-key"] == "sk_test_e2e"
    assert secrets["sendgrid-api-key"] == "sg_test_e2e"
    assert f"{STACK}-secrets-sentinel" in secrets

    # The state blob is real, in real Azurite.
    from fakecloud import blob
    assert blob.blob_exists(STATE_CONTAINER, STATE_KEY)


def test_first_deploy_dispatches_the_bootstrap(workspace):
    """With no cache entry, phase 1 goes over the wire to the control repo."""
    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    dispatches = workspace.dispatches()
    assert len(dispatches) == 1, dispatches
    assert dispatches[0]["workflow"] == "bootstrap.yml"
    assert dispatches[0]["inputs"]["stack_name"] == STACK
    assert dispatches[0]["inputs"]["env"] == ENV

    # Least privilege on the dispatch token.
    request = workspace.app_token_requests()[0]
    assert request["permission_actions"] == "write"
    assert request["permission_contents"] == "read"
    assert request["repositories"] == "cloud-app"


def test_cache_hit_skips_the_bootstrap_dispatch(workspace):
    """A cached bootstrap whose fingerprint matches the shipped one must serve
    phase 1 outright -- that is the whole point of the cache."""
    fingerprint = (workspace.path / "bootstrap.fingerprint").read_text().strip()
    workspace.fakegh(contents={
        f"registries/{ENV}/{STACK}.bootstrap.yml": bootstrap_cache(fingerprint),
    })

    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    assert workspace.dispatches() == []
    assert workspace.outputs()["resource_group"] == RESOURCE_GROUP
    assert "phase 1 via cache" in workspace.log


def test_stale_cache_fingerprint_forces_a_dispatch(workspace):
    workspace.fakegh(contents={
        f"registries/{ENV}/{STACK}.bootstrap.yml": bootstrap_cache("stale-fingerprint"),
    })

    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    assert len(workspace.dispatches()) == 1


@pytest.mark.workspace(commits=["cloud-app.yml", None])
def test_unchanged_manifest_rotates_instead_of_applying(workspace):
    """The rotate lane: state exists and the manifest did not move, so
    Terraform is skipped entirely and the new image is rolled straight onto the
    running container app."""
    workspace.seed_state_blob(STATE_CONTAINER, STATE_KEY)
    workspace.seed_graph({
        "resource_groups": {RESOURCE_GROUP: {"location": "eastus2"}},
        "keyvaults": {KEYVAULT: {"secrets": {}, "network_rules": []}},
        "containerapps": {CONTAINER_APP: {
            "latestRevisionName": f"{CONTAINER_APP}--r1",
            "revision_count": 1,
            "prov": "Provisioned",
            "running": "Running",
            "containers": {"main": "acrplatformdev.azurecr.io/orders-api/api-main:old"},
        }},
        "functionapps": {},
        "identities": {},
    })

    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    outputs = workspace.outputs()
    assert outputs["manifest_changed"] == "false"
    assert outputs["applied"] == "false"

    assert "plan@azure" not in workspace.terraform_commands()
    assert "containerapp update" in workspace.az_commands()

    rotated = workspace.graph()["containerapps"][CONTAINER_APP]["containers"]["main"]
    assert rotated.endswith(":" + _sha(workspace))


@pytest.mark.workspace(commits=["cloud-app.yml", None])
def test_always_run_terraform_overrides_the_rotate_lane(workspace):
    workspace.seed_state_blob(STATE_CONTAINER, STATE_KEY)

    workspace.act(
        "deploy.yml", {"env": ENV, "always_run_terraform": "true"}, expect_success=True
    )

    assert workspace.outputs()["applied"] == "true"
    assert "apply@azure" in workspace.terraform_commands()


def test_plan_only_never_applies_or_writes_secrets(workspace):
    """A pull-request run must be read-only: plan identity, no apply, no secret
    sync, no image push."""
    workspace.act("deploy.yml", {"env": ENV, "plan_only": "true"}, expect_success=True)

    outputs = workspace.outputs()
    assert outputs["summary"] == f"plan only ({ENV})"

    terraform = workspace.terraform_commands()
    assert "plan@azure" in terraform
    assert "apply@azure" not in terraform

    assert "keyvault secret set" not in workspace.az_commands()
    assert [c for c in workspace.docker_calls() if c["command"][:1] == ["push"]] == []

    # Exactly one login, under the Reader-scoped plan identity.
    logins = workspace.azure_logins()
    assert [login["client_id"] for login in logins] == [PLAN_ID], logins


@pytest.mark.workspace(commits=["cloud-app.customtf.yml", None])
def test_caller_terraform_forces_an_apply_and_is_staged(workspace):
    """Caller .tf files cannot be diffed, so their presence must defeat the
    manifest-unchanged skip -- otherwise a change there would never apply."""
    workspace.seed_state_blob(STATE_CONTAINER, STATE_KEY)

    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    assert workspace.outputs()["manifest_changed"] == "false"
    assert workspace.outputs()["applied"] == "true"
    assert "caller .tf changes cannot be diffed" in workspace.log

    custom = workspace.path / "terraform" / "azure" / "custom"
    assert (custom / "queue.tf").exists()
    assert (custom / "_providers.g.tf").exists()
    assert "hashicorp/random" in (custom / "_providers.g.tf").read_text()


@pytest.mark.workspace(commits=["cloud-app.codefn.yml"])
def test_code_functions_ship_a_zip_after_apply(workspace):
    """Code functions deploy through the SCM endpoint after Terraform, and the
    package must be non-empty for both the zip-mode and builder-mode paths."""
    workspace.act("deploy.yml", {"env": ENV}, expect_success=True)

    assert workspace.outputs()["code_functions"] == "true"
    assert "functionapp deployment source config-zip" in workspace.az_commands()

    functions = workspace.graph()["functionapps"]
    for key in ("cron", "worker"):
        name = f"func-{STACK}-{key}-{ENV}"
        assert name in functions, sorted(functions)
        assert functions[name]["package"]["bytes"] > 0


def test_verify_fails_a_crash_looping_revision(workspace):
    """The reality check: a revision that never comes up must fail the run and
    name the resource, not report success."""
    workspace.scenario(revision_state={
        CONTAINER_APP: {"prov": "Provisioned", "running": "Failed"},
    })

    workspace.act("deploy.yml", {"env": ENV, "verify_timeout": "5"}, expect_success=False)

    assert CONTAINER_APP in workspace.log
    assert "runningState=Failed" in workspace.log


def test_verify_can_be_switched_off(workspace):
    workspace.scenario(revision_state={
        CONTAINER_APP: {"prov": "Provisioned", "running": "Failed"},
    })

    workspace.act(
        "deploy.yml", {"env": ENV, "verify_deploy": "false"}, expect_success=True
    )

    assert "containerapp revision show" not in workspace.az_commands()


def test_undeclared_environment_fails_before_touching_the_cloud(workspace):
    workspace.act("deploy.yml", {"env": "staging"}, expect_success=False)

    assert "is not declared in the manifest" in workspace.log
    assert workspace.dispatches() == []
    assert workspace.terraform_calls() == []


def _sha(workspace):
    """The commit the run built from; image tags are suffixed with it."""
    import subprocess
    return subprocess.run(
        ["git", "-C", str(workspace.path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
