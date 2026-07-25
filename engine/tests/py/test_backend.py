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


def test_stack_container_normalizes_trailing_hyphen():
    sb = {"type": "azurerm", "container": "tfstate"}
    # a trailing hyphen would otherwise produce the invalid "orders--dev"
    assert backend.stack_container(sb, "orders-", "dev") == "orders-dev"


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
