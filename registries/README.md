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
  Add an entry here (via PR to this repo) to grant another repo access.
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
```

A deploy skips the bootstrap dispatch when this file's `fingerprint` matches the
one shipped with the action version the caller pinned. It is written by the
bootstrap itself; deleting it is always safe and simply makes the next deploy
bootstrap again.

### Revoking a repository's access

Removing a repo from `allowed_repos` is **not sufficient on its own.** The
federated credential that lets that repo obtain Azure tokens lives in Azure
until a bootstrap re-runs and rewrites it — and while a valid cache exists, no
bootstrap runs. To revoke access:

1. Remove the repo from `allowed_repos` in `registries/<env>/<stack>.yml`.
2. **Delete `registries/<env>/<stack>.bootstrap.yml`.**

Step 2 forces the next deploy to bootstrap, which re-federates the identities to
the remaining `allowed_repos`.

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

The action dispatches the control repo to bootstrap the stack (creating the
RG + plan/apply identities federated to this repo), then runs the resource
deploy under those identities. The stack name is the manifest `name:` — the
action resolves it from the manifest, so there is nothing to pass.
