"""End-to-end coverage of the `validate-lock` CLI command against a workspace
layout. Drives cli.main in-process and asserts the authorization outcomes plus
the new-stack registration branch (git write-back faked, so it runs offline)."""

import yaml
from conftest import FakeRunner

from cloudapp import cli


def setup_workspace(tmp, *, manifest_name="orders", stack_file="cloud-app.yml",
                    lock_name=None, allowed=None, env_name="dev"):
    caller = tmp / "caller-workspace"
    caller.mkdir()
    if manifest_name is not None:
        (caller / stack_file).write_text(yaml.safe_dump({"name": manifest_name}))
    else:
        (caller / stack_file).write_text("apps: {}\n")
    reg = tmp / "central-workspace" / "registries" / env_name
    reg.mkdir(parents=True)
    if lock_name is not None:
        (reg / f"{lock_name}.yml").write_text(
            yaml.safe_dump({"stack_name": lock_name, "allowed_repos": allowed or []})
        )
    return caller


def invoke(tmp, environment, stack_file, stack_name, caller_repo, *, extra_args=None):
    return cli.main([
        "validate-lock",
        "--environment", environment,
        "--stack-file", stack_file,
        "--stack-name", stack_name,
        "--caller-repo", caller_repo,
        "--caller-root", str(tmp / "caller-workspace"),
        "--central-root", str(tmp / "central-workspace"),
        *(extra_args or []),
    ])


def test_missing_stack_file_rejected(tmp_path, capsys):
    (tmp_path / "central-workspace" / "registries" / "dev").mkdir(parents=True)
    (tmp_path / "caller-workspace").mkdir()
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_name_mismatch_rejected(tmp_path, capsys):
    setup_workspace(tmp_path, manifest_name="something-else")
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_unauthorized_repo_rejected(tmp_path, capsys):
    setup_workspace(tmp_path, lock_name="orders", allowed=["acme/orders"])
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "evil/fork")
    assert rc == 1
    assert "SECURITY VIOLATION" in capsys.readouterr().out


def test_authorized_repo_allowed(tmp_path, capsys):
    setup_workspace(tmp_path, lock_name="orders", allowed=["acme/orders"])
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 0
    assert "authorized" in capsys.readouterr().out


def test_missing_name_falls_back_to_input(tmp_path, capsys):
    setup_workspace(tmp_path, manifest_name=None, lock_name="orders", allowed=["acme/orders"])
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 0
    assert "authorized" in capsys.readouterr().out


def test_invalid_stack_name_rejected(tmp_path, capsys):
    setup_workspace(tmp_path)
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "../../evil", "acme/orders")
    assert rc == 1
    assert "invalid stack name" in capsys.readouterr().out


def test_invalid_env_rejected(tmp_path, capsys):
    setup_workspace(tmp_path)
    rc = invoke(tmp_path, "../../etc", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 1
    assert "invalid environment" in capsys.readouterr().out


def test_stack_file_traversal_rejected(tmp_path, capsys):
    setup_workspace(tmp_path)
    rc = invoke(tmp_path, "dev", "../../../etc/passwd", "orders", "acme/orders")
    assert rc == 1
    # Now caught by validate_names' charset/traversal gate, before
    # resolve_stack_path ever runs.
    assert "invalid stack file" in capsys.readouterr().out


def test_malformed_caller_repo_rejected(tmp_path, capsys):
    setup_workspace(tmp_path)
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "no-slash-here")
    assert rc == 1
    assert "invalid caller repo" in capsys.readouterr().out


def test_new_stack_registers_lock_and_pushes(tmp_path, capsys, monkeypatch):
    setup_workspace(tmp_path)  # no lock file -> first use
    fake = FakeRunner()
    monkeypatch.setattr("cloudapp.runner.run", fake)
    rc = invoke(tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders")
    assert rc == 0
    lock_path = tmp_path / "central-workspace" / "registries" / "dev" / "orders.yml"
    written = yaml.safe_load(lock_path.read_text())
    assert written["allowed_repos"] == ["acme/orders"]
    assert written["stack_name"] == "orders"
    assert [c[1] for c in fake.commands("git")] == ["config", "config", "add", "commit", "pull", "push"]


def test_new_stack_honors_the_registry_remote_flag(tmp_path, capsys, monkeypatch):
    """`--registry-remote` is the only way a production caller can override
    `persist_lock`'s `remote`; assert it actually reaches the git pull/push
    invocations rather than being accepted and silently dropped."""
    setup_workspace(tmp_path)  # no lock file -> first use
    fake = FakeRunner()
    monkeypatch.setattr("cloudapp.runner.run", fake)
    rc = invoke(
        tmp_path, "dev", "cloud-app.yml", "orders", "acme/orders",
        extra_args=["--registry-remote", "upstream"],
    )
    assert rc == 0
    assert ["git", "pull", "--rebase", "--autostash", "upstream", "main"] in fake.calls
    assert ["git", "push", "upstream", "HEAD:main"] in fake.calls
