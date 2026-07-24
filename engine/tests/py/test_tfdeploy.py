import json

import pytest

from cloudapp import manifest, tfdeploy
from conftest import ENVDIR, FIXTURES, FakeResult, FakeRunner


def tool(fixture="minimal", env="dev"):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{fixture}.yml")
    return tools[env]


def test_prepare_passes_through_supplied_tags():
    lines, tags, runner_ip = tfdeploy.prepare(
        ENVDIR / "dev.yml", tool(), "orders-api", "dev",
        '{"main/main": "acr/x:1"}', plan_only=False, fetch_ip=lambda: "9.9.9.9",
    )
    assert lines[3] == "key=orders-api/dev.tfstate"
    assert tags == {"main/main": "acr/x:1"}
    assert runner_ip == "9.9.9.9"  # dev.yml is public-allowlist


def test_prepare_plan_only_generates_placeholder_tags():
    _, tags, _ = tfdeploy.prepare(
        ENVDIR / "dev.yml", tool(), "orders-api", "dev",
        "{}", plan_only=True, fetch_ip=lambda: None,
    )
    assert tags == {"main/main": "acrplatformdev.azurecr.io/orders-api/main-main:plan-placeholder"}


def deploy(run, plan_only=False, targets=(), runner_ip=None, sleeps=None):
    return tfdeploy.deploy(
        "terraform", "tfvars.json", ["key=a/b.tfstate"], {"main/main": "acr/x:1"},
        runner_ip, "dev", plan_only, targets=targets, run=run,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_plan_only_never_applies():
    run = FakeRunner()
    assert deploy(run, plan_only=True) == "plan only (dev)"
    assert run.commands("terraform", "-chdir=terraform", "apply") == []
    (init,) = run.commands("terraform", "-chdir=terraform", "init")
    assert "-backend-config=key=a/b.tfstate" in init


def test_apply_passes_image_tags_and_runner_ip_and_targets():
    run = FakeRunner()
    assert deploy(run, runner_ip="1.2.3.4", targets=("module.keyvault",)) == "applied dev"
    (plan,) = run.commands("terraform", "-chdir=terraform", "plan")
    assert "image_tags=" + json.dumps({"main/main": "acr/x:1"}, separators=(",", ":")) in " ".join(plan)
    assert "runner_ip=1.2.3.4" in " ".join(plan)
    assert "-target=module.keyvault" in plan
    assert len(run.commands("terraform", "-chdir=terraform", "apply")) == 1


def test_apply_retries_once_after_transient_authz_failure():
    attempts = []

    def apply_result(cmd):
        attempts.append(cmd)
        # first attempt: a transient RBAC-propagation error; second: success
        return FakeResult(1, stderr="AuthorizationFailed: not authorized") if len(attempts) == 1 else FakeResult(0)

    sleeps = []
    run = FakeRunner([(("terraform", "-chdir=terraform", "apply"), apply_result)])
    assert deploy(run, sleeps=sleeps) == "applied dev"
    assert len(attempts) == 2
    assert sleeps == [30]
    assert len(run.commands("terraform", "-chdir=terraform", "plan")) == 2


def test_apply_non_transient_error_fails_immediately():
    run = FakeRunner([
        (("terraform", "-chdir=terraform", "apply"), FakeResult(1, stderr="Error: quota exceeded")),
    ])
    with pytest.raises(tfdeploy.DeployError):
        deploy(run)
    # no retry, no second plan
    assert len(run.commands("terraform", "-chdir=terraform", "apply")) == 1
    assert len(run.commands("terraform", "-chdir=terraform", "plan")) == 1


def test_prepare_bootstrap_stack_uses_bootstrap_state_key_and_skips_runner_ip():
    lines, _, runner_ip = tfdeploy.prepare(
        ENVDIR / "dev.yml", tool(), "orders-api", "dev",
        "{}", plan_only=False, stack="bootstrap", fetch_ip=lambda: "9.9.9.9",
    )
    assert any(line == "key=orders-api/dev.bootstrap.tfstate" for line in lines)
    # dev.yml is public-allowlist, but bootstrap must never allowlist the runner
    # (the bootstrap module declares no runner_ip variable).
    assert runner_ip is None


def test_bootstrap_deploy_omits_image_tags_and_runner_ip():
    run = FakeRunner()
    summary = tfdeploy.deploy(
        "terraform/azure/bootstrap", "tfvars.json", ["key=a/b.bootstrap.tfstate"],
        {}, None, "dev", plan_only=False, stack="bootstrap", run=run, sleep=lambda s: None,
    )
    assert summary == "applied dev"
    (plan,) = run.commands("terraform", "-chdir=terraform/azure/bootstrap", "plan")
    joined = " ".join(plan)
    assert "image_tags=" not in joined
    assert "runner_ip=" not in joined
    assert "-var-file=" in joined
