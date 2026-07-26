# Bootstrap Result Cache — Design

**Date:** 2026-07-26
**Status:** Approved
**Repo:** `vgmello/cloud-app`

## Overview

Today every deploy dispatches the control repo's `bootstrap.yml`, waits for that
workflow run to finish, and downloads an artifact to recover three values:
`resource_group`, `plan_client_id`, `apply_client_id`. On the second and every
subsequent deploy of a stack, that entire round trip re-derives values that have
not changed.

Cache those values in the control repo, keyed by `(stack, environment)`, and
skip the dispatch when the cache is current. Currency is decided by a **content
fingerprint of the bootstrap stack**, produced once in the control repo and
shipped inside the action, so the caller never computes a hash and the two sides
cannot silently disagree.

## Motivation

The dispatch costs a full cross-repo workflow round trip per deploy: dispatch →
poll → list artifacts → download a zip → parse. On run 2+ it applies a no-op
Terraform plan and returns identical values.

Removing it also removes two latent defects:

- `_download` (`.github/scripts/dispatch_and_wait.py:116`) follows GitHub's
  `302` to its Azure Blob artifact backend with the `Authorization: Bearer`
  header still attached — sending a GitHub token to a third-party host. The
  failure is swallowed as a warning, so the ids come back **empty** and the run
  fails two steps later at `azure/login` with an unrelated message.
- **Version skew.** `control-ref` defaults to `main`
  (`.github/actions/cloud-app/action.yml:36`) and flows to the dispatch `ref`
  (`:177` → `dispatch_and_wait.py:130`), so a caller pinned at `@v1` triggers a
  bootstrap running **`main`'s** Terraform. The action version and the bootstrap
  it triggers should be the same thing.

## Goals

- Skip the bootstrap dispatch when the cached result is current.
- One producer of the fingerprint (the control repo); the caller only compares.
- Invalidate automatically when the bootstrap stack or its inputs change.
- Fail safe: anything unknown, missing, unreadable, or mismatched → dispatch.
- Fix the version skew so a caller's action ref and its bootstrap are one version.

## Non-Goals

- Not caching anything about the **main** stack — this is Phase 1 only.
- Not removing `dispatch_and_wait.py`; the cache-miss path still uses it.
- Not changing the trust model. The registry gate's role is discussed below, but
  the enforcement point is unchanged.

## Design

### Versioning

The control repo publishes floating tags:

| Tag      | Moves on                      |
| -------- | ----------------------------- |
| `v1`     | every minor and patch release |
| `v1.1`   | every patch release           |
| `v1.1.1` | never                         |

Callers pin the action at whichever they want. `github.action_ref` reports the
ref the action was resolved at, which becomes the default for `control-ref` —
so the bootstrap runs the same version of the platform the caller is using.
(When the action is referenced locally as `./...`, `action_ref` is empty; the
default falls back to `main`.)

### The fingerprint

`bootstrap.fingerprint` at the repo root: a `sha256` over the sorted contents of
`terraform/azure/bootstrap/**` and `environments/**` — the bootstrap stack and
the inputs its tfvars derive from.

It is **committed to the repo**, so it ships inside the action tree at every tag.
A CI check recomputes it on every push and pull request and fails when the
committed value is stale, following the same pattern as the repo's existing
fixture-drift check. Release therefore only has to move tags; there is no
commit-then-tag ordering hazard.

Deliberately a **content** hash and not the version string: an unrelated release
(docs, a CLI change) leaves the fingerprint identical, so no stack re-bootstraps
for a change that cannot affect it.

### The cache file

`registries/<env>/<stack>.bootstrap.yml` — a **separate file from the ownership
lock**, so a routine cache write can never clobber `allowed_repos`:

```yaml
stack_name: orders-api
environment: dev
resource_group: rg-orders-api-dev
plan_client_id: 00000000-0000-0000-0000-000000000000
apply_client_id: 00000000-0000-0000-0000-000000000000
fingerprint: sha256:...
updated_at: 2026-07-26T10:00:00Z
```

