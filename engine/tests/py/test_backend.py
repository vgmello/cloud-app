import pytest
from conftest import ENVDIR

from cloudapp import backend


def test_azurerm_main_backend_lines():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="main")
    assert lines == [
        "resource_group_name=rg-tfstate",
        "storage_account_name=sttfstatedev",
        "container_name=tfstate",
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
