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
    assert outputs == {"secret-count": 0, "vault-exists": "true", "secrets-changed": "false"}
    assert run.calls == []


def test_sync_missing_gha_secret_fails_with_names():
    with pytest.raises(secrets.SyncError, match="missing environment secrets: STRIPE_KEY"):
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
    want = secrets.sentinel_hash("orders-api", secrets.collect(tool("full")), {"STRIPE_KEY": "v"})
    run = FakeRunner([
        (("az", "keyvault", "secret", "show"), FakeResult(0, stdout=want + "\n")),
    ])
    outputs = secrets.sync(tool("full"), "kv-x", {"STRIPE_KEY": "v"}, run, fetch_ip=lambda: "1.2.3.4")
    assert run.commands("az", "keyvault", "secret", "set") == []
    assert len(run.commands("az", "keyvault", "network-rule", "add")) == 1
    assert outputs["secrets-changed"] == "false"


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
    assert len(sets) == 2
    assert "stripe-key" in sets[0]
    assert "orders-api-secrets-sentinel" in sets[1]
    assert outputs == {"secret-count": 1, "vault-exists": "true", "secrets-changed": "true"}


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


def test_sentinel_hash_is_deterministic_and_order_independent():
    a = [{"name": "A", "kv_name": "a"}, {"name": "B", "kv_name": "b"}]
    b = [{"name": "B", "kv_name": "b"}, {"name": "A", "kv_name": "a"}]
    vals = {"A": "1", "B": "2"}
    assert secrets.sentinel_hash("stk", a, vals) == secrets.sentinel_hash("stk", b, vals)


def test_sentinel_hash_changes_on_value_change():
    s = [{"name": "A", "kv_name": "a"}]
    assert secrets.sentinel_hash("stk", s, {"A": "1"}) != secrets.sentinel_hash("stk", s, {"A": "2"})


def test_sentinel_hash_changes_when_name_added():
    one = [{"name": "A", "kv_name": "a"}]
    two = [{"name": "A", "kv_name": "a"}, {"name": "B", "kv_name": "b"}]
    assert secrets.sentinel_hash("stk", one, {"A": "1"}) != secrets.sentinel_hash("stk", two, {"A": "1", "B": "2"})


def test_sentinel_hash_folds_stack_name():
    s = [{"name": "A", "kv_name": "a"}]
    vals = {"A": "1"}
    assert secrets.sentinel_hash("stk-one", s, vals) != secrets.sentinel_hash("stk-two", s, vals)


def test_sentinel_kv_name_normalizes_and_suffixes():
    assert secrets.sentinel_kv_name("orders-api") == "orders-api-secrets-sentinel"
    assert secrets.sentinel_kv_name("Orders_API.v2") == "orders-api-v2-secrets-sentinel"


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _vault_run(sentinel_value):
    """Fake `run`: vault exists; sentinel read returns sentinel_value (None => not
    found); all sets succeed. Records every command."""
    calls = []

    def run(cmd, check=False, capture=False):
        calls.append(cmd)
        if cmd[:3] == ["az", "keyvault", "show"]:
            return _Res(0)
        if cmd[:4] == ["az", "keyvault", "secret", "show"]:
            if sentinel_value is None:
                return _Res(1, "", "ResourceNotFound")
            return _Res(0, sentinel_value + "\n")
        return _Res(0)  # secret set / network-rule add

    run.calls = calls
    return run


_TOOL = {"name": "orders-api", "apps": {"api": {"containers": {"main": {"secrets": ["STRIPE_KEY"]}}}}, "functions": {}}
_ALL = {"STRIPE_KEY": "sk_1"}


def _sets(calls):
    return [c for c in calls if c[:4] == ["az", "keyvault", "secret", "set"]]


def test_sync_skips_writes_when_sentinel_matches():
    from cloudapp import secrets as s
    want = s.sentinel_hash("orders-api", s.collect(_TOOL), _ALL)
    run = _vault_run(want)
    out = s.sync(_TOOL, "kv-x", _ALL, run, fetch_ip=lambda: "", sleep=lambda _: None)
    assert _sets(run.calls) == []
    assert out["secrets-changed"] == "false"
    assert out["vault-exists"] == "true"


def test_sync_writes_all_then_sentinel_last_on_mismatch():
    from cloudapp import secrets as s
    run = _vault_run("stale-hash")
    out = s.sync(_TOOL, "kv-x", _ALL, run, fetch_ip=lambda: "", sleep=lambda _: None)
    sets = _sets(run.calls)
    # one set for the mapped secret + one for the sentinel; sentinel is last
    names = [c[c.index("--name") + 1] for c in sets]
    assert names == ["stripe-key", "orders-api-secrets-sentinel"]
    assert out["secrets-changed"] == "true"


def test_sync_writes_all_when_sentinel_absent():
    from cloudapp import secrets as s
    run = _vault_run(None)
    out = s.sync(_TOOL, "kv-x", _ALL, run, fetch_ip=lambda: "", sleep=lambda _: None)
    names = [c[c.index("--name") + 1] for c in _sets(run.calls)]
    assert names == ["stripe-key", "orders-api-secrets-sentinel"]
    assert out["secrets-changed"] == "true"


def test_sync_never_deletes():
    from cloudapp import secrets as s
    run = _vault_run("stale-hash")
    s.sync(_TOOL, "kv-x", _ALL, run, fetch_ip=lambda: "", sleep=lambda _: None)
    assert not any("delete" in c for c in run.calls)


def test_sync_rejects_secret_colliding_with_sentinel():
    from cloudapp import secrets as s
    tool = {"name": "orders-api",
            "apps": {"api": {"containers": {"main": {"secrets": ["ORDERS_API_SECRETS_SENTINEL"]}}}},
            "functions": {}}
    run = _vault_run("stale-hash")
    with pytest.raises(s.SyncError, match="sentinel"):
        s.sync(tool, "kv-x", {"ORDERS_API_SECRETS_SENTINEL": "v"}, run, fetch_ip=lambda: "", sleep=lambda _: None)


def test_sync_no_manifest_secrets_reports_unchanged():
    from cloudapp import secrets as s
    tool = {"name": "orders-api", "apps": {}, "functions": {}}
    run = _vault_run(None)
    out = s.sync(tool, "kv-x", {}, run, fetch_ip=lambda: "", sleep=lambda _: None)
    assert out["vault-exists"] == "true"
    assert out["secrets-changed"] == "false"
    assert _sets(run.calls) == []
