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

The action dispatches the control repo to bootstrap the stack (creating the
RG + plan/apply identities federated to this repo), then runs the resource
deploy under those identities. The stack name is the manifest `name:` — the
action resolves it from the manifest, so there is nothing to pass.
