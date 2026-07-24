# Using the cloudapp platform

## 1. Add a manifest

`cloud-app.yml` at your repo root:

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

## 2. Run the cloud-app action in your own gated job

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

concurrency:
  group: cloud-app-${{ github.repository }}-dev-${{ github.event_name == 'pull_request' && 'plan' || 'apply' }}
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: vgmello/cloud-app/.github/actions/cloud-app@v1
        with:
          env: dev
          plan_only: ${{ github.event_name == 'pull_request' }}
          app-id: ${{ secrets.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          app-secrets: |
            STRIPE_KEY=${{ secrets.STRIPE_KEY }}
```

App secrets are enumerated explicitly under `app-secrets` — one `NAME=value`
per line, matching the manifest `secrets:` list.

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

## Code (non-container) functions

A `functions:` entry deploys a container image by default (`image:` or
`docker:`, same as `app`/`containers`). Adding `runtime:` switches that
function to CODE deploy instead. `runtime` is one of:

`dotnet-isolated:8.0`, `dotnet-isolated:9.0`, `node:20`, `node:22`,
`python:3.11`, `python:3.12`, `java:17`, `java:21`, `powershell:7.4`.

In code mode, supply exactly one artifact key:

- `package:` — a directory, zipped as-is and shipped unmodified. No build
  step; use this when the directory already contains the deployable output.
- `docker:` or `image:` — a **builder**, not the runtime image. The platform
  mounts a host directory at `/out`, runs the builder container, and zips
  whatever it wrote to `/out`. The builder is only responsible for producing
  build output at `/out`; it is not what runs in Azure Functions.

The function's compute plan is EP1 (Elastic Premium) regardless of mode.
Code artifacts are shipped after `terraform apply`, via
`az functionapp deployment source config-zip` against the function app's SCM
endpoint — a separate step from the Terraform apply itself, and one that
still runs even on a manifest-unchanged deploy (`always_run_terraform:
false`) since a code-only change has nothing for Terraform to diff. This
means the workflow's runner needs network access to the SCM endpoint, which
is private by default — see the `runs-on:` note in
[samples/caller-app/.github/workflows/cloud-app.yml](../samples/caller-app/.github/workflows/cloud-app.yml)
and the `runner_access: private` note below.

```yaml
functions:
  worker:
    runtime: dotnet-isolated:8.0
    docker: { file: ./Dockerfile.build } # builder writes /out
  cron:
    runtime: python:3.11
    package: ./cron # zipped as-is, no build
```

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
  name is fixed, so invoking the `cloud-app` action twice in a single run is
  not supported.
