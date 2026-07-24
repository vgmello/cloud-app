# Using the cloudapp platform

## 1. Add a manifest

`.cloud-app.yml` at your repo root:

```yaml
name: orders-api
app:
  port: 8080
database:
  size: small
environments:
  dev: {}
  prod:
    database:
      size: medium
```

## 2. Call the reusable workflow

`.github/workflows/deploy.yml` in your repo:

```yaml
name: deploy
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    uses: vgmello/cloud-app/.github/workflows/cloud-app.yml@v1
    secrets: inherit
    with:
      env: dev
      plan_only: ${{ github.event_name == 'pull_request' }}
      repo_ref: v1 # keep in lockstep with the @v1 pin above
```

## 3. Configure GitHub environments

Create a GitHub environment per manifest env key (`dev`, `prod`, ...). Put
required reviewers on `prod` — that is the approval gate. Add any manifest
`secrets:` names as environment secrets.

## Multiple databases

The singular `database:` form above still works unchanged — it provisions one
server and injects a blanket `DATABASE_URL` (Key Vault secret `database-url`)
into every app and function.

For multiple database servers or multiple logical databases per server, use
the plural `databases:` map instead. `database:` and `databases:` are
mutually exclusive. Apps and functions opt into specific `<server>/<db>`
refs; each ref injects its own `<SERVER>_<DB>_DATABASE_URL` env var:

```yaml
name: shop
apps:
  api:
    databases: [primary/orders, reporting/main]
databases:
  primary:
    type: postgres
    dbs: [orders, billing]
  reporting:
    type: sqlserver
```

Here `api` receives `PRIMARY_ORDERS_DATABASE_URL` (secret
`database-url-primary-orders`) and `REPORTING_MAIN_DATABASE_URL` (secret
`database-url-reporting-main`). App-level `databases:` applies to all of that
app's containers. Each `databases.<server>` entry also takes `size`,
`storage_gb`, `public_access`, and an optional `name` override, same as the
singular `database:` form; `dbs` defaults to `[main]`.

## Trust & identity

See [trust-modes.md](trust-modes.md) for the three deploy identities, self vs delegated execution, state backends (Azure Blob / AWS S3), and the one-time bootstrap. Delegated-mode stack ownership is governed by the [registries/](../registries/README.md) lock files.

## Notes

- Push to main deploys every environment in manifest order; the chain stops
  on first failure. Max 4 environments.
- PRs run plan-only.
- Docker: a `Dockerfile` at the repo root (or `docker:` sections) triggers
  image builds; images are built once and promoted across environments.
  Docker settings must not vary per environment; the ACR is assumed shared.
- `workflow_dispatch`-style single-env deploys: pass `environment: dev`.
- PR plan-only runs plan against the first environment only, so protected
  environment gates are never touched by PRs.
- Azure OIDC: each environment's deploy service principal (client id in
  `environments/<env>.yml`) needs a federated credential for your repo, plus
  Key Vault Secrets Officer at resource-group (or subscription) scope so
  sync-secrets can write manifest secrets.
- `runner_access: private` environments require self-hosted runners inside
  the VNet — GitHub-hosted runners cannot reach a firewalled Key Vault.
- One manifest (one platform call) per workflow run: the config artifact
  name is fixed, so calling the reusable workflow twice in a single run is
  not supported.
