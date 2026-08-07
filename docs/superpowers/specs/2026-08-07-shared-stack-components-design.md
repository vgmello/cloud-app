# Shared stack state control — components

**Status:** implemented
**Follows:** `2026-07-24-multiple-databases-design.md` (which deferred
"cross-manifest / shared database references"), `2026-07-24-trust-identity-model-design.md`

## Problem

A **stack** is one manifest `name:` in one environment. The registry lock
(`registries/<env>/<stack>.yml`) already allows several repos to deploy one
stack via `allowed_repos` — that is what "shared stack" means in this platform.
But nothing below the lock was ever split:

- The main-stack Terraform state key is `<name>/<env>.tfstate`. Every repo
  deploying the stack initialises the **same state**.
- The root module builds the entire stack from one `tfvars.json`, produced from
  one manifest.

So a shared stack only worked if every repo's manifest described the whole
stack identically. The concrete failure — create a database from one repo and
an app from another, deploy them at different times:

1. The app repo cannot even express the dependency. `manifest.validate_db_refs`
   rejects `databases: [primary/orders]` unless the same manifest declares the
   `primary` server, and the schema rejected a manifest with a database and no
   compute, so the database repo could not exist either.
2. If both manifests declare everything to work around (1), each apply sees the
   other's resources missing from its config and plans to **destroy** them, and
   both try to create `kv-<name>-<env>` and — because the single-entry naming
   dedupe drops the entry key — the same `ca-<name>-<env>`.

## Decision

Add a top-level, non-overlayable `component:` key. A stack is one or more
components; each component is one manifest, in one repo, with **its own
Terraform state**.

```
stack "shop", env dev
├── state container  shop-dev                     (shared)
├── resource group   rg-shop-dev                  (shared, bootstrap-owned)
├── key vault        kv-shop-dev                  (shared, root-owned)
├── root component   shop/dev.tfstate             → databases, storage
└── component "api"  shop/components/api/dev.tfstate → ca-shop-api-dev
```

Three mechanisms, and each is doing one job:

**1. State split.** `backend.state_key` gains a component segment. A manifest
with no `component:` keeps the historical key verbatim, so adopting the feature
never migrates an existing deploy. This is what makes the two applies stop
fighting: each component's state describes only what that component owns, so
nothing the other created is ever an orphan.

**2. Name split.** `local.base` (and `naming._base`, kept in lockstep) gains the
component suffix; `local.stack_base` keeps the un-suffixed name for the
stack-wide resource group and Key Vault. Without this, two components each
declaring a single app would both dedupe to `ca-shop-dev`.

**3. Reference without ownership.** `external: true` on a `databases.<server>`
entry or on `storage:`. The entry stays in the config — the Key Vault secret
names apps are wired to are derived from the *declaration*
(`database-url-<server>-<db>`), not from the resource — but `main.tf` filters it
out of `module.database` / `module.storage`. No data source is needed, because
a consuming app needs only the secret name, and the secret lives in the shared
vault.

### Key Vault ownership

The Key Vault is stack-wide and created in the main stack, so exactly one
component must create it. The **root** component (no `component:`) does; named
components read it with `data "azurerm_key_vault"`. Alternatives considered:

- *Move the Key Vault to the bootstrap stack.* Cleaner in principle (it is
  genuinely stack-wide, like the resource group) and would help review finding
  #3, but it changes the bootstrap fingerprint, invalidating every cached
  bootstrap, and expands the bootstrap identity's surface. Deferred.
- *Per-component Key Vaults.* Defeats the point: components share a stack in
  order to share its services, database URLs included.

Consequence: a named component deployed before the root fails. `secrets.sync`
detects the missing vault and says so explicitly rather than letting the apply
fail on the data-source lookup.

### What components are not

Components bound **what Terraform believes it manages**. They are not a trust
boundary:

- One bootstrap per stack, so all components deploy under the same RG-scoped
  plan/apply identities, federated to the same `allowed_repos`.
- All component states live in the stack's single state container, and the
  apply identity's blob grant covers the container.
- One Key Vault, one secret namespace: two components declaring the same
  `secrets:` name write the same secret.

This is stated in `backend.stack_container`'s docstring, in usage.md, and in
`registries/README.md`, because "separate state" reads like isolation and here
it is not. Repos that must not reach each other's resources need separate stack
names.

## Follow-on fixes this forced

- **Per-component secret sentinel.** `secrets.sync` skipped all writes when a
  stack-wide sentinel secret matched. Two components with different secret sets
  writing to one vault would let one component's hash satisfy the other's check.
  The sentinel is now labelled `<stack>-<component>`; unsplit stacks keep the
  original label and therefore the original secret.
- **Per-component image repository.** Image tags were
  `<registry>/<stack>/<key>`, which two components would collide on. Now
  `<registry>/<stack>/<component>/<key>` — still under the `<stack>/` prefix the
  apply identity's ACR push ABAC condition requires.
- **`moved` block for the Key Vault.** Gating the module on `count` renames it
  to `module.keyvault[0]`; without the move, an upgrade would destroy and
  recreate a vault full of live secrets.

## Rejected alternatives

- **`-target` per component in one shared state.** Untargeted resources survive,
  but the consuming component's tfvars still would not contain the other's
  database declaration, so the env wiring breaks; and Terraform documents
  `-target` as an exceptional measure, not a deploy mode.
- **A stack definition in the control repo, with per-repo slices referenced from
  it.** Puts the shape of every stack in one central file, which is exactly the
  coupling the manifest model exists to avoid.
- **`terraform_remote_state` between components.** Would give a component read
  access to another's whole state and add ordering coupling for nothing — the
  only cross-component value needed is a Key Vault secret name, which is
  derivable.

## Compatibility

Every existing manifest is a root component with no `component:` key: same
state key, same names, same image repositories, same sentinel secret. The only
state-affecting change is the Key Vault `moved` block, which is a no-op for
fresh deploys.
