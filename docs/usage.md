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

## Caller-supplied Terraform

For a resource the platform doesn't model, point `terraform:` at a directory of
`.tf` files in your repo:

```yaml
terraform: ./terraform
```

or, to declare extra providers, the object form:

```yaml
terraform:
  dir: ./terraform
  providers:
    - { name: random, source: hashicorp/random, version: "~> 3" }
```

Both forms are overridable per environment under `environments.<env>`, same as
everything else. The named directory's top-level `.tf` files (no
subdirectories) are copied, unmodified, into a platform-owned `custom` child
module and run as part of the main stack — so they apply under the same
RG-scoped apply identity as the rest of your resources. That scope is the
confinement for Azure resource-plane providers (`azurerm`, `azapi`): the
identity only has Contributor on the tool's resource group. It is not a
confinement for directory-scoped providers — see `azuread` under Residual
risk below.

### Providers

`azurerm` and `random` are already available (inherited from the root module).
Anything else must be declared under `terraform.providers`, and the `name`
must be one of a fixed allowlist; `source` must match exactly:

| name       | source               |
| ---------- | -------------------- |
| `random`   | `hashicorp/random`   |
| `null`     | `hashicorp/null`     |
| `tls`      | `hashicorp/tls`      |
| `time`     | `hashicorp/time`     |
| `local`    | `hashicorp/local`    |
| `external` | `hashicorp/external` |
| `azuread`  | `hashicorp/azuread`  |
| `azapi`    | `Azure/azapi`        |

### Context variables

Caller `.tf` files reference platform state as module variables:

| variable                          | description                                                                      |
| --------------------------------- | -------------------------------------------------------------------------------- |
| `resource_group_name`             | the tool's resource group — the only RG the apply identity can write             |
| `location`                        | deploy region                                                                    |
| `environment`                     | manifest environment key (`dev`, `prod`, ...)                                    |
| `tool_name`                       | manifest `name` with the platform naming prefix applied                          |
| `vnet_id`                         | landing-zone VNet id                                                             |
| `subnets`                         | landing-zone subnet ids — `private_endpoints` and `functions` (no `apps` subnet) |
| `key_vault_id`                    | the tool's Key Vault id                                                          |
| `key_vault_uri`                   | the tool's Key Vault URI                                                         |
| `app_identity_principal_ids`      | map of app key -> managed identity principal id, for role assignments            |
| `function_identity_principal_ids` | map of function key -> managed identity principal id, for role assignments       |

### Rejected

- File names starting with `_` — reserved for the platform's own files in the
  `custom` module (`_context.tf`, `_versions.tf`, the generated `_providers.g.tf`).
- A `dir` that is absolute or contains `..` — rejected by the manifest schema,
  and re-checked against the resolved repo root before files are copied.
- Any caller file with a top-level `provider "..."`, `terraform { ... }`, or
  `backend "..." { ... }` block — providers come from `terraform.providers`
  above; backend and core `terraform {}` settings belong to the platform.
- Anything that isn't a top-level `.tf` file in the named directory —
  subdirectories aren't scanned, so files inside them are silently not picked
  up.

### Residual risk

Nothing stops a caller `.tf` file from using a `local-exec` provisioner,
`data "external"`, or `data "terraform_remote_state"`. Those run arbitrary
commands on the CI runner (not just in Azure) under the same apply identity
used for the rest of the stack. This is allowed, not sandboxed further — treat
custom Terraform with the same trust as the rest of the repo's CI-executed
code.

`azuread` is on the provider allowlist but is **not** RG-scoped: it is a
directory-scoped provider whose blast radius is the Entra tenant, not the
tool's resource group. `azapi` stays fully RG-confined because it goes
through ARM under the same RBAC as `azurerm`. This is a deliberate allowlist
decision, not an oversight — treat `azuread` resources in caller `.tf` with
tenant-wide trust, not resource-group trust.

### Example

```yaml
terraform:
  dir: ./terraform
  providers:
    - { name: random, source: hashicorp/random, version: "~> 3" }
```

```hcl
# terraform/queue.tf in the caller repo
resource "azurerm_storage_queue" "jobs" {
  name                 = "jobs"
  storage_account_name = azurerm_storage_account.custom.name
}

resource "azurerm_role_assignment" "app_can_read" {
  scope                = azurerm_storage_account.custom.id
  role_definition_name = "Storage Queue Data Reader"
  # "main" is the app key the single-app `app:` shorthand folds to; adjust to
  # your app's key (e.g. the name under `apps:` if you use the map form).
  principal_id         = var.app_identity_principal_ids["main"]
}
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
