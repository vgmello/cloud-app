# Secret Sync Sentinel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-secret `az keyvault secret show` comparison in `secrets.sync` with a single sentinel-hash read: skip all writes when the sentinel matches, otherwise upsert every mapped secret and bump the sentinel last.

**Architecture:** Two pure helpers (`sentinel_hash`, `sentinel_kv_name`) plus a rewritten write path in `secrets.sync`. The sentinel is a reserved secret in the same Key Vault holding `SHA-256(stack_name + sorted name\0value pairs)`.

**Tech Stack:** Python engine (`engine/cloudapp/secrets.py`), Azure CLI (`az keyvault secret ...`), pytest.

## Global Constraints

- Hash material: `stack_name` then one line per secret **sorted by name**, each `f"{name}\0{value}"`, joined by `"\n"`; `hashlib.sha256(...).hexdigest()`.
- Sentinel name: `normalize(stack_name) + "-secrets-sentinel"`, where `normalize` lowercases and replaces runs of non-`[a-z0-9]` with `-` and strips leading/trailing `-`.
- Reserved: a mapped secret whose `kv_name` equals the sentinel name → `SyncError`.
- Write order: all mapped secrets first (upsert via existing `_set_secret`), sentinel **last**. Never delete.
- `sync` return dict keys: `secret-count`, `vault-exists`, and new `secrets-changed` (`"true"`/`"false"`) on every return path.
- Existing `secrets.sync` signature and the `sync-secrets` CLI/action are unchanged. `_set_secret` is unchanged. `_secret_unchanged` and the old `_push_secrets` are removed.
- Tests: `cd engine && python3 -m pytest`; lint `python3 -m ruff check .` (invoke via `python3 -m`).

---

### Task 1: Sentinel hash + name helpers

Pure functions, no `az`, no I/O — the deterministic core.

**Files:**

- Modify: `engine/cloudapp/secrets.py` (add `import hashlib`, `sentinel_hash`, `sentinel_kv_name`)
- Test: `engine/tests/py/test_secrets.py`

**Interfaces:**

- Produces: `secrets.sentinel_hash(stack_name: str, secrets: list[dict], all_secrets: dict) -> str` — `secrets` is `collect(tool)` output (`[{"name","kv_name"}]`); returns a hex SHA-256 digest, order-independent, folding in `stack_name`.
- Produces: `secrets.sentinel_kv_name(stack_name: str) -> str` — normalized `<name>-secrets-sentinel`.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_secrets.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_secrets.py -k "sentinel_hash or sentinel_kv_name" -v`
Expected: FAIL — `AttributeError: module 'cloudapp.secrets' has no attribute 'sentinel_hash'`.

- [ ] **Step 3: Implement the helpers**

In `engine/cloudapp/secrets.py`, add `hashlib` to the imports (top of file, beside `import json`):

```python
import hashlib
import json
import re
import time
```

Add these after `collect` (near the top, before `_vault_exists`):

```python
_SENTINEL_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def sentinel_kv_name(stack_name):
    """Reserved Key Vault secret name that stores the secret-set hash."""
    base = _SENTINEL_NON_ALNUM.sub("-", stack_name.lower()).strip("-")
    return f"{base}-secrets-sentinel"


