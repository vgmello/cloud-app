# Caller-supplied Terraform (`terraform:` field) — design

## Goal

Let an app team ship **extra Terraform** alongside the platform template — a
queue, an extra storage account, an in-RG role assignment — declared in their
own repo and merged into the platform's root module at deploy time. The extra
resources deploy in the **main stack**, so they run under the RG-scoped
**apply identity** (`id-<tool>-<env>-apply`, Contributor on the resource group
only). That RG scope is the confinement: caller Terraform cannot create or
touch anything outside its own resource group.

The caller reaches platform context (RG name, subnets, Key Vault, app managed
identities) through a **curated child-module interface** — never the platform's
resource internals. Additional providers are allowed but **manifest-declared
and allowlisted** so authentication stays pinned to the ambient apply identity.

This is a **trusted, additive** model: the caller repo is the same team's, and
the security boundary is the RG-scoped identity, not sandboxing the Terraform.

## Manifest field

New optional top-level field `terraform`, string shorthand or object:

```yaml
# shorthand — dir only
terraform: ./terraform

# object — dir + additional providers
terraform:
  dir: ./terraform
  providers:
    - { name: random,  source: hashicorp/random,  version: "~> 3" }
    - { name: azuread, source: hashicorp/azuread, version: "~> 3" }
```

- Optional. Absent → no custom module (the shipped `custom/` child module is
  empty and creates nothing).
- Per-environment overridable under `environments.<env>.terraform` (deep-merge,
  same as every other field). An env can point at a different dir or providers.
- `dir` — string, path in the caller repo to a directory of `*.tf`. Must be
  repo-relative with no `..` escape and not absolute.
- `providers` — optional array of `{name, source, version}`. Each `name` must
  be in the platform **provider allowlist** (below). Empty/absent = no extra
  providers.

Engine normalizes the shorthand `terraform: ./x` to `{dir: "./x", providers: []}`,
mirroring the existing `app`/`ingress` shorthand-folding pattern.

### Schema

- Add `terraform` to the top-level schema: `oneOf` a `string` (minLength 1) or
  an `object` `{dir: string, providers: [providerRef]}` with
  `additionalProperties: false`; object requires `dir`.
- `dir` pattern rejects a leading `/` and any `..` segment
  (`^(?!/)(?!.*\.\.).+$`).
- `providerRef`: `{name: string, source: string, version: string}`, all
  required, `additionalProperties: false`. `name` is an enum of the allowlist.
- Also add `terraform` to the `overlay` def so per-env overrides validate.

## Provider allowlist

Only providers whose auth is **credential-less** or the **ambient Azure apply
identity** are permitted — this is what keeps the "only the RG identity"
guarantee. The `name` enum and its `source`:

| `name`     | `source`             | Auth                                       |
| ---------- | -------------------- | ------------------------------------------ |
| `random`   | `hashicorp/random`   | none                                       |
| `null`     | `hashicorp/null`     | none                                       |
| `tls`      | `hashicorp/tls`      | none                                       |
| `time`     | `hashicorp/time`     | none                                       |
| `local`    | `hashicorp/local`    | none                                       |
| `external` | `hashicorp/external` | none (runs a program on the runner)        |
| `azuread`  | `hashicorp/azuread`  | ambient OIDC (Graph — bounded by identity) |
| `azapi`    | `Azure/azapi`        | ambient OIDC (ARM — RG-bounded)            |

- The manifest declares `name`+`source`+`version`; the engine validates
  `source` matches the allowlist's canonical source for that `name` (a caller
  cannot smuggle a different source under an allowlisted name).
- Non-allowlisted providers (e.g. `aws`, `cloudflare`, `google`) are rejected
  at validation: they need foreign credentials, which would escape the identity
  boundary.
- Terraform gives the child module **default (env-based) provider
  configurations** for these — no root-level `provider` blocks are generated,
  and `azuread`/`azapi` pick up the same `ARM_*`/`AZURE_*` env the platform's
  `azurerm` provider uses (the apply identity's OIDC token).

## Mechanics

### The `custom/` child module (shipped by the platform)

`terraform/azure/custom/` ships in the control repo with **no resources**:

- `_context.tf` — the input variables (context interface below).
- `_versions.tf` — a `terraform { required_providers { azurerm = ... } }` block
  matching the root's azurerm version (so the module is valid when empty and
  when the caller uses `azurerm_*`).
- All platform-owned files in `custom/` are `_`-prefixed; caller files may not
  start with `_` (enforced at copy).

### Root module wiring

`terraform/azure/main.tf` **always** declares the module:

```hcl
module "custom" {
  source = "./custom"

  resource_group_name             = local.rg_name
  location                        = local.location
  environment                     = local.env
  tool_name                       = local.base
  vnet_id                         = local.platform.network.vnet_id
  subnets                         = local.platform.network.subnets
  key_vault_id                    = module.keyvault.id
  key_vault_uri                   = module.keyvault.vault_uri
  app_identity_principal_ids      = { for k, m in module.container_app : k => m.identity_principal_id }
  function_identity_principal_ids = { for k, m in module.function : k => m.identity_principal_id }
}
```

- Present unconditionally. When the caller ships no `.tf`, `custom/` holds only
  variables and creates nothing — a no-op in plan/apply.
