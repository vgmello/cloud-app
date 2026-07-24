"""The stack-lock enforcement gate runs as a script against a workspace layout;
these tests invoke it as a subprocess and assert the authorization outcomes.
The new-stack registration branch commits/pushes to git and is not exercised
offline."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[3] / ".github" / "scripts" / "validate_and_lock.py"


def run(tmp, env_name, stack_file, expected_name, caller_repo):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp,
        env={
            "PATH": "/usr/bin:/bin",
            "TARGET_ENV": env_name,
            "STACK_FILE": stack_file,
            "EXPECTED_STACK_NAME": expected_name,
            "CALLER_REPO": caller_repo,
        },
        capture_output=True,
        text=True,
    )


def setup_workspace(tmp, *, manifest_name="orders", stack_file=".cloud-app.yml",
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


def test_missing_stack_file_rejected(tmp_path):
    (tmp_path / "central-workspace" / "registries" / "dev").mkdir(parents=True)
    (tmp_path / "caller-workspace").mkdir()
    r = run(tmp_path, "dev", ".cloud-app.yml", "orders", "acme/orders")
    assert r.returncode == 1
    assert "not found" in r.stdout


def test_name_mismatch_rejected(tmp_path):
    setup_workspace(tmp_path, manifest_name="something-else")
    r = run(tmp_path, "dev", ".cloud-app.yml", "orders", "acme/orders")
    assert r.returncode == 1
    assert "MISMATCH" in r.stdout


def test_unauthorized_repo_rejected(tmp_path):
    setup_workspace(tmp_path, manifest_name="orders", lock_name="orders", allowed=["acme/orders"])
    r = run(tmp_path, "dev", ".cloud-app.yml", "orders", "evil/fork")
    assert r.returncode == 1
    assert "SECURITY VIOLATION" in r.stdout


def test_authorized_repo_allowed(tmp_path):
    setup_workspace(tmp_path, manifest_name="orders", lock_name="orders", allowed=["acme/orders"])
    r = run(tmp_path, "dev", ".cloud-app.yml", "orders", "acme/orders")
    assert r.returncode == 0
    assert "authorized" in r.stdout


def test_missing_name_falls_back_to_input(tmp_path):
    setup_workspace(tmp_path, manifest_name=None, lock_name="orders", allowed=["acme/orders"])
    r = run(tmp_path, "dev", ".cloud-app.yml", "orders", "acme/orders")
    assert r.returncode == 0
    assert "authorized" in r.stdout