def sentinel_hash(stack_name, secrets, all_secrets):
    """SHA-256 over the stack name and the sorted name\\0value pairs.

    Order-independent (sorted by name); changes when any value changes or a
    name is added/removed. The stack name is folded in for cross-vault
    distinctness (not a security control — see the design spec).
    """
    lines = [stack_name]
    for secret in sorted(secrets, key=lambda s: s["name"]):
        lines.append(f"{secret['name']}\0{all_secrets[secret['name']]}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd engine && python3 -m pytest tests/py/test_secrets.py -k "sentinel_hash or sentinel_kv_name" -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint**

Run: `cd engine && python3 -m ruff check cloudapp/secrets.py tests/py/test_secrets.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/secrets.py engine/tests/py/test_secrets.py
git commit -m "feat(secrets): sentinel hash + reserved sentinel name helpers"
```

---

### Task 2: Sentinel-gated sync write path

Rewrite `secrets.sync` to read the sentinel once and skip or write-all; remove the per-secret compare.

**Files:**

- Modify: `engine/cloudapp/secrets.py` (`sync`; remove `_secret_unchanged` + `_push_secrets`; add `_read_secret`)
- Test: `engine/tests/py/test_secrets.py`

**Interfaces:**

- Consumes: `sentinel_hash`, `sentinel_kv_name` (Task 1); `_set_secret`, `collect`, `_vault_exists`, `_allowlist_runner_ip` (unchanged).
- Produces: `secrets.sync(...)` returning `{"secret-count", "vault-exists", "secrets-changed"}`.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_secrets.py`:

```python
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
```

(These assume `import pytest` is already present in `test_secrets.py`; it is.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_secrets.py -k "sync_" -v`
Expected: FAIL — the current `sync` returns no `secrets-changed` key (`KeyError`) and does per-secret `show` compares, so the sentinel/collision assertions fail.

- [ ] **Step 3: Remove `_secret_unchanged` and `_push_secrets`; add `_read_secret`**

In `engine/cloudapp/secrets.py`, delete the `_secret_unchanged` function (lines defining it) and the `_push_secrets` function. Add `_read_secret` in their place:

```python
def _read_secret(run, vault, kv_name):
    """Current value of a secret, or None if it does not exist."""
    r = run(
        ["az", "keyvault", "secret", "show", "--vault-name", vault,
         "--name", kv_name, "--query", "value", "-o", "tsv"],
        check=False, capture=True,
    )
    return r.stdout.rstrip("\n") if r.returncode == 0 else None
```

- [ ] **Step 4: Rewrite the `sync` write path**

Replace the body of `sync` from the `_vault_exists` check onward (and add `secrets-changed` to the early returns) so the whole function reads:

```python
def sync(tool, vault, all_secrets, run, require_vault=False, fetch_ip=_runner.fetch_runner_ip,
         sleep=time.sleep):
    """Push manifest secrets into the vault. Returns action outputs.

    Reads a per-stack sentinel secret holding a hash of the current secret set;
    when it matches, skips all writes. Otherwise upserts every mapped secret and
    writes the sentinel last (crash-safe). Never deletes. Tolerates a
    not-yet-created vault (first deploy) unless require_vault; allowlists the
    runner IP first.
    """
    secrets = collect(tool)
    outputs = {"secret-count": len(secrets)}
    if not secrets:
        print("no manifest secrets to sync")
        return {**outputs, "vault-exists": "true", "secrets-changed": "false"}

    missing = [s["name"] for s in secrets if s["name"] not in all_secrets]
    if missing:
        raise SyncError("missing GitHub environment secrets: " + ", ".join(missing))

    if not _vault_exists(run, vault, require_vault):
        return {**outputs, "vault-exists": "false", "secrets-changed": "false"}

    # Only now that the vault exists do we need this runner's IP on its firewall.
    _allowlist_runner_ip(run, vault, fetch_ip)

    sentinel = sentinel_kv_name(tool["name"])
    if any(s["kv_name"] == sentinel for s in secrets):
        raise SyncError(f"a manifest secret collides with the reserved sentinel name '{sentinel}'")

    want = sentinel_hash(tool["name"], secrets, all_secrets)
    if _read_secret(run, vault, sentinel) == want:
        print("secrets unchanged (sentinel)")
        return {**outputs, "vault-exists": "true", "secrets-changed": "false"}

    for secret in secrets:
        _set_secret(run, vault, secret["kv_name"], all_secrets[secret["name"]], sleep)
        print(f"synced {secret['kv_name']}")
    _set_secret(run, vault, sentinel, want, sleep)  # last: crash-safe
    return {**outputs, "vault-exists": "true", "secrets-changed": "true"}
```

- [ ] **Step 5: Run the sync tests, full suite, and lint**

Run: `cd engine && python3 -m pytest tests/py/test_secrets.py -v && python3 -m pytest -q && python3 -m ruff check .`
Expected: the new `sync_` tests PASS; full suite green; `All checks passed!` for the engine tree.

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/secrets.py engine/tests/py/test_secrets.py
git commit -m "feat(secrets): sentinel-gated sync, drop per-secret compare"
```

---

## Self-Review

**Spec coverage:**

- `sentinel_hash` (stack name + sorted name\0value, order-independent) → Task 1. ✓
- `sentinel_kv_name` normalized + `-secrets-sentinel` → Task 1. ✓
- Read sentinel once; match → skip all writes → Task 2 `sync`. ✓
- Mismatch/absent → upsert all + sentinel last → Task 2 `sync`, tested for order. ✓
- Never delete → Task 2 test `test_sync_never_deletes`. ✓
- Reserved-name collision → `SyncError` → Task 2 `sync` + test. ✓
- `secrets-changed` on every return path → Task 2 (all four returns). ✓
- Drop `_secret_unchanged` / `_push_secrets` → Task 2 Step 3. ✓
- CLI/action/Terraform unchanged → not touched. ✓

**Placeholder scan:** No TBD/TODO; every code block is complete. `kv-x`/`sk_1`/`stale-hash` are concrete test values.

**Type consistency:** `sentinel_hash(stack_name, secrets, all_secrets)` / `sentinel_kv_name(stack_name)` signatures identical across Task 1 (def), Task 2 (call in `sync`), and tests. `_read_secret(run, vault, kv_name) -> str|None` defined and used in `sync`. `sync` return dict gains `secrets-changed` on all paths; `cmd_sync_secrets` passes the dict straight to `gha.write_outputs`, so the extra key is written harmlessly.

**Note on live validation:** the `az` calls run only on a real deploy; tests drive the `run` seam with a fake, consistent with the rest of the engine's Azure-touching code.