- Providers pass through by default inheritance (the child needs no explicit
  `providers = {}` map for default configs).

> **Identity outputs.** The interface exposes each app/function's managed-identity
> **principal id** (what a caller `azurerm_role_assignment` needs to grant the
> identity access to a custom resource). The container-app module already outputs
> `identity_principal_id`. The **function module does not** — add
> `output "identity_principal_id" { value = azurerm_user_assigned_identity.this.principal_id }`
> to `terraform/azure/modules/function/outputs.tf`. Small, in-scope addition;
> verify the exact local names (`local.rg_name`, `local.base`, `local.env`,
> `local.platform.network.*`) against `terraform/azure/locals.tf` when wiring.

### Action step (in the composite action, before `terraform-deploy`)

A new engine command `prepare-custom-tf` (or a step in the action) runs when
`terraform` is set in the manifest:

1. Resolve the caller dir from the normalized tool config; fail if it does not
   exist or escapes the repo.
2. Enumerate `*.tf`/`*.tf.json` (no subdirs). Reject any file whose name starts
   with `_` (reserved), and any file containing a top-level `provider "`,
   `terraform {`, or `backend "` block (grep-based lint — providers are declared
   via the manifest, not raw HCL; backend re-homing is forbidden).
3. Copy the accepted files into `<terraform-dir>/custom/`.
4. Generate `<terraform-dir>/custom/_providers.g.tf` from the manifest
   `providers` list: a single `terraform { required_providers { ... } }` block.
   When the list is empty, generate nothing (the shipped `_versions.tf` covers
   azurerm).

The copy/generate happens on the runner into the ephemeral checkout of the
control repo's `terraform/azure/` tree, before `terraform init`.

### Placement in the deploy flow

The `custom` module is part of the **main stack**, so it inherits everything the
main stack already does:

- **Plan/apply gating** — PR → plan under the plan identity (Reader); default
  branch → apply under the apply identity (Contributor on RG). No new gating.
- **State** — tracked in the same `<tool>/<env>.tfstate`.
- **Identity confinement** — the apply identity is RG-scoped, so every custom
  resource is RG-confined. This is the whole security story; nothing else is
  needed to bound Azure blast radius.

## Context interface (`custom/_context.tf`)

The curated inputs the caller `.tf` may reference — nothing else of the platform
is reachable:

| Variable                          | Type        | Purpose                                             |
| --------------------------------- | ----------- | --------------------------------------------------- |
| `resource_group_name`             | string      | place resources in the tool's RG                    |
| `location`                        | string      | region                                              |
| `environment`                     | string      | env name (dev/prod)                                 |
| `tool_name`                       | string      | base name for naming derived resources              |
| `vnet_id`                         | string      | the landing-zone VNet                               |
| `subnets`                         | object      | `{apps, functions, endpoints}` subnet ids           |
| `key_vault_id`                    | string      | grant access / add secrets to the tool's KV         |
| `key_vault_uri`                   | string      | KV reference URIs                                   |
| `app_identity_principal_ids`      | map(string) | per-app identity principal id (grant custom access) |
| `function_identity_principal_ids` | map(string) | per-function identity principal id                  |

> `tags` is intentionally omitted — the root module has no `local.tags` today.
> Adding a platform tag map and exposing it here is a reasonable follow-up if
> teams want inherited tagging; not required for the additive-resources goal.

## Guardrails (trusted mode — light)

- Copy only `*.tf`/`*.tf.json`; no subdirectories; reject `_`-prefixed filenames
  (reserved for platform-generated files).
- Reject `..`/absolute `dir`.
- Grep-reject raw `provider "…" {`, `terraform {`, and `backend "…" {` blocks in
  caller files — providers are manifest-declared and allowlisted; state stays on
  the platform backend.
- **Accepted, documented residual risk:** `local-exec`, `data "external"`, and
  `data "terraform_remote_state"` run on the runner under the apply-identity OIDC
  token (and, on the apply path, alongside the app secrets synced to Key Vault).
  This is acceptable for a same-team trusted repo — the stated model — and is
  documented, not blocked. Teams that need untrusted isolation are out of scope.

## Testing

- **Schema** — `terraform` shorthand string and object both validate; `providers`
  allowlist enum enforced; non-allowlisted provider rejected; `..`/absolute `dir`
  rejected; per-env override validates.
- **Engine** — normalization (shorthand → object); dir resolution + escape
  rejection; file filter (`.tf` only, reserved-name rejection); provider-block
  lint rejection; `_providers.g.tf` generation from the provider list; source
  mismatch rejection.
- **Terraform `tftest`** — the `custom` module receives the full context; an
  empty `custom` plans clean (no resources); a fixture custom `.tf` that creates
  a `random_pet` and an in-RG resource referencing `var.resource_group_name`
  plans successfully with the `random` provider declared.
- **Docs + sample** — usage.md section; a `samples/caller-app/terraform/` dir
  with a small example and a manifest `terraform:` entry.

## Out of scope

- Untrusted-caller sandboxing (state isolation, forbidding `local-exec`, provider
  credential firewalling beyond the allowlist).
- Providers needing non-Azure credentials (`aws`, `google`, `cloudflare`, …).
- A separate state file or separate apply identity for the custom module.
- Cross-tool / cross-RG resources (the RG-scoped identity forbids them by
  construction).
