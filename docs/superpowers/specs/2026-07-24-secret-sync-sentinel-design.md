# Secret Sync Sentinel — Design

**Date:** 2026-07-24
**Status:** Approved
**Repo:** `vgmello/cloud-app`

## Overview

The `sync-secrets` engine step pushes the manifest-declared secrets into the
stack's Key Vault on every apply run. Today it decides what to write by reading
each secret back first — one `az keyvault secret show` per mapped secret
(`secrets._secret_unchanged`) — so the common "nothing changed" run still costs
N reads.

Replace that per-secret comparison with a single **sentinel secret** that stores
a hash of the current secret set. Read the sentinel once; if it matches the hash
of the values we would push, skip all writes. Otherwise write every mapped
secret (upsert, never delete) and bump the sentinel last.

## Goals

- Common unchanged path: **1** `az keyvault secret show` (the sentinel) instead
  of N.
- On any change, write all mapped secrets, then update the sentinel.
- Never delete a secret (a secret dropped from the manifest lingers; its
  container reference is removed by the manifest-change Terraform run — Lane A).
- Crash-safe: a partial write never marks the set as synced.

## Non-Goals

- No change to the `sync-secrets` CLI surface (`--tool-json`,
  `--keyvault-name`, `--require-vault`) or to the action.
- No secret deletion / reconciliation of stale vault secrets.
- No change to how Terraform references secrets (version-less, unchanged).

## Security note (why hashing the values is safe here)

The sentinel is an ordinary secret in the **same Key Vault, under the same
RBAC** as the real secrets. Anyone who can read the sentinel can already read
the plaintext secrets directly, so the stored hash grants no additional
capability. Two further properties:

- The hash covers the **entire secret set concatenated**, so an offline guess
  must recover every value at once — not one.
- The stack name is folded into the hashed material. This is **not** a security
  control (the name is public, so a constant salt does not stop brute force); it
  only makes two stacks with identical secret sets produce different sentinels
  (no cross-vault correlation) and defeats generic precomputed tables. Real
  keyed protection (HMAC) is pointless here — the key would live in the same
  vault.

Net: safe by same-vault RBAC; the stack-name fold is a cheap distinctness bonus.

## Design

### Hash

`secrets.sentinel_hash(stack_name, secrets, all_secrets) -> str`

- `secrets` is `collect(tool)` (list of `{"name", "kv_name"}`), `all_secrets` the
  deploy-time `{name: value}` map.
- Canonical material: the stack name, then one line per secret **sorted by
  name**, each `name` + `"\0"` + `value`:

  ```
  material = stack_name + "\n" + "\n".join(f"{s['name']}\0{all_secrets[s['name']]}" for s in sorted(secrets, key=name))
  ```

- Return `hashlib.sha256(material.encode()).hexdigest()`.
- Deterministic and order-independent (sorted); a changed value, added name, or
  removed name changes the digest.

### Sentinel secret

`secrets.sentinel_kv_name(stack_name) -> str`

- `normalize(f"{stack_name}-secrets-sentinel")` where `normalize` lowercases and
  replaces any character outside `[a-z0-9-]` with `-` (Key Vault secret-name
  rules), collapsing to a valid name.
- **Reserved:** if any mapped secret's `kv_name` equals the sentinel name,
  `sync` raises `SyncError` (a manifest secret may not collide with the
  sentinel). In practice impossible for normal names; guarded regardless.

### Sync flow (replaces `_push_secrets` + `_secret_unchanged`)

Inside `secrets.sync`, after the vault-exists check and runner-IP allowlist
(both unchanged):

1. Compute `sentinel_name = sentinel_kv_name(tool["name"])` and guard against
   collision with any mapped `kv_name` → `SyncError`.
2. Compute `want = sentinel_hash(tool["name"], secrets, all_secrets)`.
3. Read the sentinel: `az keyvault secret show --vault-name <v> --name <sentinel_name> --query value -o tsv` (tolerate not-found → `have = None`).
4. If `have == want`: print `"secrets unchanged (sentinel)"`; return outputs with
   `secrets-changed = "false"`.
5. Else: for each mapped secret, `_set_secret` (upsert with the existing
   RBAC-propagation retry) — **no per-secret read**. Then `_set_secret` the
   sentinel to `want` **last**. Return `secrets-changed = "true"`.

`_secret_unchanged` is removed. `_set_secret` is unchanged.

**Crash-safety:** the sentinel is written only after every mapped secret write
succeeds. A failure mid-write leaves the old (or absent) sentinel → the next run
sees a mismatch and re-pushes (idempotent) before bumping the sentinel. The set
is never reported synced until all values are in place.

### Outputs

`sync` returns, unchanged, `vault-exists` and `secret-count`, plus a new
`secrets-changed` (`"true"`/`"false"`). The `sync-secrets` CLI writes it via
`gha.write_outputs`; the action does not need to consume it (available for
future use / logging).

## Files

**Modified**

- `engine/cloudapp/secrets.py` — add `sentinel_hash`, `sentinel_kv_name`,
  `_normalize` (or inline); rewrite the write path in `sync`; remove
  `_secret_unchanged` and the old `_push_secrets` per-secret compare.
- `engine/tests/py/test_secrets.py` — new tests.

No other files change (`cli.py cmd_sync_secrets`, the action, Terraform all
unchanged).

## Testing

- `sentinel_hash`: deterministic; order-independent (same digest regardless of
  input list order); changes when a value changes, a name is added, or removed;
  stack name folded in (different stack name → different digest for the same
  secrets).
- `sentinel_kv_name`: normalization (uppercase/underscore/dot → `-`, lowercased)
  and the `-secrets-sentinel` suffix.
- `sync` with a fake `run`:
  - sentinel matches → zero `secret set` calls, `secrets-changed=false`.
  - sentinel mismatch → one `set` per mapped secret **plus** the sentinel, and
    the sentinel `set` is the **last** call; `secrets-changed=true`.
  - sentinel absent (not-found) → writes all + sentinel.
  - **never** issues an `az keyvault secret delete` in any path.
  - a mapped secret colliding with the sentinel name → `SyncError`.
  - existing behavior preserved: no manifest secrets → `vault-exists=true`,
    no writes; vault missing → `vault-exists=false`, no writes; missing GitHub
    secret → `SyncError`.
- Full engine suite + `ruff` green.

## Rollout note

First run after this ships: no sentinel exists → treated as changed → all
secrets rewritten (idempotent) and the sentinel created. Subsequent unchanged
runs are a single sentinel read. Existing vault secrets are untouched except the
mapped ones (rewritten once) and the new sentinel.
