# cloud-app

A deployment platform that lets teams ship Azure resources through Terraform
without writing any. Describe an app in a small `cloud-app.yml` manifest at
the root of its repo; a composite GitHub Action, invoked as a step in your own
gated job, translates the manifest into Terraform and deploys it. Behind the
scenes each tool gets a
full stack — Container Apps / Functions / Static Web Apps, Key Vault, optional
database and blob storage — wired together over private networking by default.

Landing page: <https://vgmello.github.io/cloud-app/> (source in [`site/`](site/)).

## For app teams

Two files in your repo:

```yaml
# cloud-app.yml
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

```yaml
# .github/workflows/deploy.yml
name: deploy
on:
  push: { branches: [main] }
  pull_request:
permissions: { contents: read, id-token: write }
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

Full manifest reference and onboarding steps: [docs/usage.md](docs/usage.md).
The trust & identity model — the split topology (control bootstraps, caller deploys under RG-scoped identities), state backends, and the security boundary (wired, not yet live-validated): [docs/trust-modes.md](docs/trust-modes.md).

## What's in this repo

| Path                                     | What                                                                                                                                          |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `terraform/schema/cloud-app.schema.json` | Manifest JSON Schema                                                                                                                          |
| `engine/cloudapp/`                       | Python package with all action logic (validate, merge, normalize, build, secrets, deploy)                                                     |
| `.github/actions/cloud-app/`             | Composite deploy action (clients invoke this as a step in their own gated job)                                                                |
| `.github/actions/deploy-stack/`          | Control-side composite action (bootstraps the RG + plan/apply identities for a stack)                                                         |
| `terraform/azure/`                       | Root module + compute (`container-app`, `function`, `static-site`) and shared (`keyvault`, `database`, `storage`, `private-endpoint`) modules |
| `environments/`                          | Per-environment platform config (subscription, VNet, DNS zones, ACR, state, deploy SP)                                                        |
| `docs/superpowers/specs/`                | Design spec                                                                                                                                   |

## Manifest at a glance

- `name` + at least one compute section (`app`/`apps`, `functions`, `static_sites`).
- A `functions:` entry deploys a container by default. Add `runtime:`
  (`dotnet-isolated:8.0`, `node:20`, `python:3.11`, `java:17`, `powershell:7.4`, …)
  to deploy application code instead: supply `package:` (a directory zipped as-is)
  or a `docker`/`image` **builder** that writes build output to `/out` (zipped and
  shipped via `config-zip` after apply). Code functions require a runner that can
  reach the app's SCM endpoint — a VNet self-hosted runner when private.
- `app:` is shorthand for a single-app repo; `apps:` is a map for several.
- Each app takes a `containers:` map (Terraform `template.container` hierarchy);
  single-container fields (`cpu`, `memory`, `docker`/`image`, `env`, `secrets`)
  are shorthand that folds into `containers.main`.
- `ingress` is `public` / `internal` / `none`, or an object mirroring the
  Terraform ingress block.
- `database.type` is `postgres` (default) or `sqlserver`. Need more than one
  database? Use the plural `databases:` map instead, with per-app opt-in.
- Everything is private by default; opt out with `public_access: true` or
  `ingress: public`.
- Per-environment overrides live under `environments.<env>` and deep-merge.
- Need a resource the platform doesn't model? Point `terraform: ./terraform` at a
  directory of `*.tf` in your repo. They merge into a `custom` child module that
  receives platform context (resource group, subnets, Key Vault, per-app managed
  identity principal ids) and applies under the same RG-scoped identity — so custom
  resources are confined to your resource group for Azure resource-plane providers
  (`azurerm`, `azapi`). Extra providers are declared in the manifest from a fixed
  allowlist; see [docs/usage.md](docs/usage.md#residual-risk) for the one
  directory-scoped exception (`azuread`).

## Development

```bash
pip install -r engine/requirements-dev.txt
(cd engine && python3 -m pytest tests/py)   # action logic (the engine)
terraform -chdir=terraform/azure test       # module logic (offline, mock providers)
```

CI (`.github/workflows/ci.yml`) runs pytest, `terraform validate` + `terraform test`,
a fixture-drift check, `terraform fmt -check`, `tflint`, and actionlint on every
push to `main` and pull request.

> **Status:** the platform is fully built and tested offline, but has not yet
> been run against a live Azure subscription. A landing zone (VNet, subnets,
> private DNS zones, Container Apps environment, ACR, Terraform state storage)
> and per-environment deploy service principals with OIDC federation are
> prerequisites — see `environments/*.yml` and [docs/usage.md](docs/usage.md).

## License

MIT — see [LICENSE](LICENSE).
