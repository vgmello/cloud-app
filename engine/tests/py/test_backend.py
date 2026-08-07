import pytest
from conftest import ENVDIR

from cloudapp import backend


def test_azurerm_main_backend_lines():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="main")
    assert lines == [
        "resource_group_name=rg-tfstate",
        "storage_account_name=sttfstatedev",
        "container_name=orders-api-dev",
        "key=orders-api/dev.tfstate",
        "use_oidc=true",
        "use_azuread_auth=true",
    ]


def test_azurerm_bootstrap_stack_uses_bootstrap_key():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="bootstrap")
    assert "key=orders-api/dev.bootstrap.tfstate" in lines


def test_s3_backend_lines(tmp_path):
    (tmp_path / "prod.yml").write_text(
        "state_backend:\n"
        "  type: s3\n"
        "  bucket: my-tfstate\n"
        "  region: us-east-1\n"
        "  dynamodb_table: tfstate-locks\n"
        "  role_arn: arn:aws:iam::123456789012:role/gha-tfstate\n"
    )
    lines = backend.render(tmp_path / "prod.yml", "orders-api", "prod", stack="main")
    assert lines == [
        "bucket=my-tfstate",
        "key=orders-api/prod.tfstate",
        "region=us-east-1",
        "dynamodb_table=tfstate-locks",
        "role_arn=arn:aws:iam::123456789012:role/gha-tfstate",
        "encrypt=true",
    ]


def test_backend_type_reports_configured_type():
    assert backend.backend_type(ENVDIR / "dev.yml") == "azurerm"


def test_unknown_backend_type_fails(tmp_path):
    (tmp_path / "x.yml").write_text("state_backend:\n  type: gcs\n")
    with pytest.raises(backend.BackendError, match="unknown state backend"):
        backend.render(tmp_path / "x.yml", "n", "dev")


def test_missing_azurerm_key_fails(tmp_path):
    (tmp_path / "x.yml").write_text("state_backend:\n  type: azurerm\n  resource_group: rg\n  container: tfstate\n")
    with pytest.raises(backend.BackendError, match="storage_account"):
        backend.render(tmp_path / "x.yml", "n", "dev")


def test_missing_state_backend_block_fails(tmp_path):
    (tmp_path / "x.yml").write_text("location: eastus2\n")
    with pytest.raises(backend.BackendError, match="state_backend.type"):
        backend.render(tmp_path / "x.yml", "n", "dev")


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_state_exists_true_probes_deterministic_key():
    calls = []

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        return _Result(0, "true\n")

    assert backend.state_exists(ENVDIR / "dev.yml", "orders-api", "dev", fake_run) is True
    assert "orders-api/dev.tfstate" in calls[0]
    assert "sttfstatedev" in calls[0]


def test_state_exists_false_when_blob_absent():
    def fake_run(cmd, check=False, capture=False):
        return _Result(0, "false\n")

    assert backend.state_exists(ENVDIR / "dev.yml", "orders-api", "dev", fake_run) is False


def test_state_exists_false_on_az_failure():
    def fake_run(cmd, check=False, capture=False):
        return _Result(1, "", "auth error")

    assert backend.state_exists(ENVDIR / "dev.yml", "orders-api", "dev", fake_run) is False


def test_state_exists_false_and_skips_az_for_non_azurerm(tmp_path):
    (tmp_path / "prod.yml").write_text(
        "state_backend:\n  type: s3\n  bucket: b\n  region: us-east-1\n"
        "  role_arn: arn:aws:iam::123456789012:role/x\n"
    )
    called = []

    def fake_run(cmd, check=False, capture=False):
        called.append(cmd)
        return _Result(0, "true\n")

    assert backend.state_exists(tmp_path / "prod.yml", "n", "prod", fake_run) is False
    assert called == []


def test_stack_container_bootstrap_uses_shared_container():
    sb = {"type": "azurerm", "container": "tfstate"}
    assert backend.stack_container(sb, "orders-api", "dev", "bootstrap") == "tfstate"


def test_stack_container_main_is_per_stack_and_env():
    sb = {"type": "azurerm", "container": "tfstate"}
    assert backend.stack_container(sb, "orders-api", "dev") == "orders-api-dev"


def test_stack_container_rejects_trailing_hyphen():
    # normalizing "orders-" would collide with "orders"
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="stack name"):
        backend.stack_container(sb, "orders-", "dev")


def test_stack_container_rejects_consecutive_hyphens():
    # normalizing "orders--api" would collide with "orders-api"
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="stack name"):
        backend.stack_container(sb, "orders--api", "dev")


