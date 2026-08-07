# Stack lock registry

Each file binds a stack name (in one environment) to the repositories allowed to
deploy it. The `deploy-stack` gate (`cloudapp validate-lock`, in `engine/cloudapp/registry.py`)
enforces this on every delegated deploy: the first repo to deploy a given stack
name claims it (trust-on-first-use), and any later caller not in `allowed_repos`
is rejected before Terraform runs.

## Layout

```
registries/
├── dev/
│   ├── cloud-app.yml       # owner: repo-a
│   └── payment-stack.yml   # owner: repo-b
└── staging/
    └── cloud-app.yml       # owner: repo-a
```

One directory per environment; one file per stack name (`<stack-name>.yml`).

## File format

```yaml
stack_name: cloud-app
environment: staging
allowed_repos:
  - owner/repo-a
registered_at: 2026-07-24T12:00:00Z
```

- `allowed_repos` — full `owner/name` entries permitted to deploy this stack.
  Editing this list alone is **not sufficient** to grant or revoke access when
  a bootstrap cache exists for the stack — see "Granting a repository access"
  and "Revoking a repository's access" below.
- The gate creates the file automatically on first deploy; edit it to add or
  remove authorized repos.

## Bootstrap cache

Alongside each lock, `registries/<env>/<stack>.bootstrap.yml` caches what the
bootstrap produced — the resource group, the plan/apply client ids, and a
fingerprint of the bootstrap stack it was produced from:

```yaml
stack_name: orders-api
environment: dev
resource_group: rg-orders-api-dev
plan_client_id: ...
apply_client_id: ...
fingerprint: sha256:...
updated_at: 2026-07-26T10:00:00Z
```

A deploy skips the bootstrap dispatch when this file's `fingerprint` matches the
one shipped with the action version the caller pinned. It is written by the
bootstrap itself; deleting it is always safe and simply makes the next deploy
bootstrap again.

When several repos share one `allowed_repos` entry, they should all pin the
**same** action version. The cache is one file per `(stack, environment)`, but
the fingerprint each caller compares against comes from its own pinned action
tree — if repo A pins `@v1` and repo B pins `@v1.0.3` and those resolve to
different fingerprints, each deploy invalidates the other's cache, and the two
repos alternate re-bootstrapping (and re-applying) the stack on every deploy.
Mixed pins across `allowed_repos` should be treated as a misconfiguration to
fix, not a stable state.

### Force-invalidating every cached bootstrap

`CACHE_EPOCH` in `engine/cloudapp/bootcache.py` is the one-line lever to
invalidate every cached bootstrap in every environment at once, independent
of any file content — for situations the content fingerprint can't see (e.g.
a bug discovered in a past bootstrap run). Bump it and regenerate
`bootstrap.fingerprint` **in the same commit**:

```bash
PYTHONPATH=engine python3 -m cloudapp bootstrap-fingerprint --root . > bootstrap.fingerprint
```

Skipping the regeneration leaves the committed fingerprint stale, and CI's
drift check (`.github/workflows/ci.yml`, "Bootstrap fingerprint drift") fails
the build.

### Granting a repository access

Adding a repo to `allowed_repos` is **not sufficient on its own** when a valid
bootstrap cache already exists for the stack. A cache hit skips the bootstrap
dispatch entirely, so the newly-added repo's first deploy never gets a
federated credential minted for it — it hits the cache, skips straight to the
resource deploy, and `azure/login` fails with an opaque OIDC subject error. To
grant access:

1. Add the repo to `allowed_repos` in `registries/<env>/<stack>.yml`.
2. **Delete `registries/<env>/<stack>.bootstrap.yml`.**

Step 2 forces the next deploy (from any allowed repo) to bootstrap, which
federates the identities to the full, updated `allowed_repos` list — including
the new repo.

### Revoking a repository's access

Removing a repo from `allowed_repos` is **not sufficient on its own, and it is
not enough to pair with deleting the cache either.** The federated credential
that lets the revoked repo obtain Azure tokens lives in Azure until a
bootstrap re-runs and rewrites it. Deleting the cache file only forces the
_next_ deploy to dispatch a bootstrap — it does not choose who performs that
deploy. If the revoked repo itself is the one that deploys next, its dispatch
is rejected by the registry gate (`cloudapp validate-lock` /
`registry.authorize_caller`) before Terraform runs, because it is no longer in
`allowed_repos` — so no bootstrap runs and the stale federated credential
survives. To revoke access:

1. Remove the repo from `allowed_repos` in `registries/<env>/<stack>.yml`.
2. Delete `registries/<env>/<stack>.bootstrap.yml`.
3. **Trigger a deploy from a repo that is still allowed** (or delete the
   federated credential on the plan/apply identities directly in Azure),
   because only an authorized bootstrap run rewrites the federation. Until one
   of those happens, the removed repo can still obtain Azure tokens.

## Caller usage

An app repo deploys a stack by running the `cloud-app` action as a step in
its own gated job:

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: <owner>/cloud-app/.github/actions/cloud-app@main
        with:
          env: staging
          plan_only: ${{ github.event_name == 'pull_request' }}
          app-id: ${{ secrets.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
```

Set a `concurrency:` group per environment (as the sample workflow does) so
overlapping deploys to the same stack and environment serialize rather than
racing Terraform state.

## Several repos on one stack

`allowed_repos` lets more than one repo deploy a stack, but by itself it does
not say who owns what inside it — every manifest would describe the whole stack
and share one Terraform state, so each repo's apply would plan to destroy
whatever the others created. Repos sharing a stack should declare a
`component:` in their manifest: exactly one root component (no `component:`)
owning the shared services, and a named component per additional repo, each
with its own state key under `<stack>/components/<component>/`. See
[docs/usage.md](../docs/usage.md#splitting-a-stack-across-repos-components).

Components are an ownership boundary for Terraform, not a trust boundary: every
component of a stack deploys under the same plan/apply identities and shares the
stack's state container and Key Vault. Repos that must not reach each other's
resources need separate stack names.

The action dispatches the control repo to bootstrap the stack (creating the
RG + plan/apply identities federated to this repo), then runs the resource
deploy under those identities. The stack name is the manifest `name:` — the
action resolves it from the manifest, so there is nothing to pass.