Written control-side by `deploy-stack` after a successful bootstrap, recording
the fingerprint **of the tree it actually applied** (computed live from
`central-workspace`), via the existing git commit/push path. Unlike
`registry.persist_lock`, which fails closed, this write **fails open**: a push
race or any other failure warns and continues, because the cache is an
optimisation and a missing cache simply means the next deploy dispatches.

### Caller flow

Replacing the unconditional dispatch:

1. Read `${{ github.action_path }}/../../../bootstrap.fingerprint` — a local file
   from the pinned action tree. No API call, no computation.
2. Read `registries/<env>/<stack>.bootstrap.yml` from the control repo's default
   branch via the Contents API, using the App token.
3. **Use the cache** when the file parses, its `fingerprint` equals the local
   one, and all three values are non-empty → emit them as the `bootstrap` step
   outputs and skip the dispatch entirely.
4. **Dispatch** otherwise — cache absent, unreadable, malformed, stale, any value
   empty, or the run is a `workflow_dispatch` (so a manual run remains the
   operator's way to force a re-bootstrap).

The decision itself is a pure engine function so it is unit-testable; the action
only fetches and passes it the two inputs.

### Token permissions

The caller's App token gains `contents: read` alongside `actions: write`.

This is not a widening in practice: the caller already receives the entire
control repo, because `uses: vgmello/cloud-app/.github/actions/cloud-app@v1`
checks that repository out onto its runner. The added permission grants nothing
the caller does not already hold.

## Security notes

**Skipping the registry gate does not weaken the boundary.** On a cache hit the
control-side `validate-lock` does not run. The gate is bookkeeping, not the
control: the plan/apply identities' federated credentials trust only
`repo:<owner>/<allowed-repo>:environment:<env>`, so a repo holding these client
ids that is not the owner still gets nothing — `azure/login` fails on the OIDC
subject. Client ids and a resource group name are identifiers, not secrets.

**Revocation requires invalidating the cache.** Removing a repo from
`allowed_repos` does not by itself stop that repo from deploying, because the
federated credential minted for it lives in Azure until a bootstrap re-runs and
rewrites it — and with a valid cache no bootstrap runs. Revoking access must
therefore be: remove the repo from `allowed_repos` **and delete
`registries/<env>/<stack>.bootstrap.yml`**, so the next deploy re-bootstraps and
re-federates. This must be documented in `registries/README.md`; it is the one
operational sharp edge the cache introduces.

## Files

**New**

- `bootstrap.fingerprint`
- `engine/cloudapp/bootcache.py` — fingerprint computation and the use-cache decision
- `engine/tests/py/test_bootcache.py`
- `.github/workflows/release.yml` — move `v<major>` and `v<major>.<minor>` to a released tag

**Modified**

- `.github/workflows/ci.yml` — fail when `bootstrap.fingerprint` is stale
- `.github/actions/cloud-app/action.yml` — `control-ref` defaults to
  `github.action_ref`; token gains `permission-contents: read`; cache read +
  conditional dispatch
- `.github/actions/deploy-stack/action.yml` — write the cache file on success
- `engine/cloudapp/cli.py` — `bootstrap-fingerprint` and `bootstrap-cache` commands
- `registries/README.md` — the cache file, and the revocation procedure
- `docs/usage.md` — versioning and the cached path

## Testing

- `bootcache.fingerprint(paths)`: deterministic; order-independent; changes when
  any covered file changes; unaffected by files outside the covered paths.
- `bootcache.use_cache(local_fingerprint, cache)`: true only when the fingerprint
  matches and all three values are non-empty; false for a missing file, a
  malformed document, a mismatched fingerprint, and each individually empty
  value. These are the fail-safe paths and each gets its own test.
- CLI: `bootstrap-fingerprint` prints a stable digest; `bootstrap-cache` emits
  the decision plus the three values as step outputs.
- Action: YAML parses; the dispatch step is conditional on the decision; the
  cached path still reaches `azure/login` with the same output names.
- The `az`/API behaviour and `github.action_ref` population are confirmable only
  on a live run, consistent with the platform's status.

## Rollout

The first deploy of every existing stack after this ships finds no cache file,
dispatches exactly as today, and writes the cache. The second deploy is the first
to skip. No migration, and nothing to undo if the cache is deleted — deleting any
cache file simply restores today's behaviour for that stack.
