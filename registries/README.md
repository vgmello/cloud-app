# Stack lock registry

Each file binds a stack name (in one environment) to the repositories allowed to
deploy it. The `deploy-stack` gate (`.github/scripts/validate_and_lock.py`)
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

## Caller usage

An app repo deploys a stack by calling the reusable workflow:

```yaml
jobs:
  deploy:
    uses: <owner>/cloud-app/.github/workflows/cloud-app.yml@main
    secrets: inherit
    with:
      env: staging
      stack_name: orders-api
```

The workflow dispatches the control repo to bootstrap the stack (creating the
RG + plan/apply identities federated to this repo), then runs the resource
deploy under those identities. `stack_name` must match the manifest name.
