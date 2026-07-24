"""Manifest secrets: collection and Key Vault sync."""

import hashlib
import json
import re
import time

from . import gha
from . import runner as _runner

NOT_FOUND = re.compile(r"ResourceNotFound|was not found|could not be found", re.IGNORECASE)


class SyncError(Exception):
    pass


def collect(tool):
    """Unique secret names across all containers and functions, with KV names."""
    names = set()
    for app in (tool.get("apps") or {}).values():
        for container in app["containers"].values():
            names.update(container.get("secrets", []))
    for function in (tool.get("functions") or {}).values():
        names.update(function.get("secrets", []))
    return [{"name": n, "kv_name": n.lower().replace("_", "-")} for n in sorted(names)]


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


def _vault_exists(run, vault, require_vault):
    """True if the vault exists, False if not-yet-created (tolerated on first
    deploy unless require_vault). Raise on any other az failure."""
    show = run(["az", "keyvault", "show", "--name", vault], check=False, capture=True)
    if show.returncode == 0:
        return True
    if NOT_FOUND.search(show.stderr or ""):
        if require_vault:
            raise SyncError(f"key vault {vault} still missing after the targeted apply")
        gha.notice(f"key vault {vault} not created yet; deferring secret sync")
        return False
    raise SyncError(f"az keyvault show failed for a reason other than not-found:\n{show.stderr}")


def _allowlist_runner_ip(run, vault, fetch_ip):
    """Add this runner's IP to the vault firewall. Hosted runners change IP per
    job and the firewall holds the previous apply's IP; a failure only warns."""
    runner_ip = fetch_ip()
    if not runner_ip:
        return
    rule = run(
        ["az", "keyvault", "network-rule", "add", "--name", vault,
         "--ip-address", runner_ip, "--output", "none"],
        check=False, capture=True,
    )
    if rule.returncode != 0:
        gha.warning(f"could not allowlist runner IP on {vault}; secret writes may hit the vault firewall")


def _read_secret(run, vault, kv_name):
    """Current value of a secret, or None if it does not exist."""
    r = run(
        ["az", "keyvault", "secret", "show", "--vault-name", vault,
         "--name", kv_name, "--query", "value", "-o", "tsv"],
        check=False, capture=True,
    )
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def _set_secret(run, vault, kv_name, value, sleep):
    """Idempotent secret write with one RBAC-propagation retry."""
    for attempt in (1, 2):
        result = run(
            ["az", "keyvault", "secret", "set", "--vault-name", vault,
             "--name", kv_name, "--value", value, "--output", "none"],
            check=False, capture=True,
        )
        if result.returncode == 0:
            return
        if attempt == 1:
            gha.warning(f"secret set failed for {kv_name}; retrying in 15s (RBAC propagation)")
            sleep(15)
    raise SyncError(f"failed to set secret {kv_name}:\n{result.stderr}")


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


def parse_pairs(text):
    """Parse newline-delimited NAME=value app secrets into a dict.

    Splits each non-blank line on the first '=' so values may contain '='.
    Single-line values only (the enumerated caller format cannot express a
    multiline secret). A line without '=' or with an empty name is an error.
    """
    result = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise SyncError(f"malformed app-secrets line {lineno}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise SyncError(f"malformed app-secrets line {lineno}: empty secret name")
        result[name] = value
    return result


def load_secrets(env):
    """Deploy-time secret map from the environment.

    Prefers APP_SECRETS (enumerated NAME=value pairs the caller passes to the
    cloud-app action); falls back to the legacy ALL_SECRETS JSON blob.
    """
    pairs = env.get("APP_SECRETS")
    if pairs is not None and pairs.strip():
        return parse_pairs(pairs)
    return json.loads(env.get("ALL_SECRETS") or "{}")