def test_stack_container_is_injective_for_distinct_names():
    sb = {"type": "azurerm", "container": "tfstate"}
    assert backend.stack_container(sb, "orders", "dev") == "orders-dev"
    assert backend.stack_container(sb, "orders-api", "dev") == "orders-api-dev"
    # the names that would have collided are rejected outright
    for bad in ("orders-", "orders--api", "-orders", "Orders"):
        with pytest.raises(backend.BackendError):
            backend.stack_container(sb, bad, "dev")


def test_stack_container_rejects_overlong_name():
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="container name"):
        backend.stack_container(sb, "a" * 60, "production")


def test_render_uses_per_stack_container_for_main():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="main")
    assert "container_name=orders-api-dev" in lines


def test_render_uses_shared_container_for_bootstrap():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="bootstrap")
    assert "container_name=tfstate" in lines


def test_state_exists_probes_the_per_stack_container():
    calls = []

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        return _Result(0, "true\n")

    assert backend.state_exists(ENVDIR / "dev.yml", "orders-api", "dev", fake_run) is True
    assert "orders-api-dev" in calls[0]
    assert "tfstate" not in calls[0]


def test_stack_container_rejects_env_with_hyphen():
    # a hyphenated env would make the <name>-<env> join ambiguous:
    # ("orders-api-east", "dev") and ("orders-api", "east-dev") would collide
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="environment"):
        backend.stack_container(sb, "orders-api", "east-dev")


def test_stack_container_no_collision_for_adversarial_pair():
    sb = {"type": "azurerm", "container": "tfstate"}
    a = backend.stack_container(sb, "orders-api-east", "dev")
    # the colliding counterpart is rejected outright, so a collision is
    # unreachable rather than merely unlikely
    with pytest.raises(backend.BackendError):
        backend.stack_container(sb, "orders-api", "east-dev")
    assert a == "orders-api-east-dev"


def test_stack_container_rejects_too_short_name():
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="container name"):
        backend.stack_container(sb, "", "")


# --- shared stacks: per-component state ---------------------------------------


def test_main_state_key_unchanged_when_no_component():
    """Adopting components must not migrate the state of stacks that don't use
    them, so the historical key survives verbatim."""
    assert backend.state_key("orders-api", "dev") == "orders-api/dev.tfstate"
    assert backend.state_key("orders-api", "dev", component=None) == "orders-api/dev.tfstate"
    assert backend.state_key("orders-api", "dev", component="") == "orders-api/dev.tfstate"


def test_component_gets_its_own_main_state_key():
    assert (
        backend.state_key("orders-api", "dev", component="api")
        == "orders-api/components/api/dev.tfstate"
    )


def test_components_of_one_stack_never_share_a_state_key():
    keys = {
        backend.state_key("shop", "dev"),
        backend.state_key("shop", "dev", component="api"),
        backend.state_key("shop", "dev", component="worker"),
    }
    assert len(keys) == 3


def test_bootstrap_state_is_per_stack_not_per_component():
    """One resource group and one pair of plan/apply identities serve every
    component, so the bootstrap key must ignore the component."""
    assert (
        backend.state_key("orders-api", "dev", stack="bootstrap", component="api")
        == backend.state_key("orders-api", "dev", stack="bootstrap")
    )


def test_components_share_the_stack_state_container():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", component="api")
    assert "container_name=orders-api-dev" in lines
    assert "key=orders-api/components/api/dev.tfstate" in lines


def test_s3_component_key(tmp_path):
    (tmp_path / "prod.yml").write_text(
        "state_backend:\n"
        "  type: s3\n"
        "  bucket: my-tfstate\n"
        "  region: us-east-1\n"
        "  role_arn: arn:aws:iam::123456789012:role/gha-tfstate\n"
    )
    lines = backend.render(tmp_path / "prod.yml", "orders-api", "prod", component="api")
    assert "key=orders-api/components/api/prod.tfstate" in lines


@pytest.mark.parametrize("bad", ["Api", "1api", "api/../evil", "api name", "a" * 31])
def test_invalid_component_names_are_rejected(bad):
    with pytest.raises(backend.BackendError):
        backend.state_key("orders-api", "dev", component=bad)


def test_state_exists_probes_the_component_key():
    from conftest import FakeResult, FakeRunner

    run = FakeRunner([(["az", "storage", "blob", "exists"], FakeResult(0, "true"))])
    assert backend.state_exists(ENVDIR / "dev.yml", "shop", "dev", run, component="api") is True
    cmd = run.commands("az", "storage", "blob", "exists")[0]
    assert "shop/components/api/dev.tfstate" in cmd
    assert "shop-dev" in cmd
