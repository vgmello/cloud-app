import pytest
from conftest import FIXTURES, FakeResult, FakeRunner

from cloudapp import manifest, secrets


def tool(fixture, env="dev"):
    _, _, tools, _ = manifest.parse(FIXTURES / f"{fixture}.yml")
    return tools[env]


def test_collect_maps_names_to_kv_names():
    assert secrets.collect(tool("full")) == [
        {"name": "STRIPE_KEY", "kv_name": "stripe-key"}
    ]


def test_collect_empty_without_secrets():
    assert secrets.collect(tool("minimal")) == []


def test_sync_no_secrets_short_circuits():
    run = FakeRunner()
    outputs = secrets.sync(tool("minimal"), "kv-x", {}, run)
    assert outputs == {"secret-count": 0, "vault-exists": "true"}
    assert run.calls == []


def test_sync_missing_gha_secret_fails_with_names():
    with pytest.raises(secrets.SyncError, match="missing GitHub environment secrets: STRIPE_KEY"):
        secrets.sync(tool("full"), "kv-x", {}, FakeRunner())


def test_sync_defers_when_vault_not_found():
    run = FakeRunner([(("az", "keyvault", "show"), FakeResult(1, stderr="(ResourceNotFound) nope"))])
    outputs = secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run)
    assert outputs["vault-exists"] == "false"


def test_sync_require_vault_fails_when_still_missing():
    run = FakeRunner([(("az", "keyvault", "show"), FakeResult(1, stderr="ResourceNotFound"))])
    with pytest.raises(secrets.SyncError, match="still missing"):
        secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run, require_vault=True)


def test_sync_other_show_errors_fail_hard():
    run = FakeRunner([(("az", "keyvault", "show"), FakeResult(1, stderr="AuthorizationFailed"))])
    with pytest.raises(secrets.SyncError, match="other than not-found"):
        secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run)


def test_sync_skips_unchanged_secret():
    run = FakeRunner([
        (("az", "keyvault", "secret", "show"), FakeResult(0, stdout="v\n")),
    ])
    secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run, fetch_ip=lambda: "1.2.3.4")
    assert run.commands("az", "keyvault", "secret", "set") == []
    assert len(run.commands("az", "keyvault", "network-rule", "add")) == 1


def test_sync_does_not_fetch_ip_when_vault_missing():
    fetched = []
    run = FakeRunner([(("az", "keyvault", "show"), FakeResult(1, stderr="ResourceNotFound"))])
    secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run,
                 fetch_ip=lambda: fetched.append(1))
    assert fetched == []


def test_sync_sets_changed_secret():
    run = FakeRunner([
        (("az", "keyvault", "secret", "show"), FakeResult(1, stderr="not found")),
    ])
    outputs = secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run, fetch_ip=lambda: None)
    sets = run.commands("az", "keyvault", "secret", "set")
    assert len(sets) == 1
    assert "stripe-key" in sets[0]
    assert outputs == {"secret-count": 1, "vault-exists": "true"}


def test_sync_retries_set_once_then_fails():
    sleeps = []
    run = FakeRunner([
        (("az", "keyvault", "secret", "show"), FakeResult(1)),
        (("az", "keyvault", "secret", "set"), FakeResult(1, stderr="rbac lag")),
    ])
    with pytest.raises(secrets.SyncError, match="failed to set secret stripe-key"):
        secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run,
                     fetch_ip=lambda: None, sleep=sleeps.append)
    assert len(run.commands("az", "keyvault", "secret", "set")) == 2
    assert sleeps == [15]


def test_parse_pairs_basic():
    assert secrets.parse_pairs("STRIPE_KEY=sk_live_123") == {"STRIPE_KEY": "sk_live_123"}


def test_parse_pairs_splits_on_first_equals():
    # base64 / values that themselves contain '='
    assert secrets.parse_pairs("TOKEN=YWJjПw==") == {"TOKEN": "YWJjПw=="}


def test_parse_pairs_multiple_and_blank_lines():
    text = "A=1\n\n  \nB=two=parts\n"
    assert secrets.parse_pairs(text) == {"A": "1", "B": "two=parts"}


def test_parse_pairs_empty_value():
    assert secrets.parse_pairs("NAME=") == {"NAME": ""}


def test_parse_pairs_missing_equals_raises():
    with pytest.raises(secrets.SyncError):
        secrets.parse_pairs("NOT_A_PAIR")


def test_parse_pairs_empty_name_raises():
    with pytest.raises(secrets.SyncError):
        secrets.parse_pairs("=value")


def test_load_secrets_prefers_app_secrets_pairs():
    env = {"APP_SECRETS": "STRIPE_KEY=sk_1", "ALL_SECRETS": '{"STRIPE_KEY":"ignored"}'}
    assert secrets.load_secrets(env) == {"STRIPE_KEY": "sk_1"}


def test_load_secrets_falls_back_to_all_secrets_json():
    env = {"ALL_SECRETS": '{"STRIPE_KEY":"sk_2"}'}
    assert secrets.load_secrets(env) == {"STRIPE_KEY": "sk_2"}


def test_load_secrets_blank_app_secrets_falls_back():
    env = {"APP_SECRETS": "   \n", "ALL_SECRETS": '{"X":"y"}'}
    assert secrets.load_secrets(env) == {"X": "y"}


def test_load_secrets_empty_returns_empty_dict():
    assert secrets.load_secrets({}) == {}
